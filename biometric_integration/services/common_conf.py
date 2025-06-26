from __future__ import annotations
import contextlib, json, os, socket, urllib.request, frappe
from frappe.installer import update_site_config 

CONF_KEY     = "biometric_listener_port"
DEFAULT_PORT = 8998

BENCH_PATH   = frappe.utils.get_bench_path()
COMMON_CONF  = os.path.join(BENCH_PATH, "sites", "common_site_config.json")

# ------------------------------------------------------------------ port ---
def get_port() -> int:
    """Return port from common_site_config or default."""
    return int(frappe.get_conf().get(CONF_KEY, DEFAULT_PORT))

def set_port(port: int) -> None:
    """Persist port in common_site_config.json (no validation)."""
    update_site_config(CONF_KEY, int(port), validate=False,
                       site_config_path=COMMON_CONF)

# ----------------------------------------------------------- tcp-probe -----
def port_open(port: int) -> bool:
    """Quick TCP probe on 127.0.0.1:*port*."""
    with contextlib.closing(socket.socket()) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

# ----------------------------------------------------------- public ip -----
def public_ip() -> str:
    """Best-effort external IPv4 (falls back to local LAN IP)."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=3) as r:
            return r.read().decode()
    except Exception:
        # fallback: first non-loopback local IP
        for fam, _, _, _, addr in socket.getaddrinfo(socket.gethostname(), None):
            if fam == socket.AF_INET and not addr[0].startswith("127."):
                return addr[0]
    return "127.0.0.1"
