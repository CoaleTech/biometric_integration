from __future__ import annotations
import os, re, random, subprocess, socket, logging, frappe
from frappe.model.document import Document
from frappe.utils import cint, get_url
import requests

BENCH_PATH   = frappe.utils.get_bench_path()
PROCFILE     = os.path.join(BENCH_PATH, "Procfile")
PROC_NAME    = "biometric_listener"

# --------------------------------------------------------------------------- #
#  low-level helpers                                                          #
# --------------------------------------------------------------------------- #

def _write_procfile(port: int, enable: bool) -> None:
    """Add / remove the Procfile line and regenerate supervisor config."""
    lines: list[str] = []
    if os.path.exists(PROCFILE):
        with open(PROCFILE, "r") as fh:
            lines = fh.read().splitlines()
    lines = [ln for ln in lines if not ln.startswith(f"{PROC_NAME}:")]

    if enable:
        cmd = f"bench biometric-listener -p {port}"
        lines.append(f"{PROC_NAME}: {cmd}")

    with open(PROCFILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    subprocess.check_call(["bench", "setup", "procfile"], cwd=BENCH_PATH)

def _supervisor(action: str) -> None:
    try:
        subprocess.check_call(
            ["supervisorctl", "-c", "supervisord.conf",
             action, f"program:{PROC_NAME}"],
            cwd=BENCH_PATH,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

def _tcp_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

def get_device_employee_id(employee_id):
    """
    Convert an ERP Employee ID to a Device Employee ID based on the mapping method.

    Args:
        employee_id (str): The ERP Employee ID.

    Returns:
        str: The Device Employee ID.
    """
    if not employee_id:
        frappe.throw("Employee ID is required.")

    settings = frappe.get_cached_doc("Biometric Integration Settings")

    if settings.employee_id_mapping_method == "Use Device ID Field":
        device_employee_id = frappe.get_value("Employee", {"name": employee_id}, settings.device_id_field)
        if not device_employee_id:
            frappe.throw(f"Device Employee ID not found for Employee {employee_id} in field '{settings.device_id_field}'.")
        return device_employee_id

    elif settings.employee_id_mapping_method == "Clean Employee ID with Regex":
        if not settings.clean_id_regex:
            frappe.throw("Clean ID Regex is not configured.")
        cleaned_id = re.sub(settings.clean_id_regex, "", employee_id)
        if not cleaned_id:
            frappe.throw(f"Failed to clean Employee ID '{employee_id}' using regex '{settings.clean_id_regex}'.")
        return cleaned_id

    frappe.throw(f"Unsupported mapping method: {settings.employee_id_mapping_method}")

def get_erp_employee_id(device_employee_id):
    """
    Convert a Device Employee ID to an ERP Employee ID based on the mapping method.

    Args:
        device_employee_id (str): The Device Employee ID.

    Returns:
        str: The ERP Employee ID.
    """
    if not device_employee_id:
        frappe.throw("Device Employee ID is required.")

    settings = frappe.get_cached_doc("Biometric Integration Settings")

    if settings.employee_id_mapping_method == "Use Device ID Field":
        erp_employee_id = frappe.get_value("Employee", {settings.device_id_field: device_employee_id}, "name")
        if not erp_employee_id:
            frappe.throw(f"ERP Employee ID not found for Device Employee ID '{device_employee_id}' in field '{settings.device_id_field}'.")
        return erp_employee_id

    elif settings.employee_id_mapping_method == "Clean Employee ID with Regex":
        erp_employee_id = frappe.get_value("Employee", {"name": device_employee_id}, "name")
        if not erp_employee_id:
            frappe.throw(f"ERP Employee ID not found for cleaned ID '{device_employee_id}'.")
        return erp_employee_id

    frappe.throw(f"Unsupported mapping method: {settings.employee_id_mapping_method}")


# --------------------------------------------------------------------------- #
#  controller                                                                 #
# --------------------------------------------------------------------------- #

class BiometricIntegrationSettings(Document):
    # ------------- validation ------------------------------------------------
    def validate(self):
        if (self.employee_id_mapping_method == "Use Device ID Field"
                and not self.device_id_field):
            frappe.throw("Device ID Field is required when mapping "
                         "method is ‘Use Device ID Field’.")
        if (self.employee_id_mapping_method == "Clean Employee ID with Regex"
                and not self.clean_id_regex):
            frappe.throw("Clean-ID regex is required for that mapping mode.")

        if self.clean_id_regex:
            try:
                re.compile(self.clean_id_regex)
            except re.error:
                frappe.throw("Invalid regex pattern for Clean-ID.")

        if not 1024 < cint(self.listener_port or 0) < 65535:
            frappe.throw("Listener port must be in the 1025-65534 range.")

        # example cleaned IDs (pure UI sugar)
        employees = frappe.get_all("Employee", pluck="name", limit=30)
        sample    = random.sample(employees, min(5, len(employees)))
        self.example_cleaned_ids = "\n".join(
            f"{i} → {re.sub(self.clean_id_regex or '', '', i)}"
            for i in sample
        )

    # ------------- after-commit  --------------------------------------------
    def before_save(self):
        """Hook runs *after* DB commit — safe for slow shell work."""
        frappe.enqueue(
            "biometric_integration.biometric_integration."
            "doctype.biometric_integration_settings.listener_sync_job",
            site=frappe.local.site,
            enabled=bool(self.listener_enabled),
            port=cint(self.listener_port or 8998),
        )
        # write Procfile entry
        _write_procfile(port, self.listener_enabled)

        # refresh supervisor only if procfile changed
        if frappe.flags.in_test:           # skip in tests
            return
        import subprocess, pathlib
        subprocess.call(["bench", "setup", "procfile"])
        subprocess.call(["bench", "setup", "supervisor"])

    # ------------- client-side helper ---------------------------------------

def _public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=2).text
    except Exception:
        return frappe.local.site

@frappe.whitelist()
def fetch_status(self):
    port = cint(self.listener_port or 8998)
    host = _public_ip()
    base = f"http://{host}:{port}"
    return {
        "listener_status": "Running" if _is_running(port) else "Stopped",
        "ebkn_webhook_url":   f"{base}/ebkn",
        "zkteco_webhook_url": f"{base}/zkteco",
        "suprema_webhook_url":f"{base}/suprema",
    }


# --------------------------------------------------------------------------- #
#  background job                                                             #
# --------------------------------------------------------------------------- #

def listener_sync_job(site: str, enabled: bool, port: int):
    """Runs in a worker; updates Procfile + supervisor safely."""
    frappe.init(site=site); frappe.connect()
    try:
        _write_procfile(port, enabled)
        _supervisor("update")
        _supervisor("restart" if enabled else "stop")
    except Exception as exc:
        frappe.log_error(str(exc), "Listener sync job failed")
    finally:
        frappe.destroy()
