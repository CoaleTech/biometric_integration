# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
import frappe
from frappe.utils.file_manager import get_file
from frappe.utils import now, now_datetime, cint
from typing import Optional, Dict, Any, Union
import json
import base64

# Use full paths for robust imports as required by the Frappe framework.
from biometric_integration.services.logger import logger

# --- Main Public Function ---

def process_device_command(device_sn: str) -> Optional[Union[str, dict]]:
    """
    Fetches the next pending command and builds the brand-specific command payload.
    This function acts as an adapter, returning the correct format for each brand.
    """
    command_name = frappe.db.get_value(
        "Biometric Device Command",
        {"biometric_device": device_sn, "status": "Pending"},
        "name",
        order_by="creation asc"
    )

    if not command_name:
        return None

    cmd_doc = frappe.get_doc("Biometric Device Command", command_name)
    
    try:
        payload = _build_command_payload(cmd_doc)
        if payload:
            cmd_doc.no_of_attempts += 1
            cmd_doc.save(ignore_permissions=True)
            frappe.db.commit()
            return payload
        else:
            # The error is handled and logged inside the build function.
            return None
            
    except Exception as e:
        # Catch any unexpected critical errors during payload processing.
        _handle_command_build_failure(cmd_doc, e, "Critical Command Processing Failure")
        return None

# --- Command Building Logic ---

def _build_command_payload(cmd_doc: frappe.Document) -> Optional[Union[str, dict]]:
    """Routes to the correct builder based on brand and handles exceptions."""
    try:
        user_doc = frappe.get_doc("Biometric Device User", cmd_doc.biometric_device_user)
        
        if cmd_doc.brand == "EBKN":
            return _build_ebkn_payload(cmd_doc, user_doc)
        elif cmd_doc.brand == "ZKTeco":
            return _build_zkteco_command(cmd_doc, user_doc)
        elif cmd_doc.brand == "Hikvision":
            return _build_hikvision_command(cmd_doc, user_doc)
        else:
            raise ValueError(f"Unsupported brand: {cmd_doc.brand}")

    except Exception as e:
        _handle_command_build_failure(cmd_doc, e, "Command Build Failed")
        return None

def _build_ebkn_payload(cmd_doc: frappe.Document, user_doc: frappe.Document) -> Optional[dict]:
    """Builds a command payload dictionary for the EBKN brand."""
    cmd_type = cmd_doc.command_type

    if cmd_type == "Delete User":
        body = json.dumps({"user_id": f"{int(user_doc.user_id):0>8}"})
        return {"trans_id": cmd_doc.name, "cmd_code": "DELETE_USER", "body": body}

    if cmd_type == "Get Enroll Data":
        body = json.dumps({"user_id": f"{int(user_doc.user_id):0>8}"})
        return {"trans_id": cmd_doc.name, "cmd_code": "GET_USER_INFO", "body": body}
    
    if cmd_type == "Enroll User":
        blob = _load_blob(user_doc.ebkn_enroll_data)
        if not blob:
            raise FileNotFoundError(f"EBKN enrollment data not found for user {user_doc.name}")
        return {"trans_id": cmd_doc.name, "cmd_code": "SET_USER_INFO", "body": blob}
        
    return None

def _build_zkteco_command(cmd_doc: frappe.Document, user_doc: frappe.Document) -> Optional[str]:
    """Builds a command string for the ZKTeco brand."""
    cmd_type = cmd_doc.command_type
    cmd_id = cmd_doc.name
    user_pin = user_doc.user_id
    user_name = user_doc.employee_name

    if cmd_type == "Delete User":
        return f"C:{cmd_id}:DATA DELETE USERINFO PIN={user_pin}"

    if cmd_type == "Get Enroll Data":
        user_cmd = f"C:{cmd_id}:DATA QUERY USERINFO PIN={user_pin}"
        fp_cmd = f"C:{cmd_id}:DATA QUERY FPTMP PIN={user_pin}"
        return "\n".join([user_cmd, fp_cmd])

    if cmd_type == "Enroll User":
        blob = _load_blob(user_doc.zkteco_enroll_data)
        if not blob:
            raise FileNotFoundError(f"ZKTeco enrollment data not found for user {user_doc.name}")
        
        template_b64 = base64.b64encode(blob).decode('utf-8')
        user_info_cmd = f"C:{cmd_id}:DATA UPDATE USERINFO PIN={user_pin}\tName={user_name}\tPri=0"
        fp_data_cmd = f"C:{cmd_id}:DATA UPDATE FINGERPRINT PIN={user_pin}\tFID=0\tSize={len(blob)}\tValid=1\tTMP={template_b64}"
        return "\n".join([user_info_cmd, fp_data_cmd])
        
    return None

def _build_hikvision_command(cmd_doc: frappe.Document, user_doc: frappe.Document) -> Optional[dict]:
    """Builds a command payload dictionary for the Hikvision brand."""
    cmd_type = cmd_doc.command_type

    if cmd_type == "Delete User":
        return {
            "Command": "DeleteUser",
            "Parameters": {
                "EmployeeNo": str(user_doc.user_id)
            }
        }

    if cmd_type == "Get Enroll Data":
        return {
            "Command": "GetUserInfo",
            "Parameters": {
                "EmployeeNo": str(user_doc.user_id)
            }
        }

    if cmd_type == "Enroll User":
        blob = _load_blob(user_doc.hikvision_enroll_data)
        if not blob:
            raise FileNotFoundError(f"Hikvision enrollment data not found for user {user_doc.name}")
        return {
            "Command": "SetUserInfo",
            "Parameters": {
                "EmployeeNo": str(user_doc.user_id),
                "Name": user_doc.employee_name,
                "EnrollData": base64.b64encode(blob).decode('utf-8')
            }
        }

    return None

# --- Helper Functions ---

def _load_blob(url: str) -> Optional[bytes]:
    """Loads a file's content by its URL, ensuring bytes are returned."""
    if not url: return None
    file_name = frappe.db.get_value("File", {"file_url": url}, "name")
    if file_name:
        content = frappe.get_doc("File", file_name).get_content()
        return content if isinstance(content, bytes) else content.encode('utf-8')
    # This is a critical error, so it will be caught and logged by the calling function.
    logger.error(f"File Not Found for URL: {url}")
    return None

def _handle_command_build_failure(cmd_doc: frappe.Document, exc: Exception, title: str):
    """
    Handles exceptions during command building by updating the command doc and
    logging a critical error for the administrator to review.
    """
    try:
        frappe.db.rollback()
        cmd_doc.reload()
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        error_line = f"[{now()}] Build Failed: {exc}"
        cmd_doc.device_response = (f"{cmd_doc.device_response}\n{error_line}" if cmd_doc.device_response else error_line)
        
        settings = frappe.get_cached_doc("Biometric Integration Settings")
        max_attempts = cint(settings.get("maximum_no_of_attempts_for_commands")) or 3

        if cmd_doc.no_of_attempts >= max_attempts:
            cmd_doc.status = "Failed"
            cmd_doc.closed_on = now_datetime()
        else:
            # Reset to Pending if there are attempts left for a retry.
            cmd_doc.status = "Pending"

        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        # Log this as a critical error in Frappe's Error Log.
        frappe.log_error(
            title=title,
            message=frappe.get_traceback(),
            reference_doctype="Biometric Device Command",
            reference_name=cmd_doc.name
        )
    except Exception as e:
        # Log a failure within the error handler itself.
        logger.error(
            f"Critical Failure in Command Error Handler for {cmd_doc.name}: {e}",
            exc_info=True
        )
        frappe.db.rollback()

