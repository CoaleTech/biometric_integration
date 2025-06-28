# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

import frappe
from werkzeug.wrappers import Response
from urllib.parse import urlparse

# Use full paths for robust imports as required by the Frappe framework.
from biometric_integration.services.ebkn_processor import handle_ebkn
from biometric_integration.services.zkteco_processor import handle_zkteco
from biometric_integration.services.logger import logger # Import the centralized logger

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

    logger.info(f"Request from {request.headers.get('X-Forwarded-For', request.remote_addr)} Path: '{parsed_path}' Headers: {dict(request.headers)}")

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

        reconstructed_headers = dict(request.headers)
        if is_ebkn:
            for nginx_header, original_header in NGINX_TO_ORIGINAL_HEADERS.items():
                if nginx_header in request.headers:
                    reconstructed_headers[original_header] = request.headers[nginx_header]

        raw_body = request.get_data(cache=False)
        
        # Execute the handler
        handler_output = handler(request, raw_body, reconstructed_headers)

        # --- RESPONSE ADAPTER ---
        # This block correctly handles the different return types from each processor.
        if is_ebkn and isinstance(handler_output, tuple):
            # The EBKN handler returns a tuple (body, status, headers).
            # We must construct a proper Response object from it.
            body, status, headers = handler_output
            response = Response(body, status=status, headers=headers, content_type='application/octet-stream')
        elif isinstance(handler_output, Response):
            # The ZKTeco handler already returns a complete Response object.
            response = handler_output
        else:
            # Fallback for unexpected return types.
            logger.error(f"Handler for {parsed_path} returned an invalid type: {type(handler_output)}")
            return Response("Internal Server Error: Invalid handler response", status=500)

        logger.info(f"Response for {parsed_path}: Status: {response.status_code} Headers: {dict(response.headers)}")
        return response

    except Exception as e:
        logger.error(f"Error handling request for path {parsed_path}", exc_info=True)
        return Response("Internal Server Error", status=500)
    finally:
        frappe.set_user(original_user or "Guest")
        frappe.db.commit()

