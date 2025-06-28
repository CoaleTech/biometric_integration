from __future__ import annotations
import json
import frappe
from typing import Optional
from frappe.utils import now, now_datetime, cint

# --- EBKN-specific command builders ---

def _load_ebkn_blob(url: str) -> Optional[bytes]:
    """Loads a file's content by its URL for EBKN."""
    if not url: return None
    try:
        file_name = frappe.db.get_value("File", {"file_url": url}, "name")
        if file_name:
            return frappe.get_doc("File", file_name).get_content()
        else:
            frappe.log_error(title="File Not Found in DB", message=f"Could not find a File document for URL: {url}")
            return None
    except Exception:
        frappe.log_error(title="Blob Load Exception", message=frappe.get_traceback())
        return None

def _delete_user_ebkn(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "DELETE_USER", "body": body}

def _set_user_info_ebkn(cmd, user) -> Optional[dict]:
    blob = _load_ebkn_blob(user.ebkn_enroll_data)
    if not blob:
        raise FileNotFoundError(f"EBKN enrollment blob not found for user {user.name}")
    return {"trans_id": cmd.name, "cmd_code": "SET_USER_INFO", "body": blob}

def _get_user_info_ebkn(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "GET_USER_INFO", "body": body}

# --- ZKTeco-specific command builders ---

def _build_zkteco_command(cmd, user) -> Optional[str]:
    """Builds a command string for a ZKTeco device."""
    user_pin = user.user_id
    if cmd.command_type == "Enroll User":
        return f"C:{cmd.name}:DATA UPDATE USERINFO PIN={user_pin}\tName={user.get('employee_name') or user_pin}"
    if cmd.command_type == "Delete User":
        return f"C:{cmd.name}:DATA DELETE USERINFO PIN={user_pin}"
    if cmd.command_type == "Get Enroll Data":
        return f"C:{cmd.name}:DATA QUERY USERINFO PIN={user_pin}"
    return None

# --- Main Logic ---

def _handle_command_build_failure(cmd, exc: Exception):
    """Handles exceptions during command building."""
    try:
        frappe.db.rollback()
        cmd.reload()
        cmd.no_of_attempts = (cmd.no_of_attempts or 0) + 1
        error_line = f"[{now()}] Build Failed: {str(exc)}"
        cmd.device_response = (f"{cmd.device_response}\n{error_line}" if cmd.device_response else error_line)
        
        settings = frappe.get_cached_doc("Biometric Integration Settings")
        max_attempts = cint(settings.get("maximum_no_of_attempts_for_commands")) or 3
        if cmd.no_of_attempts >= max_attempts:
            cmd.status = "Failed"
            cmd.closed_on = now_datetime()
        cmd.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Critical error in _handle_command_build_failure: {e}", "Command Processor")

def _build(cmd) -> Optional[dict | str]:
    """Tries to build a command. On failure, logs the error and returns None."""
    try:
        user = frappe.get_doc("Biometric Device User", cmd.biometric_device_user)
        
        if cmd.brand == "EBKN":
            if cmd.command_type == "Delete User": return _delete_user_ebkn(cmd, user)
            if cmd.command_type == "Enroll User": return _set_user_info_ebkn(cmd, user)
            # FIX: Restored the "Get Enroll Data" command for EBKN.
            if cmd.command_type == "Get Enroll Data": return _get_user_info_ebkn(cmd, user)
        
        elif cmd.brand == "ZKTeco":
            return _build_zkteco_command(cmd, user)

    except Exception as exc:
        _handle_command_build_failure(cmd, exc)
    return None

def process_device_command(device_id: str) -> Optional[dict | str]:
    """Fetches and processes the next pending command for a device."""
    try:
        name = frappe.db.get_value(
            "Biometric Device Command",
            {"biometric_device": device_id, "status": "Pending"},
            "name",
            order_by="creation"
        )
        if not name:
            return None
        cmd = frappe.get_doc("Biometric Device Command", name)
        return _build(cmd)
    except Exception as exc:
        frappe.log_error(f"process_device_command failed: {exc}", "Command Processor")
        return None
