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
from biometric_integration.services.logger import logger

# --- Response Helpers ---

def plain_text_response(body: str, status_code: int = 200) -> Response:
    """Creates a standard plain text response, which is expected by ZKTeco devices."""
    return Response(body, mimetype='text/plain', status=status_code)

# --- Data Parsing Helpers ---

def _parse_key_value_data(body_str: str) -> dict:
    """Parses ZKTeco's unique key=value format."""
    data = {}
    pairs = re.findall(r'(\w+)=(\S+)', body_str)
    for key, value in pairs:
        data[key] = value
    return data

# --- Request Handlers ---

def _handle_cdata_get(query_params: dict) -> Response:
    """Handles the initial handshake from the device (GET /iclock/cdata)."""
    sn = query_params.get("SN", [None])[0]
    
    if not sn:
        frappe.log_error("ZKTeco handshake failed: Missing Serial Number (SN).", "ZKTeco Processor")
        return plain_text_response("ERROR: SN is required.", 400)
    
    logger.info(f"ZKTeco Processor: Handshake received for SN: {sn}")
    last_sync_id = frappe.db.get_value("Biometric Device", sn, "last_synced_id") or 0

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

def _handle_cdata_post(query_params: dict, raw_body: bytes) -> Response:
    """Handles data uploads (POST /iclock/cdata)."""
    sn = query_params.get("SN", [None])[0]
    table = query_params.get("table", [None])[0]
    
    if table == "ATTLOG":
        return _process_attlog(sn, raw_body)
    elif table == "OPERLOG":
        body_str = raw_body.decode('utf-8', errors='ignore')
        if "USER" in body_str:
            return _process_user_data(sn, body_str)
        if "FP" in body_str:
            return _process_fingerprint_data(sn, body_str)

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
            try:
                pin, time_str, _, _, _, _, _, log_id_str = (parts + [None]*8)[:8]
                log_id = int(log_id_str) if log_id_str and log_id_str.isdigit() else 0
                
                create_employee_checkin(
                    employee_field_value=pin,
                    timestamp=datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S"),
                    device_id=sn
                )
                processed_count += 1
                if log_id > latest_id:
                    latest_id = log_id
            except Exception as e:
                frappe.log_error(f"Failed to process ZKTeco ATTLOG line: '{line}'. Error: {e}", "ZKTeco Processor")

    if latest_id > 0 and sn:
        frappe.db.set_value("Biometric Device", sn, "last_synced_id", latest_id, update_modified=False)
        frappe.db.commit()

    return plain_text_response(f"OK: {processed_count}")

def _process_user_data(sn: str, body_str: str) -> Response:
    """Processes user data from an OPERLOG."""
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
    """Processes fingerprint templates from an OPERLOG."""
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

def _handle_getrequest(query_params: dict) -> Response:
    """Handles the device's polling for pending commands."""
    sn = query_params.get("SN", [None])[0]
    if not sn:
        return plain_text_response("ERROR: Missing SN", 400)
        
    command_to_send = process_device_command(sn)
    return plain_text_response(command_to_send or "OK")

def _handle_devicecmd(query_params: dict, raw_body: bytes) -> Response:
    """Handles the device's reply after executing a command."""
    body_str = raw_body.decode('utf-8', errors='ignore')
    
    for line in body_str.strip().split('\n'):
        params = parse_qs(line)
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

def handle_zkteco(request: Request, raw_body: bytes, headers: dict, path: str) -> Response:
    """
    The main routing function for all ZKTeco-related requests. It dispatches
    the request to the appropriate handler based on the URL path and HTTP method.
    """
    method = request.method
    
    # CORRECTED: Use the exact, case-sensitive header name as seen in the logs.
    original_uri = headers.get('X-Original-Request-Uri', '/')
    parsed_uri = urlparse(original_uri)
    query_params = parse_qs(parsed_uri.query)
    
    #logger.info(f"ZKTeco Processor: Parsed URI: {str(parsed_uri)}, Query Params: {dict(query_params)}")
    #logger.info(f"ZKTeco Processor: Routing request. Method: '{method}', Path: '{path}'")
    
    if path == "/iclock/cdata":
        return _handle_cdata_get(query_params) if method == "GET" else _handle_cdata_post(query_params, raw_body)
    
    elif path == "/iclock/getrequest":
        return _handle_getrequest(query_params)
        
    elif path == "/iclock/devicecmd":
        return _handle_devicecmd(query_params, raw_body)
    
    elif path in ["/iclock/ping", "/iclock/registry", "/iclock/edata"]:
        return plain_text_response("OK")

    logger.warning(f"ZKTeco Processor: No route matched for path '{path}' and method '{method}'. Returning 404.")
    return plain_text_response("Not Found", 404)
