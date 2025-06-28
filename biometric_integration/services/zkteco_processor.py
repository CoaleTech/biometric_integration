# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
import frappe
from werkzeug.wrappers import Request, Response
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Import shared functions
from .command_processor import process_device_command
from .create_checkin import create_employee_checkin

# --- Response Helpers ---

def plain_text_response(body: str) -> Response:
    """Creates a standard ZKTeco plain text response."""
    return Response(body, mimetype='text/plain')

# --- Request Handlers ---

def handle_cdata_get(request: Request) -> Response:
    """Handles the initial handshake from the device."""
    sn = request.args.get("SN")
    if not sn:
        return plain_text_response("ERROR: Missing SN")
    
    # Get the last sync timestamp for this device to prevent re-uploading old logs
    last_sync = frappe.db.get_value("Biometric Device", sn, "last_sync_on") or "0"
    
    response_body = f"""GET OPTION FROM: {sn}
ATTLOGStamp={last_sync}
OPERLOGStamp=9999
ATTPHOTOStamp=None
ErrorDelay=30
Delay=10
TransTimes=00:00;14:05
TransInterval=1
TransFlag=TransData AttLog OpLog AttPhoto EnrollUser ChgUser EnrollFP ChgFP UserPic
TimeZone=7
Realtime=1
Encrypt=None
"""
    return plain_text_response(response_body)

def handle_cdata_post(request: Request, raw_body: bytes) -> Response:
    """Handles data uploads, primarily attendance logs (ATTLOG)."""
    sn = request.args.get("SN")
    table = request.args.get("table")
    
    if table == "ATTLOG":
        body_str = raw_body.decode('utf-8', errors='ignore')
        lines = body_str.strip().split('\n')
        processed_count = 0
        latest_timestamp = None

        for line in lines:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                pin, time_str = parts[0], parts[1]
                try:
                    # Create the checkin record using the existing function
                    create_employee_checkin(
                        employee_field_value=pin,
                        timestamp=time_str,
                        device_id=sn,
                        log_type="IN" # ZKTeco doesn't always specify IN/OUT
                    )
                    processed_count += 1
                    latest_timestamp = time_str
                except Exception as e:
                    frappe.log_error(f"Failed to process ZKTeco ATTLOG line: {line}. Error: {e}", "ZKTeco Processor")
        
        # Update the last_sync_on for this device to the latest timestamp processed
        if latest_timestamp and sn:
             frappe.db.set_value("Biometric Device", sn, "last_sync_on", latest_timestamp)
             frappe.db.commit()

        return plain_text_response(f"OK: {processed_count}")

    # Handle other tables like OPERLOG if needed in the future
    return plain_text_response("OK")

def handle_getrequest(request: Request) -> Response:
    """Handles the device's request for pending commands."""
    sn = request.args.get("SN")
    if not sn:
        return plain_text_response("ERROR: Missing SN")
        
    # Use the universal command processor to get the next command
    command_to_send = process_device_command(sn)
    
    if command_to_send:
        frappe.log_error(f"Sending command to ZKTeco device {sn}: {command_to_send}", "ZKTeco Processor")
        return plain_text_response(command_to_send)
    else:
        # If no command, just send OK
        return plain_text_response("OK")

def handle_devicecmd(request: Request, raw_body: bytes) -> Response:
    """Handles the device's reply after executing a command."""
    sn = request.args.get("SN")
    body_str = raw_body.decode('utf-8', errors='ignore')
    
    # The body can contain multiple replies, separated by newlines
    for line in body_str.strip().split('\n'):
        params = dict(parse_qs(line))
        cmd_id = params.get('ID', [None])[0]
        return_code = params.get('Return', [None])[0]
        
        if cmd_id:
            try:
                cmd_doc = frappe.get_doc("Biometric Device Command", cmd_id)
                cmd_doc.device_response = (f"{cmd_doc.device_response or ''}\n{line}").strip()
                cmd_doc.status = "Success" if return_code == "0" else "Failed"
                cmd_doc.closed_on = datetime.now()
                cmd_doc.save(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                 frappe.log_error(f"Failed to update ZKTeco command reply for CmdID {cmd_id}. Error: {e}", "ZKTeco Processor")

    return plain_text_response("OK")

# --- Main Entry Point ---

def handle_zkteco(request: Request, raw_body: bytes, headers: dict) -> Response:
    """
    Main entry point for all ZKTeco requests.
    It routes the request to the appropriate handler based on the path.
    """
    path = urlparse(request.url).path
    method = request.method
    
    if path == "/iclock/cdata":
        if method == "GET":
            return handle_cdata_get(request)
        elif method == "POST":
            return handle_cdata_post(request, raw_body)
    
    elif path == "/iclock/getrequest":
        return handle_getrequest(request)
        
    elif path == "/iclock/devicecmd":
        return handle_devicecmd(request, raw_body)

    return Response("Not Found", status=404)
