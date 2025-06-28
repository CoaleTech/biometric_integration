# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
from typing import Dict, List

import frappe
from frappe.model.document import Document

# Import from the correct, absolute path
from biometric_integration.biometric_integration.doctype.biometric_device_command.biometric_device_command import add_command

# REMOVED: The update_has_pending_command function is no longer needed.

_BRAND_BLOB_FIELD: Dict[str, str] = {
    "EBKN": "ebkn_enroll_data",
    "ZKTeco": "zkteco_enroll_data",
    "Suprema": "suprema_enroll_data",
}

def _active_users_with_blob(brand: str) -> List[str]:
    """User IDs that allow global enrol + already have this brand’s blob."""
    blob_field = _BRAND_BLOB_FIELD.get(brand)
    if not blob_field: return []
    return frappe.get_all("Biometric Device User", filters={"allow_user_in_all_devices": 1, blob_field: ["is", "set"]}, pluck="name")

def _enqueue_initial_enrolments(dev: "BiometricDevice") -> None:
    """For a new or re-enabled device create Enroll User commands."""
    if dev.disabled: return
    brand = dev.brand
    if brand not in _BRAND_BLOB_FIELD: return
    for user_id in _active_users_with_blob(brand):
        add_command(device_id=dev.name, user_id=user_id, brand=brand, command_type="Enroll User")

class BiometricDevice(Document):
    def after_insert(self):
        _enqueue_initial_enrolments(self)

    def on_update(self):
        before = self.get_doc_before_save()
        if before and before.disabled and not self.disabled:
            _enqueue_initial_enrolments(self)

    def on_trash(self):
        pass
