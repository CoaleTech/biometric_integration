# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

import frappe
from biometric_integration.services.hikvision_processor import sync_hikvision_attendance, scheduled_hikvision_sync

@frappe.whitelist()
def sync_hikvision_device():
    """
    API endpoint to manually sync a specific Hikvision device.
    """
    data = frappe.local.request.get_json() or {}
    device_serial = data.get('device_serial')
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    
    return sync_hikvision_attendance(device_serial, start_time, end_time)

@frappe.whitelist()
def sync_all_hikvision_devices():
    """
    API endpoint to sync all active Hikvision devices.
    """
    return scheduled_hikvision_sync()