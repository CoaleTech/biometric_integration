# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT
#
# Hook logic for *Biometric Device User* (multi-brand)

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


# ------------------------ public utility (re-usable) ------------------------ #
def get_allowed_devices(user_doc: "BiometricDeviceUser", brand: str | None = None) -> Set[str]:
    """
    Devices the *user_doc* is **allowed** to appear on.

    * If *allow_user_in_all_devices* is on → all active devices of `brand`
      (or all brands when *brand* is *None*).
    * Otherwise → devices listed in the *devices* child-table
      (again filtered by *brand* when supplied).
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

    # -------------------------------- save hook ----------------------------
    def before_save(self):
        _after_save_sync(self)


# ---------------------------------------------------------------------------#
#  Core post-save logic — separated for testability                           #
# ---------------------------------------------------------------------------#


def _after_save_sync(doc: "BiometricDeviceUser") -> None:
    """
    Decide which device-commands are required after *doc* was saved.
    Handles:

      • change of any brand-specific enrol-blob field;  
      • `allow_user_in_all_devices` flips;  
      • rows added / removed in the *devices* child table.
    """
    before = doc.get_doc_before_save()
    brands = set(_BRAND_BLOB_FIELD.keys())

    # ------------------------------------------------------------------ #
    # 1)  Blob-field changes  →  enqueue brand-specific (re)-enrol        #
    # ------------------------------------------------------------------ #
    for brand in brands:
        blob_field = _BRAND_BLOB_FIELD[brand]

        if doc.has_value_changed(blob_field):
            # Need to have *some* blob to push – skip if empty
            if not getattr(doc, blob_field):
                continue

            src_dev = next(
                (
                    row.biometric_device
                    for row in doc.devices
                    if row.brand == brand and row.enroll_data_source
                ),
                None,
            )
            targets = get_allowed_devices(doc, brand=brand)
            if src_dev:
                targets.discard(src_dev)  # already up-to-date

            for dev in targets:
                add_command(
                    device_id=dev,
                    user_id=doc.name,
                    brand=brand,
                    command_type="Enroll User",
                )

    # ------------------------------------------------------------------ #
    # 2)  allow_user_in_all_devices flag flips                            #
    # ------------------------------------------------------------------ #
    if before and before.allow_user_in_all_devices != doc.allow_user_in_all_devices:
        for brand in brands:
            allowed_now = get_allowed_devices(doc, brand=brand)

            if doc.allow_user_in_all_devices:  # turned ON → enrol everywhere
                for dev in allowed_now:
                    add_command(device_id=dev,user_id=doc.name,brand=brand,command_type="Enroll User")
            else:  # turned OFF → remove from devices not listed any more
                keep = {r.biometric_device for r in doc.devices if r.brand == brand}
                for dev in _active_devices(brand) - keep:
                    add_command(device_id=dev,user_id=doc.name,brand=brand,command_type="Delete User")

    # ------------------------------------------------------------------ #
    # 3)  Child-table mutations                                          #
    # ------------------------------------------------------------------ #
    if not doc.is_child_table_same("devices"):
        before_set: Dict[str, Set[str]] = {b: set() for b in brands}
        if before:
            for r in before.devices:
                before_set.setdefault(r.brand, set()).add(r.biometric_device)

        after_set: Dict[str, Set[str]] = {b: set() for b in brands}
        for r in doc.devices:
            after_set.setdefault(r.brand, set()).add(r.biometric_device)

        for brand in brands:
            added   = after_set[brand]  - before_set[brand]
            removed = before_set[brand] - after_set[brand]

            # Only enqueue Enrol when we *have* a blob for that brand
            blob_field = _BRAND_BLOB_FIELD[brand]
            has_blob   = bool(getattr(doc, blob_field))

            for dev in added:
                if has_blob:
                    add_command(device_id=dev,user_id=doc.name,brand=brand,command_type="Enroll User")
            for dev in removed:
                add_command(device_id=dev,user_id=doc.name,brand=brand,command_type="Delete User")

    frappe.db.commit()
