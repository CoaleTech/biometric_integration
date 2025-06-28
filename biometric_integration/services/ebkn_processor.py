from __future__ import annotations

import base64
import json
import os
import struct
import typing
from datetime import datetime
from io import BytesIO
from typing import Any, Callable, Dict, List, Tuple

import frappe
from frappe.utils import get_bench_path, now, now_datetime

# FIX: Changed the relative import to a robust absolute import.
# This resolves the "No module named 'biometric_integration.doctype'" error.
from biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings import get_erp_employee_id
from biometric_integration.services.command_processor import process_device_command
from biometric_integration.services.create_checkin import create_employee_checkin
from biometric_integration.services.device_mapping import get_biometric_assets_dir
from biometric_integration.services.logger import logger

# --- Constants & helpers ---
BENCH_ASSETS_DIR = get_biometric_assets_dir()
PARTIAL_DIR = os.path.join(BENCH_ASSETS_DIR, "partial_data")
BLOCK_MAP_PATH = os.path.join(BENCH_ASSETS_DIR, "block_sequence_map.json")
os.makedirs(PARTIAL_DIR, exist_ok=True)
REQ_RECV_CMD = "receive_cmd"
REQ_SEND_CMD_RESULT = "send_cmd_result"
REQ_REALTIME_GLOG = "realtime_glog"
REQ_REALTIME_ENROLL = "realtime_enroll_data"
Reply = Tuple[str | bytes, int, Dict[str, str]]

