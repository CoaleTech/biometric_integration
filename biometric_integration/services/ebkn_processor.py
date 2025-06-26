from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime
from frappe.utils import now, now_datetime
from io import BytesIO
from typing import Any, Callable, Dict, List, Tuple

import frappe  # type: ignore

from biometric_integration.services.create_checkin import create_employee_checkin
from biometric_integration.utils.site_session import init_site, destroy_site
from biometric_integration.services.device_mapping import get_biometric_assets_dir, get_site_for_device
from biometric_integration.services.command_processor import process_device_command
from biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings import get_erp_employee_id
# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

logger = logging.getLogger("biometric_listener")

#: Directory that persists *all* brand‑agnostic assets (raw blocks, spooled data…)
BENCH_ASSETS_DIR = get_biometric_assets_dir()
PARTIAL_DIR = os.path.join(BENCH_ASSETS_DIR, "partial_data")
BLOCK_MAP_PATH = os.path.join(BENCH_ASSETS_DIR, "block_sequence_map.json")

os.makedirs(PARTIAL_DIR, exist_ok=True)

REQ_RECV_CMD = "receive_cmd"
REQ_SEND_CMD_RESULT = "send_cmd_result"
REQ_REALTIME_GLOG = "realtime_glog"
REQ_REALTIME_ENROLL = "realtime_enroll_data"

# ---------------------------------------------------------------------------
# Block‑sequence bookkeeping (device_id + request_code ➜ last blk_no)
# ---------------------------------------------------------------------------

