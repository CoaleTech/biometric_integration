# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT
#
# DocType controller for **Biometric Device**

from __future__ import annotations
from typing import Dict, Set, List

import logging
import frappe
from frappe.model.document import Document

# ─────────────────────────────── brand helpers ───────────────────────────── #

_BRAND_BLOB_FIELD: Dict[str, str] = {
    "EBKN":    "ebkn_enroll_data",
    "ZKTeco":  "zkteco_enroll_data",
    "Suprema": "suprema_enroll_data",
}

# Import *once* to avoid circular refs
from biometric_integration.biometric_integration.doctype.biometric_device_command.biometric_device_command import (
    add_command,
)

# ────────────────────────── site-mapping utilities ───────────────────────── #

from biometric_integration.services.device_mapping import (
    load_device_site_map,
    save_device_site_map,
)


# ─────────────────────── pending-flag helper (exported) ──────────────────── #

def update_has_pending_command(device_id: str, flag: int) -> None:
	dev = frappe.get_doc("Biometric Device", device_id)
	if dev.has_pending_command != flag:
		dev.has_pending_command = flag
		dev.save(ignore_permissions=True)
		frappe.db.commit()

# ─────────────────────────────  core logic  ─────────────────────────────── #

def _sync_device_site_map(doc: "BiometricDevice", event: str) -> None:
	mp = load_device_site_map()

	if event == "on_update":
		mp[doc.name] = {
			"site_name":            frappe.local.site,
			"disabled":             doc.disabled or 0,
			"has_pending_command":  doc.has_pending_command or 0,
		}
	elif event == "on_trash":
		mp.pop(doc.name, None)

	save_device_site_map(mp)


def _active_users_with_blob(brand: str) -> List[str]:
    """User IDs that allow global enrol + already have this brand’s blob."""
    blob_field = _BRAND_BLOB_FIELD[brand]
    return frappe.get_all(
        "Biometric Device User",
        filters={
            "allow_user_in_all_devices": 1,
            blob_field: ["!=", ""],
        },
        pluck="name",
    )


def _enqueue_initial_enrolments(dev: "BiometricDevice") -> None:
    """
    For a **new** or **re-enabled** device create *Enroll User*
    commands for all applicable users.
    """
    if dev.disabled:
        return

    brand = dev.brand
    if brand not in _BRAND_BLOB_FIELD:
        return  # unknown / unsupported brand – nothing to do

    for user_id in _active_users_with_blob(brand):
        add_command(
            device_id=dev.name,
            user_id=user_id,
            brand=brand,
            command_type="Enroll User",
        )


# ───────────────────────────── controller class ─────────────────────────── #

class BiometricDevice(Document):
    """
    * on_insert → add to site-map & enqueue initial enrol
    * on_update → update map; when ‘disabled’ flips → re-enqueue
    * on_trash → remove from map
    """

    # --------------------------- creation -------------------------------- #
    def after_insert(self):
        _sync_device_site_map(self, "on_update")
        _enqueue_initial_enrolments(self)

    # -------------------------- update ----------------------------------- #
    def on_update(self):
        _sync_device_site_map(self, "on_update")
        
        before = self.get_doc_before_save()
        if before and before.disabled and not self.disabled:
            # re-enabled → queue enrols
            _enqueue_initial_enrolments(self)

    # --------------------------- delete ---------------------------------- #
    def on_trash(self):
        _sync_device_site_map(self, "on_trash")