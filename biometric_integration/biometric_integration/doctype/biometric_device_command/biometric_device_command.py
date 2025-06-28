# Copyright (c) 2024, KhaledBinAmir
# License: see license.txt

from __future__ import annotations
import logging
import time
import hashlib
from datetime import datetime
import frappe
from frappe.model.document import Document
from frappe.utils import cint, add_to_date, now_datetime, get_datetime

# REMOVED: The import for the helper function is no longer needed.

class BiometricDeviceCommand(Document):
    def after_insert(self):
        """
        When a new command is created, set the cache flag on its
        parent device to 1 (True) so the processor knows to check it.
        """
        if self.biometric_device:
            # FIX: Use db.set_value directly as requested.
            frappe.db.set_value("Biometric Device", self.biometric_device, "has_pending_command", 1)
            frappe.db.commit() # Commit immediately for the next request.

    def before_save(self):
        """Enforce maximum attempts / age‑based auto‑close rules."""
        try:
            settings = frappe.db.get_value("Biometric Integration Settings", None, ["maximum_no_of_attempts_for_commands", "force_close_after"], as_dict=True) or {}
            max_attempts, force_days = cint(settings.get("maximum_no_of_attempts_for_commands")), cint(settings.get("force_close_after"))
            if max_attempts and cint(self.no_of_attempts) >= max_attempts and self.status not in ("Closed", "Success", "Failed"):
                self.status, self.closed_on = "Failed", now_datetime()
                logging.info(f"BDC {self.name} closed by max_attempts ({max_attempts})")

            # FIX: Convert self.initiated_on to a datetime object before comparison.
            if force_days and self.initiated_on and add_to_date(get_datetime(self.initiated_on), days=force_days) <= now_datetime():
                if self.status not in ("Closed", "Success", "Failed"):
                    self.status, self.closed_on = "Failed", now_datetime()
                    logging.info(f"BDC {self.name} force‑closed after {force_days} days")
        except Exception as exc:
            frappe.log_error(frappe.get_traceback(), "BDC before_save failed")
            logging.error("before_save error: %s", exc, exc_info=True)

def add_command(device_id: str, user_id: str, brand: str, command_type: str) -> None:
    """Create a Biometric Device Command unless an equivalent pending one exists."""
    if frappe.db.exists("Biometric Device Command", {"biometric_device": device_id, "biometric_device_user": user_id, "brand": brand, "command_type": command_type, "status": "Pending"}):
        return
    cmd = frappe.get_doc({"doctype": "Biometric Device Command", "biometric_device": device_id, "biometric_device_user": user_id, "brand": brand, "command_type": command_type, "status": "Pending"})
    cmd.insert(ignore_permissions=True)
    # The after_insert hook handles committing the flag update.
