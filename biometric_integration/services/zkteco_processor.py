# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from __future__ import annotations
import frappe
from werkzeug.wrappers import Request, Response
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import re

# Use full paths for robust imports as required by the Frappe framework.
from biometric_integration.services.command_processor import process_device_command
from biometric_integration.services.create_checkin import create_employee_checkin
from biometric_integration.biometric_integration.doctype.biometric_device_user.biometric_device_user import get_or_create_user_by_pin, save_enrollment_data

# --- Response Helpers ---

def plain_text_response(body: str, status_code: int = 200) -> Response:
    """Creates a standard plain text response, which is expected by ZKTeco devices."""
    return Response(body, mimetype='text/plain', status=status_code)

# --- Data Parsing Helpers ---

def _parse_key_value_data(body_str: str) -> dict:
    """
    Parses ZKTeco's unique key=value format, handling various delimiters.
    Example: 'USER PIN=123\tName=John\tCard=456' -> {'PIN': '123', 'Name': 'John', 'Card': '456'}
    """
    data = {}
    # This regex captures key=value pairs, where the value is a sequence of non-whitespace characters.
    pairs = re.findall(r'(\w+)=(\S+)', body_str)
    for key, value in pairs:
        data[key] = value
    return data

# --- Request Handlers ---

def _handle_cdata_get(request: Request) -> Response:
    """
    Handles the initial handshake from the device (GET /iclock/cdata).
    The server responds with configuration parameters, telling the device how and when to send data.
    """
    sn = request.args.get("SN")
    if not sn:
        frappe.log_error("ZKTeco handshake failed: Missing Serial Number (SN).", "ZKTeco Processor")
        return plain_text_response("ERROR: SN is required.", 400)
    
    # Retrieve the last processed attendance log ID to prevent re-uploading old data.
    last_sync_id = frappe.db.get_value("Biometric Device", sn, "last_synced_id") or 0

    # This response body is constructed based on the ZKTeco Push Protocol specification.
    response_body = f"""GET OPTION FROM: {sn}
ATTLOGStamp={last_sync_id}
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

def _handle_cdata_post(request: Request, raw_body: bytes) -> Response:
    """
    Handles data uploads (POST /iclock/cdata). This endpoint is used for
    various data types, identified by the 'table' URL parameter.
    """
    sn = request.args.get("SN")
    table = request.args.get("table")
    
    if table == "ATTLOG":
        return _process_attlog(sn, raw_body)
    elif table == "OPERLOG":
        # OPERLOG is a multi-purpose log; its content must be inspected to determine the data type.
        body_str = raw_body.decode('utf-8', errors='ignore')
        if "USER" in body_str:
            return _process_user_data(sn, body_str)
        if "FP" in body_str:
            return _process_fingerprint_data(sn, body_str)

    # Acknowledge other unhandled table types to maintain connection.
    return plain_text_response("OK")

def _process_attlog(sn: str, raw_body: bytes) -> Response:
    """Parses and processes attendance logs (check-ins)."""
    body_str = raw_body.decode('utf-8', errors='ignore')
    lines = body_str.strip().split('\n')
    processed_count = 0
    latest_id = 0

    for line in lines:
        parts = line.strip().split('\t')
        if len(parts) >= 2:
            # Protocol format: PIN, Time, Status, Verify, Workcode, Reserved, Reserved, LogID
            try:
                pin, time_str, _, _, _, _, _, log_id_str = (parts + [None]*8)[:8]
                log_id = int(log_id_str) if log_id_str and log_id_str.isdigit() else 0
                
                create_employee_checkin(
                    employee_field_value=pin,
                    timestamp=datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S"),
                    device_id=sn,
                    log_type="IN",  # ZKTeco protocol doesn't specify IN/OUT, so a default is used.
                    log_id=log_id
                )
                processed_count += 1
                if log_id > latest_id:
                    latest_id = log_id
            except Exception as e:
                frappe.log_error(f"Failed to process ZKTeco ATTLOG line: '{line}'. Error: {e}", "ZKTeco Processor")

    # Update the last sync ID only after the batch is processed.
    if latest_id > 0 and sn:
        frappe.db.set_value("Biometric Device", sn, "last_synced_id", latest_id, update_modified=False)
        frappe.db.commit()

    return plain_text_response(f"OK: {processed_count}")

def _process_user_data(sn: str, body_str: str) -> Response:
    """Processes user data from an OPERLOG, creating Biometric Device User documents."""
    processed_count = 0
    for line in body_str.strip().split('\n'):
        if line.startswith("USER"):
            user_data = _parse_key_value_data(line)
            pin = user_data.get("PIN")
            if pin:
                get_or_create_user_by_pin(pin, user_data.get("Name"))
                processed_count += 1
    return plain_text_response(f"OK: {processed_count}")

def _process_fingerprint_data(sn: str, body_str: str) -> Response:
    """
    Processes fingerprint templates from an OPERLOG, saving the data to a file
    linked to the corresponding user for future synchronization.
    """
    # Regex to find all fingerprint templates in a single POST body.
    fp_templates = re.findall(r'FP PIN=(\S+)\s+FID=(\d+)\s+Size=(\d+)\s+Valid=(\d+)\s+TMP=(.*)', body_str)
    processed_count = 0
    for pin, fid, size, valid, template in fp_templates:
        try:
            user_doc = get_or_create_user_by_pin(pin)
            if user_doc:
                save_enrollment_data(user_doc, "ZKTeco", sn, template.encode('utf-8'))
                processed_count += 1
        except Exception as e:
            frappe.log_error(f"Failed to process fingerprint data for PIN {pin}. Error: {e}", "ZKTeco Processor")
    return plain_text_response(f"OK: {processed_count}")

def _handle_getrequest(request: Request) -> Response:
    """Handles the device's polling for pending commands (GET /iclock/getrequest)."""
    sn = request.args.get("SN")
    if not sn:
        return plain_text_response("ERROR: Missing SN", 400)
        
    command_to_send = process_device_command(sn)
    
    # It is crucial to respond with "OK" when there are no commands.
    return plain_text_response(command_to_send or "OK")