# --- Block‑sequence, partial-file, and JSON/Binary helpers (Unchanged) ---
def _load_block_map() -> Dict[str, int]:
    if os.path.exists(BLOCK_MAP_PATH):
        try:
            with open(BLOCK_MAP_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.error("Unable to read block map: %s", exc)
    return {}
def _save_block_map(map_obj: Dict[str, int]) -> None:
    try:
        with open(BLOCK_MAP_PATH, "w", encoding="utf-8") as fh:
            json.dump(map_obj, fh, indent=2)
    except Exception as exc:
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
def _extract_json_and_bins(raw: bytes) -> Tuple[dict, Dict[str, bytes]]:
    text = raw.decode("utf-8", errors="replace")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON opening brace found")
    brace, end = 0, -1
    for idx, ch in enumerate(text[start:], start=start):
        if ch == "{": brace += 1
        elif ch == "}":
            brace -= 1
            if brace == 0:
                end = idx
                break
    if end == -1: raise ValueError("unbalanced JSON braces")
    meta = json.loads(text[start : end + 1])
    remaining, placeholders = raw[end + 1 :], []
    def _recurse(obj: Any) -> None:
        if isinstance(obj, dict): [ _recurse(v) for v in obj.values() ]
        elif isinstance(obj, list): [ _recurse(v) for v in obj ]
        elif isinstance(obj, str) and obj.startswith("BIN_"): placeholders.append(obj)
    _recurse(meta)
    if not placeholders: return meta, {}
    segments, seg_size = {}, len(remaining) // len(placeholders)
    stream = BytesIO(remaining)
    for idx, ph in enumerate(placeholders, 1):
        blob = stream.read() if idx == len(placeholders) else stream.read(seg_size)
        segments[ph] = blob
    return meta, segments
def _json_with_inlined_bins(meta: dict, bin_map: Dict[str, bytes]) -> dict:
    def _replace(obj: Any) -> Any:
        if isinstance(obj, dict): return {k: _replace(v) for k, v in obj.items()}
        if isinstance(obj, list): return [_replace(v) for v in obj]
        if isinstance(obj, str) and obj in bin_map: return base64.b64encode(bin_map[obj]).decode()
        return obj
    return _replace(meta)

# --- Core entry point ---
def handle_request(raw_data: bytes, headers: Dict[str, str], *, brand: str = "ebkn",) -> Reply:
    """Process a POST from any EBKN device."""
    try:
        request_code = headers.get("request_code", "")
        dev_id = headers.get("dev_id", "")
        blk_raw = headers.get("blk_no")
        blk_no = int(blk_raw) if blk_raw is not None else 0

        if not request_code or not dev_id:
            logger.error("Request failed: Missing 'request_code' or 'dev_id' in reconstructed headers.")
            return _fail("Missing request_code or dev_id")

        last_blk = _get_last_block(dev_id, request_code)
        if blk_no == 1:
            _start_sequence(dev_id, request_code)
            _append_block(dev_id, request_code, raw_data)
            _set_last_block(dev_id, request_code, 1)
            return _ok_after_block()
        if blk_no > 1:
            if last_blk is None or blk_no != last_blk + 1:
                return _fail("Block sequence mismatch")
            _append_block(dev_id, request_code, raw_data)
            _set_last_block(dev_id, request_code, blk_no)
            return _ok_after_block()
        if last_blk is None: full_payload = raw_data
        else:
            _append_block(dev_id, request_code, raw_data)
            _set_last_block(dev_id, request_code, 0)
            full_payload = _read_sequence(dev_id, request_code)
            if full_payload is None: return _fail("Unable to read spooled data")
            _clear_sequence(dev_id, request_code)

        meta, bins = _extract_json_and_bins(full_payload)
        meta = _json_with_inlined_bins(meta, bins)
        meta["device_id"] = dev_id
        handler = REQUEST_ROUTER.get(request_code)
        if handler is None: return _fail("Unsupported request_code")
        return handler(meta, headers, full_payload)
    except Exception as exc:
        logger.error("EBKN processor fatal: %s", exc, exc_info=True)
        return _fail("Internal server error")

# --- Generic response helpers (Unchanged) ---
def reply_response_code(response_code: str = "OK", *, trans_id: str = "0", cmd_code: str = "", body: bytes | str = b"", **extra_headers: str,) -> Reply:
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    headers: Dict[str, str] = {"response_code": response_code, "trans_id": trans_id, **extra_headers}
    if cmd_code: headers["cmd_code"] = cmd_code
    return body_bytes, 200, headers
def _ok_after_block() -> Reply:
    return reply_response_code("OK")
def _fail(msg: str) -> Reply:
    return (json.dumps({"error": msg}), 400, {"response_code": "ERROR"})

# --- Request-specific handlers ---
def _handle_realtime_glog(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    try:
        user_id = int(payload["user_id"])
        ts = datetime.strptime(payload["io_time"], "%Y%m%d%H%M%S")
        log_type = "IN" if payload.get("io_mode") == 1 else "OUT"
        ok = create_employee_checkin(
            employee_field_value=user_id,
            timestamp=ts.strftime("%Y-%m-%d %H:%M:%S"),
            device_id=headers.get("dev_id"),
            log_type=log_type,
        )
        return _ok_after_block() if ok else _fail("check-in failed")
    except Exception as exc:
        logger.error("realtime_glog handler: %s", exc, exc_info=True)
        return _fail("realtime_glog error")

def create_bs_comm_buffer(payload: bytes) -> bytes:
    if not isinstance(payload, (bytes, bytearray)): raise TypeError("payload must be bytes")
    return struct.pack("<I", len(payload) + 1) + payload + b"\x00"
def _format_cmd_body(raw: typing.Union[str, bytes, None]) -> bytes:
    if raw is None: return b""
    if isinstance(raw, bytes): return raw
    if isinstance(raw, str): return create_bs_comm_buffer(raw.encode("utf-8"))
    raise TypeError("Unsupported body type for EBKN command.")

def _handle_receive_cmd(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    dev_id = headers.get("dev_id")
    trans_id = headers.get("trans_id", "0")
    try:
        cmd = process_device_command(dev_id)
        if not cmd: return reply_response_code("OK", trans_id=trans_id)
        body_bytes = _format_cmd_body(cmd.get("body"))
        trans_id = cmd.get("trans_id") or trans_id
        cmd_code = cmd.get("cmd_code", "")
        return reply_response_code("OK", trans_id=trans_id, cmd_code=cmd_code, body=body_bytes)
    except Exception as exc:
        logger.error("receive_cmd failed for %s: %s", dev_id, exc, exc_info=True)
        return reply_response_code("ERROR")

def _handle_send_cmd_result(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    dev_id = headers.get("dev_id")
    trans_id = headers.get("trans_id") or "0"
    cmd_return_code = (headers.get("cmd_return_code") or "").upper()
    blk_no_raw = headers.get("blk_no")
    try:
        try:
            cmd_doc = frappe.get_doc("Biometric Device Command", trans_id)
        except frappe.DoesNotExistError:
            logger.error(f"send_cmd_result for device {dev_id}: command doc '{trans_id}' not found")
            return reply_response_code("OK", trans_id=trans_id)
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        line = f"[{now()}] {cmd_return_code}"
        cmd_doc.device_response = (f"{cmd_doc.device_response}\n{line}" if cmd_doc.device_response else line)
        if cmd_return_code == "OK":
            if blk_no_raw is not None: cmd_doc.last_sent_data_block = int(blk_no_raw)
            else:
                cmd_doc.status, cmd_doc.closed_on = "Success", now_datetime()
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        if (cmd_doc.command_type == "Get Enroll Data" and cmd_return_code == "OK" and (blk_no_raw is None or blk_no_raw == "0")):
            _store_get_user_info_blob(dev_id=dev_id, user_id=payload.get("user_id", ""), blob=raw)
    except Exception as exc:
        frappe.db.rollback()
        logger.error("Failed updating command %s: %s", trans_id, exc, exc_info=True)
    return reply_response_code("OK", trans_id=trans_id)

def _queue_get_user_info(dev_id: str, user_id: str) -> None:
    if frappe.db.exists("Biometric Device Command", {"biometric_device": dev_id, "biometric_device_user": user_id, "brand": "EBKN", "command_type": "Get Enroll Data", "status": "Pending"}):
        return
    cmd = frappe.get_doc({"doctype": "Biometric Device Command", "biometric_device": dev_id, "biometric_device_user": user_id, "brand": "EBKN", "command_type": "Get Enroll Data"})
    cmd.insert(ignore_permissions=True)
    frappe.db.commit()

def _handle_realtime_enroll_data(payload: dict, headers: Dict[str, str], raw: bytes) -> Reply:
    dev_id = headers.get("dev_id")
    user_id_raw = payload.get("user_id")
    if not user_id_raw: return _fail("user_id missing")
    user_id = user_id_raw.lstrip("0") or user_id_raw
    try:
        docname = frappe.db.exists("Biometric Device User", {"user_id": user_id})
        user_doc = (frappe.get_doc("Biometric Device User", docname) if docname else frappe.get_doc({"doctype": "Biometric Device User", "user_id": user_id}))
        if not docname:
            try:
                if emp := get_erp_employee_id(user_id): user_doc.employee = emp
            except Exception: pass
            user_doc.insert(ignore_permissions=True)
        if not any(d.biometric_device == dev_id for d in user_doc.devices):
            user_doc.append("devices", {"biometric_device": dev_id, "brand": "EBKN", "enroll_data_source": 0})
            user_doc.save(ignore_permissions=True)
        frappe.db.commit()
        _queue_get_user_info(dev_id, user_doc.name)
        return _ok_after_block()
    except Exception as exc:
        frappe.db.rollback()
        logger.error("realtime_enroll_data: %s", exc, exc_info=True)
        return _fail("realtime_enroll error")

def _store_get_user_info_blob(dev_id: str, user_id: str, blob: bytes):
    try:
        user_id_nz = user_id.lstrip("0") or user_id
        user_doc = frappe.get_doc("Biometric Device User", frappe.db.get_value("Biometric Device User", {"user_id": user_id_nz}))
        file_doc = frappe.get_doc({"doctype": "File", "file_name": f"enroll_data_{user_id_nz}.bin", "is_private": 1, "content": blob, "attached_to_doctype": "Biometric Device User", "attached_to_name": user_doc.name})
        file_doc.insert(ignore_permissions=True)
        user_doc.ebkn_enroll_data = file_doc.file_url
        for row in user_doc.devices:
            if row.brand == "EBKN": row.enroll_data_source = 1 if row.biometric_device == dev_id else 0
        user_doc.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as exc:
        frappe.db.rollback()
        logger.error("Failed storing user info blob for %s: %s", user_id, exc, exc_info=True)

# --- Router and Public API ---
REQUEST_ROUTER: Dict[str, Callable[[dict, Dict[str, str], bytes], Reply]] = {
    REQ_REALTIME_GLOG: _handle_realtime_glog,
    REQ_REALTIME_ENROLL: _handle_realtime_enroll_data,
    REQ_RECV_CMD: _handle_receive_cmd,
    REQ_SEND_CMD_RESULT: _handle_send_cmd_result,
}
def handle_ebkn(_: Any, raw: bytes, headers: Dict[str, str]) -> Reply:
    """Adapter compatible with api.py expectation."""
    return handle_request(raw, headers, brand="ebkn")
