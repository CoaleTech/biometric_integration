# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

import frappe
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime
import json
from werkzeug.wrappers import Response

from biometric_integration.services.logger import logger
from biometric_integration.services.create_checkin import create_checkin_log

def handle_hikvision(request, raw_body, headers, parsed_path):
    """
    Handle Hikvision device requests.
    This is mainly used for manual sync operations via API calls.
    """
    try:
        method = request.method
        
        if method == "POST" and parsed_path == "/hikvision/sync":
            return sync_hikvision_attendance(request)
        
        return Response("Not Found", status=404)
        
    except Exception as e:
        logger.error(f"Error in Hikvision handler: {str(e)}")
        frappe.log_error(title="Hikvision Handler Error", message=frappe.get_traceback())
        return Response("Internal Server Error", status=500)

@frappe.whitelist()
def sync_hikvision_attendance(device_serial=None, start_time=None, end_time=None):
    """
    Sync attendance data from Hikvision device.
    Can be called via API or directly as a function.
    """
    try:
        # Get device details
        if not device_serial:
            # If called via API, get from request
            if hasattr(frappe.local, 'request'):
                data = frappe.local.request.get_json() or {}
                device_serial = data.get('device_serial')
        
        if not device_serial:
            return {"error": "Device serial is required"}
        
        device = frappe.get_doc('Biometric Device', device_serial)
        
        if device.brand != 'Hikvision':
            return {"error": "Device is not a Hikvision device"}
        
        if device.disabled:
            return {"error": "Device is disabled"}
        
        # Use provided times or device settings or defaults
        if not start_time and device.sync_start_date_time:
            start_time = device.sync_start_date_time
        elif not start_time:
            # Default to today
            today = datetime.now().date()
            start_time = datetime.combine(today, datetime.strptime("00:00:00", "%H:%M:%S").time())
        
        if not end_time and device.sync_end_date_time:
            end_time = device.sync_end_date_time
        elif not end_time:
            # Default to now
            end_time = datetime.now()
        
        # Convert to strings if datetime objects
        if isinstance(start_time, datetime):
            start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%S+03:00')
        else:
            start_time_str = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%S+03:00')
        
        if isinstance(end_time, datetime):
            end_time_str = end_time.strftime('%Y-%m-%dT%H:%M:%S+03:00')
        else:
            end_time_str = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M:%S+03:00')
        
        # Sync attendance data
        result = sync_device_attendance(device, start_time_str, end_time_str)
        
        # Update last sync time
        device.last_synced_time = datetime.now()
        device.save(ignore_permissions=True)
        
        frappe.db.commit()
        
        return result
        
    except Exception as e:
        frappe.log_error(title="Hikvision Sync Error", message=frappe.get_traceback())
        return {"error": f"Error syncing attendance: {str(e)}"}