def _load_block_map() -> Dict[str, int]:
    if os.path.exists(BLOCK_MAP_PATH):
        try:
            with open(BLOCK_MAP_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # pragma: no cover
            logger.error("Unable to read block map: %s", exc)
    return {}


def _save_block_map(map_obj: Dict[str, int]) -> None:
    try:
        with open(BLOCK_MAP_PATH, "w", encoding="utf-8") as fh:
            json.dump(map_obj, fh, indent=2)
    except Exception as exc:  # pragma: no cover
        logger.error("Unable to persist block map: %s", exc)


def _seq_key(dev_id: str, request_code: str) -> str:
    return f"{dev_id}_{request_code}"


def _set_last_block(dev_id: str, request_code: str, blk_no: int) -> None:
    m = _load_block_map()
    m[_seq_key(dev_id, request_code)] = blk_no
    _save_block_map(m)


def _get_last_block(dev_id: str, request_code: str) -> int | None:
    return _load_block_map().get(_seq_key(dev_id, request_code))


def _clear_sequence(dev_id: str, request_code: str) -> None:
    m = _load_block_map()
    m.pop(_seq_key(dev_id, request_code), None)
    _save_block_map(m)

# ---------------------------------------------------------------------------
# Partial‑file storage helpers
# ---------------------------------------------------------------------------

def _partial_path(dev_id: str, request_code: str) -> str:
    return os.path.join(PARTIAL_DIR, f"{dev_id}_{request_code}.bin")


def _start_sequence(dev_id: str, request_code: str) -> None:
    try:
        os.remove(_partial_path(dev_id, request_code))
    except FileNotFoundError:
        pass
    _clear_sequence(dev_id, request_code)


def _append_block(dev_id: str, request_code: str, data: bytes) -> None:
    with open(_partial_path(dev_id, request_code), "ab") as fh:
        fh.write(data)


def _read_sequence(dev_id: str, request_code: str) -> bytes | None:
    path = _partial_path(dev_id, request_code)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()
    return None

# ---------------------------------------------------------------------------
# Binary‑aware JSON extraction
# ---------------------------------------------------------------------------

def _extract_json_and_bins(raw: bytes) -> Tuple[dict, Dict[str, bytes]]:
    """Return (json_dict, placeholder→binary mapping).

    The protocol always places the UTF‑8 JSON string first, followed by zero or
    more binary blobs.  Each blob is referenced by a *unique* placeholder such
    as ``"BIN_1"`` in the JSON.  The order of placeholders equals the order of
    blobs on the wire.
    """
    text = raw.decode("utf-8", errors="replace")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON opening brace found")

    brace = 0
    end = -1
    for idx, ch in enumerate(text[start:], start=start):
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
            if brace == 0:
                end = idx
                break
    if end == -1:
        raise ValueError("unbalanced JSON braces")

    json_blob = text[start : end + 1]
    meta = json.loads(json_blob)
    remaining = raw[end + 1 :]

    # Collect placeholders in discovery order (depth‑first)
    placeholders: List[str] = []

    def _recurse(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                _recurse(v)
        elif isinstance(obj, list):
            for v in obj:
                _recurse(v)
        elif isinstance(obj, str) and obj.startswith("BIN_"):
            placeholders.append(obj)

    _recurse(meta)

    if not placeholders:
        return meta, {}

    # Split remaining bytes evenly; last segment gets the rest (device spec).
    segments: Dict[str, bytes] = {}
    if placeholders:
        seg_size = len(remaining) // len(placeholders)
        stream = BytesIO(remaining)
        for idx, ph in enumerate(placeholders, 1):
            if idx == len(placeholders):
                blob = stream.read()
            else:
                blob = stream.read(seg_size)
            segments[ph] = blob

    return meta, segments


def _json_with_inlined_bins(meta: dict, bin_map: Dict[str, bytes]) -> dict:
    def _replace(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _replace(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_replace(v) for v in obj]
        if isinstance(obj, str) and obj in bin_map:
            return base64.b64encode(bin_map[obj]).decode()
        return obj

    return _replace(meta)

# ---------------------------------------------------------------------------
# Core entry point
# ---------------------------------------------------------------------------

Reply = Tuple[str | bytes, int, Dict[str, str]]


def handle_request(
    raw_data: bytes,
    headers: Dict[str, str],
    *,
    brand: str = "ebkn",
) -> Reply:
    """Process a POST from *any* EBKN device.

    The caller (listener) is responsible for:
    1.  making sure ``frappe`` is already initialised for the proper site;
    2.  passing *raw* body bytes and canonicalised header dict.
    """
    try:
        request_code = headers.get("request_code", "")
        dev_id = headers.get("dev_id", "")
        blk_raw = headers.get("blk_no")
        blk_no = int(blk_raw) if blk_raw is not None else 0

        if not request_code or not dev_id:
            return _fail("Missing request_code or dev_id")

        # -------------------- block assembly --------------------
        last_blk = _get_last_block(dev_id, request_code)

        if blk_no == 1:  # first
            _start_sequence(dev_id, request_code)
            _append_block(dev_id, request_code, raw_data)
            logger.debug(
                "EBKN %s blk=%s len=%d  (last=%s, path=%s)",
                request_code, blk_no, len(raw_data),
                _get_last_block(dev_id, request_code),
                _partial_path(dev_id, request_code),
            )
            _set_last_block(dev_id, request_code, 1)
            return _ok_after_block()

        if blk_no > 1:  # middle
            if last_blk is None or blk_no != last_blk + 1:
                return _fail("Block sequence mismatch")
            _append_block(dev_id, request_code, raw_data)
            logger.debug(
                "EBKN %s blk=%s len=%d  (last=%s, path=%s)",
                request_code, blk_no, len(raw_data),
                _get_last_block(dev_id, request_code),
                _partial_path(dev_id, request_code),
            )
            _set_last_block(dev_id, request_code, blk_no)
            return _ok_after_block()

        # blk_no == 0  → final *or* single‑shot
        if last_blk is None:  # single
            full_payload = raw_data
        else:
            _append_block(dev_id, request_code, raw_data)
            logger.debug(
                "EBKN %s blk=%s len=%d  (last=%s, path=%s)",
                request_code, blk_no, len(raw_data),
                _get_last_block(dev_id, request_code),
                _partial_path(dev_id, request_code),
            )
            _set_last_block(dev_id, request_code, 0)
            full_payload = _read_sequence(dev_id, request_code)
            if full_payload is None:
                return _fail("Unable to read spooled data")
            _clear_sequence(dev_id, request_code)

        # -------------------- decode JSON/BIN --------------------
        meta, bins = _extract_json_and_bins(full_payload)
        meta = _json_with_inlined_bins(meta, bins)
        meta["device_id"] = dev_id  # convenience

        # -------------------- route to handler -------------------
        handler = REQUEST_ROUTER.get(request_code)
        if handler is None:
            return _fail("Unsupported request_code")
        return handler(meta, headers, full_payload)

    except Exception as exc:
        logger.error("EBKN processor fatal: %s", exc, exc_info=True)
        return _fail("Internal server error")

# ---------------------------------------------------------------------------
# Generic helpers to craft octet‑stream responses
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Generic helpers to craft octet-stream responses
# ---------------------------------------------------------------------------

def reply_response_code(
    response_code: str = "OK",
    *,
    trans_id: str = "0",
    cmd_code: str = "",
    body: bytes | str = b"",
    **extra_headers: str,
) -> Reply:
    """
    Build a `(body, http_status, headers)` tuple the listener expects.

    • `body` may be `str` or `bytes` (string will be UTF-8 encoded).  
    • Adds `response_code`, `trans_id`, and optional `cmd_code` / `blk_no` headers.  
    • Always returns HTTP 200 unless caller overrides.
    """
    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body

    headers: Dict[str, str] = {
        "response_code": response_code,
        "trans_id": trans_id,
        **extra_headers,
    }
    if cmd_code:
        headers["cmd_code"] = cmd_code

    return body_bytes, 200, headers


def _ok_after_block() -> Reply:
    return reply_response_code("OK")


def _fail(msg: str) -> Reply:
    return (
        json.dumps({"error": msg}),
        400,
        {"response_code": "ERROR"},
    )

# ---------------------------------------------------------------------------
# Request-specific handlers
# ---------------------------------------------------------------------------


def _handle_realtime_glog(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    """Create a Check-in from the device’s real-time log packet."""
    try:
        user_id = int(payload["user_id"])
        ts      = datetime.strptime(payload["io_time"], "%Y%m%d%H%M%S")
        log_type = "IN" if payload.get("io_mode") == 1 else "OUT"

        ok = create_employee_checkin(
            employee_field_value=user_id,
            timestamp=ts.strftime("%Y-%m-%d %H:%M:%S"),
            device_id=headers["dev_id"],
            log_type=log_type,
        )
        return _ok_after_block() if ok else _fail("check-in failed")
    except Exception as exc:
        logger.error("realtime_glog handler: %s", exc, exc_info=True)
        return _fail("realtime_glog error")


# ---------------------------------------------------------------------------
# Helpers for command download / upload
# ---------------------------------------------------------------------------

import struct

def create_bs_comm_buffer(payload: bytes) -> bytes:
    """
    Return payload framed for EBKN BS-Comm:

        [4-byte little-endian length incl. NULL]  payload  0x00
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")

    # +1 for the trailing NULL that the firmware expects
    total_len = len(payload) + 1
    header    = struct.pack("<I", total_len)      # uint32 LE
    return header + payload + b"\x00"

def _format_cmd_body(raw: typing.Union[str, bytes, None]) -> bytes:
    """
    EBKN devices expect every payload wrapped in a 4-byte little-endian length
    (including NULL terminator) + the bytes + 0x00.  Strings are encoded and
    wrapped; bytes are assumed pre-wrapped.
    """
    if raw is None:
        return b""
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return create_bs_comm_buffer(raw.encode("utf-8"))
    raise TypeError("Unsupported body type for EBKN command.")


def _handle_receive_cmd(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    """
    Device polls: “Got any command for me?”
    • Fast exit if JSON cache says there’s nothing.
    • Otherwise boot site, build command, wrap body, reply.
    """
    dev_id   = headers["dev_id"]
    trans_id = headers.get("trans_id", "0")

    try:
        info = get_site_for_device(dev_id) or {}
        if not info.get("has_pending_command"):
            return reply_response_code("OK", trans_id=trans_id)  # empty ACK

        init_site(dev_id)
        try:
            cmd = process_device_command(dev_id)  # may be None
        finally:
            destroy_site()

        if not cmd:
            return reply_response_code("OK", trans_id=trans_id)

        body_bytes = _format_cmd_body(cmd.get("body"))
        trans_id   = cmd.get("trans_id") or trans_id
        cmd_code   = cmd.get("cmd_code", "")

        extra = {"blk_no": str(cmd["blk_no"])} if cmd.get("blk_no") else {}
        logger.info( f"Sending command {cmd_code} to {dev_id} with raw body {body_bytes}")
        return reply_response_code(
            "OK", trans_id=trans_id, cmd_code=cmd_code, body=body_bytes, **extra
        )

    except Exception as exc:
        logger.error("receive_cmd failed for %s: %s", dev_id, exc, exc_info=True)
        return reply_response_code("ERROR")


# ---------------------------------------------------------------------------
#  Device → server :  send_cmd_result  (final version)
# ---------------------------------------------------------------------------

def _handle_send_cmd_result(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    dev_id          = headers.get("dev_id")
    trans_id        = headers.get("trans_id") or "0"
    cmd_return_code = (headers.get("cmd_return_code") or "").upper()
    blk_no_raw      = headers.get("blk_no")  # may be None / str

    logger.info(
                "CMD-result received\n"
                "  • dev_id   : %s\n"
                "  • headers  : %s\n"
                "  • payload  : %s\n",
                headers.get("dev_id", "<unknown>"),
                json.dumps(headers, indent=2),
                json.dumps(payload, indent=2)
            )

    # 1️⃣  Fetch the document (or gracefully ignore if missing)
    try:
        init_site(dev_id)
        try:
            cmd_doc = frappe.get_doc("Biometric Device Command", trans_id)
        except frappe.DoesNotExistError:
            frappe.log_error(
                title="Biometric Command Missing",
                message=(
                    f"send_cmd_result for device {dev_id}: "
                    f"command doc '{trans_id}' not found "
                    f"(return_code={cmd_return_code})"
                ),
            )
            return reply_response_code("OK", trans_id=trans_id)
    finally:
        destroy_site()

    # 2️⃣  Update the document
    try:
        init_site(dev_id)

        # bump attempts
        if blk_no_raw is None or (blk_no_raw is not None and cmd_return_code != "OK") or (blk_no_raw == 0 and cmd_return_code == "OK"): 
            cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
            
        # append response log
        line = f"[{now()}] {cmd_return_code}"
        cmd_doc.device_response = (
            f"{cmd_doc.device_response}\n{line}"
            if cmd_doc.device_response else line
        )

        if cmd_return_code == "OK":
            if blk_no_raw is not None:
                # chunked transfer scenario: just note last block
                cmd_doc.last_sent_data_block = int(blk_no_raw)
            else:
                # single-shot command finished: close it
                cmd_doc.status     = "Success"
                cmd_doc.closed_on  = now_datetime()

        cmd_doc.save()
        frappe.db.commit()

        # 2·A – if this was a GET_USER_INFO result keep the raw chunk
        if (cmd_doc.command_type == "Get Enroll Data"
            and cmd_return_code == "OK"
            and (blk_no_raw is None or blk_no_raw == "0")):
            _store_get_user_info_blob(
                dev_id  = dev_id,
                user_id = payload.get("user_id", ""),
                blob    = raw,
            )

    except Exception as exc:
        frappe.db.rollback()
        logger.error("Failed updating command %s: %s", trans_id, exc, exc_info=True)

    finally:
        destroy_site()

    # 3️⃣  Always acknowledge device
    return reply_response_code("OK", trans_id=trans_id)

# ──────────────────────────────────────────────────────────────────────
#  Helpers for *Biometric Device Command* creation
# ──────────────────────────────────────────────────────────────────────
def _queue_get_user_info(dev_id: str, user_id: str) -> None:
    """Insert a 'Get Enroll Data' command if one is not already queued."""
    init_site(dev_id)
    try:
        exists = frappe.db.exists(
            "Biometric Device Command",
            {
                "biometric_device":      dev_id,
                "biometric_device_user": user_id,
                "brand":                 "EBKN",
                "command_type":          "Get Enroll Data",
                "status":                "Pending",
            },
        )
        if exists:
            return  # already waiting – do not duplicate

        cmd = frappe.get_doc({
            "doctype":                "Biometric Device Command",
            "biometric_device":       dev_id,
            "biometric_device_user":  user_id,
            "brand":                  "EBKN",
            "command_type":           "Get Enroll Data"
        })
        cmd.insert(ignore_permissions=True)
        frappe.db.commit()

    finally:
        destroy_site()


# ──────────────────────────────────────────────────────────────────────
#  Device → server : realtime_enroll_data
# ──────────────────────────────────────────────────────────────────────
def _handle_realtime_enroll_data(
    payload: dict,
    headers: Dict[str, str],
    raw: bytes,        # full JSON+BIN payload – not used any more
) -> Reply:

    dev_id      = headers["dev_id"]
    user_id_raw = payload.get("user_id")
    if not user_id_raw:
        return _fail("user_id missing")

    user_id = user_id_raw.lstrip("0") or user_id_raw

    try:
        init_site(dev_id)

        # 1️⃣  upsert Biometric Device User (but do NOT touch the blob)
        docname = frappe.db.exists("Biometric Device User", {"user_id": user_id})
        user_doc = (
            frappe.get_doc("Biometric Device User", docname)
            if docname else
            frappe.get_doc({"doctype": "Biometric Device User", "user_id": user_id})
        )

        if not docname:
            # optional auto-link to Employee
            try:
                emp = get_erp_employee_id(user_id)
                if emp:
                    user_doc.employee = emp
            except Exception:
                pass
            user_doc.insert(ignore_permissions=True)

        # 2️⃣  ensure the current device row exists
        if not any(d.biometric_device == dev_id for d in user_doc.devices):
            user_doc.append("devices", {
                "biometric_device": dev_id,
                "brand":            "EBKN",
                "enroll_data_source": 0,
            })
            user_doc.save(ignore_permissions=True)

        frappe.db.commit()

        # 3️⃣  schedule GET_USER_INFO so we receive the full blob soon
        _queue_get_user_info(dev_id, user_doc.name)

        return _ok_after_block()

    except Exception as exc:
        frappe.db.rollback()
        logger.error("realtime_enroll_data: %s", exc, exc_info=True)
        return _fail("realtime_enroll error")

    finally:
        destroy_site()


# ──────────────────────────────────────────────────────────────────────
#  Helper used by send_cmd_result (stage 2)
# ──────────────────────────────────────────────────────────────────────
def _store_get_user_info_blob(dev_id: str, user_id: str, blob: bytes):
    """Create a fresh File and update enrol-source flags atomically."""
    init_site(dev_id)
    try:
        user_id_nz = user_id.lstrip("0") or user_id
        user_doc   = frappe.get_doc(
            "Biometric Device User",
            frappe.db.get_value("Biometric Device User", {"user_id": user_id_nz}),
        )

        # --- create brand-new private File ---
        file_doc = frappe.get_doc({
            "doctype":             "File",
            "file_name":           f"enroll_data_{user_id_nz}.bin",
            "is_private":          1,
            "content":             blob,
            "attached_to_doctype": "Biometric Device User",
            "attached_to_name":    user_doc.name,
        })
        file_doc.insert(ignore_permissions=True)

        user_doc.ebkn_enroll_data = file_doc.file_url

        # --- enrol_data_source bookkeeping ---
        for row in user_doc.devices:
            if row.brand == "EBKN":
                row.enroll_data_source = 1 if row.biometric_device == dev_id else 0

        user_doc.save(ignore_permissions=True)
        frappe.db.commit()

    finally:
        destroy_site()


# ---------------------------------------------------------------------------
# Placeholder for handlers we haven’t implemented yet
# ---------------------------------------------------------------------------

def _placeholder(name: str) -> Callable[[dict, Dict[str, str]], Reply]:
    def inner(payload: dict, headers: Dict[str, str]) -> Reply:
        logger.warning("%s handler not yet implemented", name)
        return _ok_after_block()
    return inner


# ---------------------------------------------------------------------------
# Router: map request-code ➜ handler
# ---------------------------------------------------------------------------

REQUEST_ROUTER: Dict[str, Callable[[dict, Dict[str, str], bytes], Reply]] = {
    REQ_REALTIME_GLOG:   _handle_realtime_glog,
    REQ_REALTIME_ENROLL: _handle_realtime_enroll_data,
    REQ_RECV_CMD:        _handle_receive_cmd,
    REQ_SEND_CMD_RESULT: _handle_send_cmd_result,
}

# ---------------------------------------------------------------------------
# Public API convenience for the listener
# ---------------------------------------------------------------------------


def handle_ebkn(_: Any, raw: bytes, headers: Dict[str, str]) -> Reply:  # noqa: D401
    """Adapter compatible with *listener.py* expectation."""
    return handle_request(raw, headers, brand="ebkn")
