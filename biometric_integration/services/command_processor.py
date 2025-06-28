# Copyright (c) 2024-2025 Zima LLC – Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
import json
import os
import frappe
from typing import Optional
from frappe.utils import now, now_datetime, cint

def _handle_command_build_failure(cmd, exc: Exception):
    """Handles exceptions during command building by updating the command doc."""
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
        
        # FIX: Use structured logging
        frappe.log_error(
            title="Command Build Failed",
            message=frappe.get_traceback(),
            reference_doctype="Biometric Device Command",
            reference_name=cmd.name
        )
    except Exception as e:
        frappe.log_error(
            title="Critical Command Processor Failure",
            message=f"Error in _handle_command_build_failure for command {cmd.name}: {e}\n\nOriginal Traceback:\n{frappe.get_traceback()}",
            reference_doctype="Biometric Device Command",
            reference_name=cmd.name
        )
        frappe.db.rollback()

def _load_blob(url: str) -> Optional[bytes]:
    """Loads a file's content by its URL."""
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

def _delete_user(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "DELETE_USER", "body": body}

def _set_user_info(cmd, user) -> Optional[dict]:
    blob = _load_blob(user.ebkn_enroll_data)
    if not blob:
        raise FileNotFoundError(f"Enrollment data blob not found for user {user.name} at URL {user.ebkn_enroll_data}")
    return {"trans_id": cmd.name, "cmd_code": "SET_USER_INFO", "body": blob}

def _get_user_info(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "GET_USER_INFO", "body": body}

def _build(cmd) -> Optional[dict]:
    """Tries to build a command. On failure, logs the error and returns None."""
    try:
        user = frappe.get_doc("Biometric Device User", cmd.biometric_device_user) if cmd.biometric_device_user else None
        if not user:
             raise ValueError("User not found for this command.")
        if cmd.brand == "EBKN":
            if cmd.command_type == "Delete User": return _delete_user(cmd, user)
            if cmd.command_type == "Enroll User": return _set_user_info(cmd, user)
            if cmd.command_type == "Get Enroll Data": return _get_user_info(cmd, user)
    except Exception as exc:
        _handle_command_build_failure(cmd, exc)
    return None

def process_device_command(device_id: str) -> Optional[dict]:
    """Efficiently fetches and processes the next pending command."""
    try:
        if not frappe.db.get_value("Biometric Device", device_id, "has_pending_command"):
            return None

        name = frappe.db.get_value(
            "Biometric Device Command",
            {"biometric_device": device_id, "status": "Pending"},
            "name",
            order_by="creation"
        )
        
        if not name:
            frappe.db.set_value("Biometric Device", device_id, "has_pending_command", 0)
            frappe.db.commit()
            return None

        cmd = frappe.get_doc("Biometric Device Command", name)
        return _build(cmd)
    except Exception:
        frappe.log_error(
            title="Command Processing Error",
            message=frappe.get_traceback(),
            reference_doctype="Biometric Device",
            reference_name=device_id
        )
        return None