def sync_device_attendance(device, start_time, end_time):
    """
    Sync attendance data from a specific Hikvision device.
    """
    try:
        url = f"http://{device.device_ip}/ISAPI/AccessControl/AcsEvent?format=json"
        decrypted_password = device.get_password('hikvision_password')
        
        headers = {"Content-Type": "application/json"}
        
        # Initial fetch to determine total records
        payload = {
            "AcsEventCond": {
                "searchID": "123456789",
                "searchResultPosition": 0,
                "maxResults": 10,
                "major": 0,
                "minor": 0,
                "startTime": start_time,
                "endTime": end_time
            }
        }
        
        response = requests.post(
            url,
            auth=HTTPDigestAuth(device.hikvision_username, decrypted_password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=600
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch attendance logs from device {device.name}. Status: {response.status_code}")
            return {"error": f"Failed to fetch attendance logs. Status: {response.status_code}"}
        
        data = response.json()
        total_records = data.get("AcsEvent", {}).get("totalMatches", 0)
        
        if total_records == 0:
            logger.info(f"No attendance records found for device {device.name} for the given time period")
            return {"message": "No attendance records found for the given time period", "synced": 0, "skipped": 0}
        
        if total_records > 1500:
            logger.warning(f"Too many records ({total_records}) for device {device.name}. Limiting to prevent timeout.")
            return {"error": "Too many records to process. Please reduce the date range and try again."}
        
        count = 0  # Successfully synced records
        skipped = 0  # Skipped duplicates
        position = 0
        batch_size = 10
        
        logger.info(f"Starting sync for device {device.name}. Total records: {total_records}")
        
        while True:
            payload["AcsEventCond"]["searchResultPosition"] = position
            payload["AcsEventCond"]["maxResults"] = batch_size
            
            response = requests.post(
                url,
                auth=HTTPDigestAuth(device.hikvision_username, decrypted_password),
                headers=headers,
                json=payload,
                verify=False,
                timeout=600
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch batch at position {position} for device {device.name}")
                break
            
            data = response.json()
            events = data.get("AcsEvent", {}).get("InfoList", [])
            
            if not events:
                break
            
            for log in events:
                emp_no = log.get('employeeNoString')
                event_timestamp = log.get('time', '')
                attendance_status = log.get('attendanceStatus')
                
                if not emp_no or not event_timestamp:
                    continue
                    
                if attendance_status not in ['checkIn', 'checkOut']:
                    continue
                
                # Convert device time format to datetime
                try:
                    event_datetime = datetime.strptime(event_timestamp[:19], '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    logger.warning(f"Invalid timestamp format: {event_timestamp}")
                    continue
                
                # Map attendance status
                log_type = "IN" if attendance_status == "checkIn" else "OUT"
                
                # Create or find employee
                employee = find_or_create_employee(emp_no)
                if not employee:
                    logger.warning(f"Could not find or create employee for emp_no: {emp_no}")
                    continue
                
                # Check if this checkin already exists
                existing_checkin = frappe.db.exists('Employee Checkin', {
                    'employee': employee,
                    'time': event_datetime,
                    'log_type': log_type,
                    'device_id': device.name
                })
                
                if existing_checkin:
                    skipped += 1
                    continue
                
                # Create new checkin record
                try:
                    checkin_doc = create_checkin_log(
                        employee=employee,
                        timestamp=event_datetime,
                        device_id=device.name,
                        log_type=log_type
                    )
                    
                    if checkin_doc:
                        count += 1
                        logger.debug(f"Created checkin for employee {employee} at {event_datetime}")
                    
                except Exception as e:
                    logger.error(f"Failed to create checkin for employee {employee}: {str(e)}")
                    continue
            
            position += batch_size
            
            if len(events) < batch_size:
                break
        
        frappe.db.commit()
        
        result_msg = f"Synced {count} attendance records successfully. {skipped} duplicate records skipped."
        logger.info(f"Device {device.name}: {result_msg}")
        
        return {"message": result_msg, "synced": count, "skipped": skipped}
        
    except Exception as e:
        logger.error(f"Error syncing attendance for device {device.name}: {str(e)}")
        frappe.log_error(title=f"Hikvision Sync Error - {device.name}", message=frappe.get_traceback())
        return {"error": f"Error syncing attendance: {str(e)}"}

def find_or_create_employee(emp_no):
    """
    Find employee by employee number or create if not exists.
    """
    try:
        # First try to find by employee ID
        employee = frappe.db.get_value('Employee', {'employee': emp_no}, 'name')
        if employee:
            return employee
        
        # Try to find by user_id (if you use a different field for device employee number)
        employee = frappe.db.get_value('Employee', {'user_id': emp_no}, 'name')
        if employee:
            return employee
        
        # If not found, you might want to create or return None
        # For now, let's return None and log the missing employee
        logger.warning(f"Employee with number {emp_no} not found in system")
        return None
        
    except Exception as e:
        logger.error(f"Error finding employee {emp_no}: {str(e)}")
        return None

@frappe.whitelist()
def scheduled_hikvision_sync():
    """
    Scheduled function to sync all active Hikvision devices.
    """
    try:
        # Get all active Hikvision devices
        devices = frappe.get_all('Biometric Device', 
            filters={
                'brand': 'Hikvision',
                'disabled': 0
            },
            fields=['name']
        )
        
        if not devices:
            logger.info("No active Hikvision devices found for scheduled sync")
            return
        
        # Set default time range (today)
        today = datetime.now().date()
        start_time = datetime.combine(today, datetime.strptime("00:00:00", "%H:%M:%S").time())
        end_time = datetime.now()
        
        total_synced = 0
        total_skipped = 0
        
        for device_data in devices:
            try:
                result = sync_hikvision_attendance(
                    device_serial=device_data.name,
                    start_time=start_time,
                    end_time=end_time
                )
                
                if isinstance(result, dict) and 'synced' in result:
                    total_synced += result['synced']
                    total_skipped += result['skipped']
                
            except Exception as e:
                logger.error(f"Error in scheduled sync for device {device_data.name}: {str(e)}")
                continue
        
        logger.info(f"Scheduled Hikvision sync completed. Total synced: {total_synced}, Total skipped: {total_skipped}")
        
    except Exception as e:
        logger.error(f"Error in scheduled Hikvision sync: {str(e)}")
        frappe.log_error(title="Scheduled Hikvision Sync Error", message=frappe.get_traceback())