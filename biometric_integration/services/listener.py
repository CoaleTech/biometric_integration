# biometric_integration/services/listener.py

import logging
import time
from typing import Callable, Dict
from urllib.parse import urlsplit

from werkzeug.wrappers import Request, Response

# Your application's request processor
from biometric_integration.services.ebkn_processor import handle_ebkn

logger = logging.getLogger("biometric_listener")

# Route table to direct requests to the correct handler.
_ROUTE_TABLE: Dict[str, Callable] = {
    "/ebkn": handle_ebkn,
}

# --- Header Processing Logic (Restored from your original file) ---
# This is the crucial part that was missing.

def _get_header(headers: "Request.headers", key: str) -> str | None:
    """Helper to tolerate different header casings (e.g., Dev-Id vs dev_id)."""
    return headers.get(key) or headers.get(key.replace("_", "-"))

_CANON_KEYS = {
    "request_code", "dev_id", "trans_id", "cmd_return_code",
    "blk_no", "response_code", "cmd_code",
}

def _canonicalize_headers(headers: "Request.headers") -> Dict[str, str]:
    """Creates a simple, clean dictionary of the headers we care about."""
    out: Dict[str, str] = {}
    for key in _CANON_KEYS:
        value = _get_header(headers, key)
        if value is not None:
            out[key] = value
    return out

# --- Main Application (Context-Free) ---
# This application runs without any Frappe context. Context is created on-demand
# by the handler (e.g., handle_ebkn) when it calls init_site().
@Request.application
def application(request: Request) -> Response:
    t0 = time.perf_counter()
    path = request.path.rstrip("/")
    if "://" in path:
        path = urlsplit(path).path.rstrip("/")

    # Basic request validation
    if request.method != "POST":
        return Response("Invalid Method", status=405)

    handler = _ROUTE_TABLE.get(path)
    if not handler:
        return Response("Not Found", status=404)

    # Process the request
    try:
        # THE FIX: We now prepare canonical headers and pass them as the third argument.
        raw_body = request.get_data(cache=False)
        canon_hdrs = _canonicalize_headers(request.headers)
        
        body_out, status, extra_headers = handler(request, raw_body, canon_hdrs)

    except Exception:
        logger.exception("Biometric processor raised an unhandled exception")
        return Response("Internal Server Error", status=500)

    # Build and return the response
    body_bytes = body_out if isinstance(body_out, (bytes, bytearray)) else str(body_out).encode()
    response = Response(body_bytes, status=status)
    response.headers["Content-Type"] = "application/octet-stream"
    response.headers["Content-Length"] = str(len(body_bytes))
    for k, v in extra_headers.items():
        response.headers[k] = v

    logger.info(
        "%s %s %s %d %.1fms",
        request.remote_addr, request.method, path, status, (time.perf_counter() - t0) * 1000
    )
    return response
