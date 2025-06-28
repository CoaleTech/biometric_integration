# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
from typing import Iterable, Set, Dict

import frappe
from frappe.model.document import Document
from biometric_integration.biometric_integration.doctype.biometric_device_command.biometric_device_command import add_command

# ---------------------------------------------------------------------------#
#  Brand-specific blob-field map                                              #
# ---------------------------------------------------------------------------#

_BRAND_BLOB_FIELD: Dict[str, str] = {
    "EBKN":    "ebkn_enroll_data",
    "ZKTeco":  "zkteco_enroll_data",
    "Suprema": "suprema_enroll_data",
}

# ---------------------------------------------------------------------------#
#  Generic helpers                                                            #
# ---------------------------------------------------------------------------#

def _active_devices(brand: str | None = None) -> Set[str]:
    """Return names of all enabled *Biometric Device* rows (optionally per brand)."""
    flt = {"disabled": 0}
    if brand:
        flt["brand"] = brand
    return {row.name for row in frappe.get_all("Biometric Device", filters=flt)}


def get_allowed_devices(user_doc: "BiometricDeviceUser", brand: str | None = None) -> Set[str]:
    """
    Devices the *user_doc* is **allowed** to appear on.
    """
    if user_doc.allow_user_in_all_devices:
        return _active_devices(brand)

    rows = (
        [row.biometric_device for row in user_doc.devices if (not brand or row.brand == brand)]
        if user_doc.devices
        else []
    )
    return set(rows)

# ---------------------------------------------------------------------------#
#  DocType class                                                              #
# ---------------------------------------------------------------------------#

class BiometricDeviceUser(Document):
    def before_save(self):
        """The main hook that triggers all synchronization logic."""
        # The is_new() check is important to prevent errors on first save.
        # The logic is handled inside _after_save_sync.
        _after_save_sync(self)

# ---------------------------------------------------------------------------#
#  Core post-save logic — separated for testability                           #
# ---------------------------------------------------------------------------#

def _after_save_sync(doc: "BiometricDeviceUser") -> None:
    """
    Decide which device-commands are required after *doc* was saved.
    This function handles all change-detection logic.
    """
    before = doc.get_doc_before_save() if not doc.is_new() else None
    brands = set(_BRAND_BLOB_FIELD.keys())

    # --- 1. Re-enroll on blob-field changes ---
    for brand in brands:
        blob_field = _BRAND_BLOB_FIELD[brand]
        if doc.has_value_changed(blob_field) and getattr(doc, blob_field):
            
            # Find the device that was the source of this new data.
            source_device = next(
                (row.biometric_device for row in doc.devices if row.brand == brand and row.enroll_data_source),
                None,
            )
            
            # Get all devices this user should be on for this brand.
            target_devices = get_allowed_devices(doc, brand=brand)
            
            # FIX: Do not re-enroll the source device itself.
            if source_device:
                target_devices.discard(source_device)
            
            # Create "Enroll User" commands for all other target devices.
            for device_id in target_devices:
                add_command(
                    device_id=device_id,
                    user_id=doc.name,
                    brand=brand,
                    command_type="Enroll User",
                )

    # --- 2. Handle changes to flags and child tables (for existing documents only) ---
    if before:
        # Check if 'allow_user_in_all_devices' flag has changed
        if before.allow_user_in_all_devices != doc.allow_user_in_all_devices:
            for brand in brands:
                allowed_now = get_allowed_devices(doc, brand=brand)
                if doc.allow_user_in_all_devices:  # Flag turned ON -> Enroll everywhere
                    for dev in allowed_now:
                        add_command(device_id=dev, user_id=doc.name, brand=brand, command_type="Enroll User")
                else:  # Flag turned OFF -> Delete from devices not explicitly listed
                    keep = {r.biometric_device for r in doc.devices if r.brand == brand}
                    for dev in _active_devices(brand) - keep:
                        add_command(device_id=dev, user_id=doc.name, brand=brand, command_type="Delete User")

        # Check for direct additions/removals in the 'devices' child table
        if not doc.is_child_table_same("devices"):
            before_set: Dict[str, Set[str]] = {b: set() for b in brands}
            for r in before.devices:
                before_set.setdefault(r.brand, set()).add(r.biometric_device)

            after_set: Dict[str, Set[str]] = {b: set() for b in brands}
            for r in doc.devices:
                after_set.setdefault(r.brand, set()).add(r.biometric_device)

            for brand in brands:
                added = after_set[brand] - before_set[brand]
                removed = before_set[brand] - after_set[brand]
                
                # Only enqueue 'Enroll User' if we have data for that brand
                if bool(getattr(doc, _BRAND_BLOB_FIELD[brand])):
                    for dev in added:
                        add_command(device_id=dev, user_id=doc.name, brand=brand, command_type="Enroll User")
                
                for dev in removed:
                    add_command(device_id=dev, user_id=doc.name, brand=brand, command_type="Delete User")

    frappe.db.commit()