def _handle_devicecmd(request: Request, raw_body: bytes) -> Response:
    """
    Handles the device's reply after executing a command (POST /iclock/devicecmd).
    This updates the status of the corresponding Biometric Device Command document.
    """
    body_str = raw_body.decode('utf-8', errors='ignore')
    
    # The body can contain multiple replies, separated by newlines.
    for line in body_str.strip().split('\n'):
        params = parse_qs(line) # e.g., 'ID=123&Return=0&CMD=DATA' -> {'ID': ['123'], ...}
        cmd_id = params.get('ID', [None])[0]
        return_code = params.get('Return', [None])[0]
        
        if cmd_id:
            try:
                # Update the original command document with the execution result.
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
    The main routing function for all ZKTeco-related requests. It dispatches
    the request to the appropriate handler based on the URL path and HTTP method.
    """
    path = urlparse(request.url).path
    method = request.method
    
    # Routing logic based on the ZKTeco protocol specification.
    if path == "/iclock/cdata":
        return _handle_cdata_get(request) if method == "GET" else _handle_cdata_post(request, raw_body)
    
    elif path == "/iclock/getrequest" and method == "GET":
        return _handle_getrequest(request)
        
    elif path == "/iclock/devicecmd" and method == "POST":
        return _handle_devicecmd(request, raw_body)
    
    # Acknowledge other standard but unhandled protocol endpoints to ensure device stability.
    elif path in ["/iclock/ping", "/iclock/registry", "/iclock/edata"]:
        return plain_text_response("OK")

    frappe.log_warning(f"Unhandled ZKTeco path and method: {method} {path}", "ZKTeco Processor")
    return plain_text_response("Not Found", 404)

