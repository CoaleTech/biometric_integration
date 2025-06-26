# Copyright (c) 2024-2025 Zima LLC – Khaled Bin Amir
# SPDX-License-Identifier: MIT
#
# Build EBKN commands (DELETE_USER / SET_USER_INFO / GET_USER_INFO)

from __future__ import annotations
import json, frappe
from typing import Optional

# ------------------------------------------------------------------ #
def _load_blob(url: str) -> Optional[bytes]:
    fid = frappe.db.get_value("File", {"file_url": url}, "name")
    return frappe.get_doc("File", fid).get_content() if fid else None

# ------------------------------------------------------------------ #
def _delete_user(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "DELETE_USER", "body": body}

def _set_user_info(cmd, user) -> Optional[dict]:
    blob = _load_blob(user.ebkn_enroll_data)
    if not blob:                      # nothing cached yet → fall back
        return _get_user_info(cmd, user)

    return {
        "trans_id": cmd.name,
        "cmd_code": "SET_USER_INFO",
        "body":     blob,             # pre-framed; send as-is
    }

def _get_user_info(cmd, user) -> dict:
    body = json.dumps({"user_id": f"{int(user.user_id):0>8}"})
    return {"trans_id": cmd.name, "cmd_code": "GET_USER_INFO", "body": body}

# ------------------------------------------------------------------ #
def _build(cmd) -> Optional[dict]:
    try:
        user = (
            frappe.get_doc("Biometric Device User", cmd.biometric_device_user)
            if cmd.biometric_device_user else None
        )
        if cmd.brand == "EBKN" and user:
            if cmd.command_type == "Delete User":
                return _delete_user(cmd, user)
            if cmd.command_type == "Enroll User":
                return _set_user_info(cmd, user)
            if cmd.command_type == "Get Enroll Data":
                return _get_user_info(cmd, user)
        # fall-through: mark unsupported …
    except Exception as exc:
        frappe.db.rollback()
        frappe.log_error(str(exc), "command build failed")
    return None

# -------------------------- public entry point ---------------------

def process_device_command(device_id: str) -> Optional[dict]:
    try:
        name = frappe.db.exists(
            "Biometric Device Command",
            {"biometric_device": device_id,
             "status": ["in", ["Pending"]]},
        )
        if not name:
            update_has_pending_command(device_id, 0)
            return None

        cmd = frappe.get_doc("Biometric Device Command", name)
        return _build(cmd)

    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "process_device_command failed")
        return None