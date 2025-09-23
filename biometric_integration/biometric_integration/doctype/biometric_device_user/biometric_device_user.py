# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
from typing import Set, Dict, Optional

import frappe
from frappe.model.document import Document
from frappe.utils.file_manager import get_file

# Use full paths for robust imports as required by the Frappe framework.
from biometric_integration.biometric_integration.doctype.biometric_device_command.biometric_device_command import add_command

# --- Brand-specific Enrollment Data Field Map ---
# Maps a device brand to the field in this Doctype that stores the URL
# of the private file containing the user's enrollment data for that brand.
_BRAND_BLOB_FIELD: Dict[str, str] = {
    "ZKTeco":  "zkteco_enroll_data",
    "EBKN":    "ebkn_enroll_data",
    "Hikvision": "hikvision_enroll_data",
    "Suprema": "suprema_enroll_data", 
    
    # Example for future expansion
}

# --- Public Helper Functions ---

def get_or_create_user_by_pin(pin: str, name: Optional[str] = None) -> "BiometricDeviceUser":
    """
    Retrieves a BiometricDeviceUser by their PIN (user_id). If the user does not
    exist, it creates a new one. This is essential for handling data from devices
    for users who may not yet exist in Frappe.
    """
    if not pin:
        raise ValueError("PIN cannot be empty.")
        
    user_doc_name = frappe.db.exists("Biometric Device User", {"user_id": pin})
    if user_doc_name:
        return frappe.get_doc("Biometric Device User", user_doc_name)
    else:
        new_user = frappe.new_doc("Biometric Device User")
        new_user.user_id = pin
        if name:
            new_user.employee_name = name
        new_user.insert(ignore_permissions=True)
        frappe.db.commit()
        return new_user

def save_enrollment_data(user_doc: "BiometricDeviceUser", brand: str, device_sn: str, data: bytes):
    """
    Saves raw enrollment data (e.g., a fingerprint template) as a private file
    in Frappe and links its URL to the user's document.
    """
    if brand not in _BRAND_BLOB_FIELD:
        frappe.log_error(f"Attempted to save enrollment data for unsupported brand: {brand}", "BiometricDeviceUser")
        return

    blob_field = _BRAND_BLOB_FIELD[brand]
    
    # Create a new File document. Making it private is essential for security.
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{brand.lower()}_enroll_{user_doc.user_id}_{device_sn}.bin",
        "is_private": 1,
        "content": data,
        "attached_to_doctype": "Biometric Device User",
        "attached_to_name": user_doc.name,
    })
    file_doc.insert(ignore_permissions=True)
    
    # Save the URL of the file to the corresponding brand field in the user's document.
    user_doc.set(blob_field, file_doc.file_url)
    
    # Mark the device that provided this data as the "source" in the child table.
    device_found_in_table = False
    for device_detail in user_doc.get("devices", []):
        if device_detail.biometric_device == device_sn:
            device_detail.enroll_data_source = 1
            device_found_in_table = True
        elif device_detail.brand == brand:
            # Ensure only one device is marked as the source per brand.
            device_detail.enroll_data_source = 0
            
    if not device_found_in_table:
        user_doc.append("devices", {
            "biometric_device": device_sn,
            "brand": brand,
            "enroll_data_source": 1
        })
        
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()


# --- Doctype Class ---

class BiometricDeviceUser(Document):
    def after_insert(self):
        """Handle initial synchronization when a user is first created."""
        _trigger_sync_logic(self, is_new=True)

    def on_update(self):
        """Handle synchronization on subsequent document saves and updates."""
        _trigger_sync_logic(self, is_new=False)

    def on_trash(self):
        """When a user is deleted, create commands to delete them from all associated devices."""
        target_devices = _get_user_devices(self)
        for device_id, device_brand in target_devices.items():
            add_command(device_id, self.name, device_brand, "Delete User")
        frappe.db.commit()


# --- Core Synchronization Logic ---

def _trigger_sync_logic(doc: "BiometricDeviceUser", is_new: bool) -> None:
    """
    Compares the document's state before and after saving to determine which
    synchronization commands need to be created. This is the central logic hub.
    """
    before_doc = doc.get_doc_before_save() if not is_new else None
    
    # 1. Handle changes in enrollment data (e.g., new fingerprint).
    _sync_on_enrollment_data_change(doc)

    # 2. Handle changes in device assignments.
    if before_doc:
        _sync_on_device_list_change(doc, before_doc)

def _sync_on_enrollment_data_change(doc: "BiometricDeviceUser"):
    """
    If a user's enrollment data file changes, create "Enroll User" commands
    for all their other assigned devices of the same brand.
    """
    for brand, blob_field in _BRAND_BLOB_FIELD.items():
        if doc.has_value_changed(blob_field) and doc.get(blob_field):
            target_devices = _get_user_devices(doc, brand=brand)
            
            # Find the device that was the source of this new data.
            source_device = next(
                (row.biometric_device for row in doc.devices if row.brand == brand and row.enroll_data_source),
                None
            )
            
            # Create "Enroll User" commands for all target devices except the source.
            for device_id in target_devices:
                if device_id != source_device:
                    add_command(device_id, doc.name, brand, "Enroll User")

def _sync_on_device_list_change(doc: "BiometricDeviceUser", before_doc: "BiometricDeviceUser"):
    """
    Compares the device list before and after the save to find added or
    removed devices and creates the corresponding commands.
    """
    devices_before = _get_user_devices(before_doc)
    devices_after = _get_user_devices(doc)

    added_devices = set(devices_after.keys()) - set(devices_before.keys())
    removed_devices = set(devices_before.keys()) - set(devices_after.keys())

    for device_id in added_devices:
        brand = devices_after[device_id]
        # Only create an enroll command if enrollment data for that brand exists.
        if doc.get(_BRAND_BLOB_FIELD.get(brand)):
            add_command(device_id, doc.name, brand, "Enroll User")

    for device_id in removed_devices:
        brand = devices_before[device_id]
        add_command(device_id, doc.name, brand, "Delete User")

# --- Private Helper ---

def _get_user_devices(doc: "BiometricDeviceUser", brand: str | None = None) -> Dict[str, str]:
    """
    Returns a dictionary of a user's assigned devices {device_id: brand}.
    """
    if doc.allow_user_in_all_devices:
        filters = {"disabled": 0}
        if brand:
            filters["brand"] = brand
        all_devices = frappe.get_all("Biometric Device", filters=filters, fields=["name", "brand"])
        return {d.name: d.brand for d in all_devices}
    else:
        # Get from the child table.
        user_devices = doc.get("devices", [])
        return {
            row.biometric_device: row.brand for row in user_devices
            if row.biometric_device and (not brand or row.brand == brand)
        }
