import frappe
from frappe.utils import get_bench_path
from werkzeug.wrappers import Response
from urllib.parse import urlparse, unquote
import logging
import os
import json

# Import the device request handlers for each brand
from biometric_integration.services.ebkn_processor import handle_ebkn
from biometric_integration.services.zkteco_processor import handle_zkteco

# --- Logger Setup ---
LOG_FILE = os.path.join(get_bench_path(), "logs", "biometric_listener.log")
logger = logging.getLogger("biometric_listener_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
# --- End Logger Setup ---

# --- Header Transformation Map (for EBKN) ---
NGINX_TO_ORIGINAL_HEADERS = {
    "x-request-code": "request_code",
    "x-dev-id": "dev_id",
    # ... other headers
}

# --- Brand to Handler Router ---
# Maps URL paths to their corresponding handler function.
REQUEST_ROUTER = {
    "/ebkn": handle_ebkn,
    "/iclock/cdata": handle_zkteco,
    "/iclock/getrequest": handle_zkteco,
    "/iclock/devicecmd": handle_zkteco,
}

@frappe.whitelist(allow_guest=True)
def handle_request():
    """
    Single entry point for all biometric device requests. It routes requests
    to the appropriate brand processor based on the URL path.
    """
    original_user = frappe.session.user
    request = frappe.local.request
    
    # Use the raw URI from Nginx to get the path
    original_uri = request.headers.get('X-Original-Request-URI', '/')
    parsed_path = urlparse(original_uri).path

    # Concise logging for every request
    log_info = f"Request from {request.remote_addr} on path {parsed_path}"
    if request.args:
        log_info += f" with params: {dict(request.args)}"
    logger.info(log_info)

    try:
        frappe.set_user("Administrator")
        
        # Find the correct handler based on the path
        handler = REQUEST_ROUTER.get(parsed_path)
        if not handler:
            logger.warning(f"No handler found for path: {parsed_path}")
            return Response(f"No handler found for path: {parsed_path}", status=404)

        # Reconstruct headers for EBKN protocol if needed
        reconstructed_headers = dict(request.headers)
        if parsed_path.startswith('/ebkn'):
            for nginx_header, original_header in NGINX_TO_ORIGINAL_HEADERS.items():
                if nginx_header in request.headers:
                    reconstructed_headers[original_header] = request.headers[nginx_header]
        
        # Execute the handler
        raw_body = request.get_data(cache=False)
        return handler(request, raw_body, reconstructed_headers)

    except Exception as e:
        logger.error(f"Biometric API request failed on path {parsed_path}", exc_info=True)
        return Response("Internal Server Error", status=500)
    finally:
        frappe.set_user(original_user or "Guest")
