# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

import frappe
from werkzeug.wrappers import Response
from urllib.parse import urlparse

# Use full paths for robust imports as required by the Frappe framework.
from biometric_integration.services.ebkn_processor import handle_ebkn
from biometric_integration.services.zkteco_processor import handle_zkteco
from biometric_integration.services.logger import logger

# --- Header Transformation Map ---
# Provides a compatibility layer for Nginx, which may alter header names.
NGINX_TO_ORIGINAL_HEADERS = {
    "x-request-code": "request_code",
    "x-dev-id": "dev_id",
    "x-trans-id": "trans_id",
    "x-cmd-return-code": "cmd_return_code",
    "x-blk-no": "blk_no",
}

@frappe.whitelist(allow_guest=True)
def handle_request():
    """
    Acts as the single entry point for all incoming biometric device requests.
    It routes requests to the appropriate brand-specific processor based on the URL path.
    """
    original_user = frappe.session.user
    request = frappe.local.request

    original_uri = request.headers.get('X-Original-Request-URI', '/')
    parsed_path = urlparse(original_uri).path
    
    remote_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    try:
        frappe.set_user("Administrator")

        handler = None
        is_ebkn = False
        if parsed_path.startswith('/iclock/'):
            handler = handle_zkteco
        elif parsed_path == '/ebkn' or parsed_path == '/ebkn/':
            handler = handle_ebkn
            is_ebkn = True
        
        if not handler:
            logger.warning(f"No registered handler for path: {parsed_path}")
            return Response(f"No handler for path: {parsed_path}", status=404)

        # Reconstruct headers: Copy all original headers, then alter/add specific ones.
        reconstructed_headers = dict(request.headers)
        if is_ebkn:
            for nginx_header, original_header in NGINX_TO_ORIGINAL_HEADERS.items():
                if nginx_header in request.headers:
                    reconstructed_headers[original_header] = request.headers[nginx_header]

        raw_body = request.get_data(cache=False)
        
        # SIMPLIFIED: Call all handlers with the same, consistent signature.
        # The handlers themselves will decide which arguments they need to use.
        handler_output = handler(request, raw_body, reconstructed_headers, parsed_path)

        # --- RESPONSE ADAPTER ---
        if is_ebkn and isinstance(handler_output, tuple):
            body, status, headers = handler_output
            response = Response(body, status=status, headers=headers, content_type='application/octet-stream')
        elif isinstance(handler_output, Response):
            response = handler_output
        else:
            logger.error(f"Handler for {parsed_path} returned an invalid type: {type(handler_output)}")
            return Response("Internal Server Error: Invalid handler response", status=500)
        
        if response.status_code != 200 :
            logger.info(f"Request from {remote_ip} for path '{parsed_path}'")
            logger.info(f"Response for {parsed_path}: Status: {response.status_code}")
        return response

    except Exception as e:
        frappe.log_error(title=f"Error handling request for path {parsed_path}", message=frappe.get_traceback())
        return Response("Internal Server Error", status=500)
    finally:
        frappe.set_user(original_user or "Guest")
        frappe.db.commit()