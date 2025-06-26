# Copyright (c) 2024, KhaledBinAmir
# License: see license.txt

"""Controller for **Biometric Device Command** DocType.

Responsibilities
----------------
* On **insert** ➜ mark the linked *Biometric Device* as having pending
  work (`has_pending_command = 1`).
* On **save**   ➜ auto‑close / error‑out commands that exceeded
  configurable limits (attempt count or age).

Configuration is taken from the **Biometric Integration Settings** single
DocType:

* ``maximum_no_of_attempts_for_commands`` – int, attempts before we mark
  *Error*.
* ``force_close_after`` (days) – int, days after *initiated_on* when we force
  *Closed* if still unfinished.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import frappe  # type: ignore
from frappe.model.document import Document
from frappe.utils import cint, add_to_date, now_datetime


class BiometricDeviceCommand(Document):
    """Extend DocType with lifecycle helpers."""

    # ------------------------------------------------------------------
    #  Doc Events
    # ------------------------------------------------------------------

    def after_insert(self):  # pylint: disable=method-hidden
        """When a new command is created mark its device as *pending*."""
        try:
            if self.biometric_device:
                from biometric_integration.biometric_integration.doctype.biometric_device.biometric_device import update_has_pending_command
                update_has_pending_command(self.biometric_device, 1)
        except Exception as exc:  # pragma: no cover
            frappe.log_error(frappe.get_traceback(), "BDC after_insert failed")
            logging.error("after_insert error: %s", exc, exc_info=True)

    def before_save(self):  # pylint: disable=method-hidden
        """Enforce maximum attempts / age‑based auto‑close rules."""
        try:
            settings = frappe.db.get_value(  # type: ignore
                "Biometric Integration Settings",
                None,
                [
                    "maximum_no_of_attempts_for_commands",
                    "force_close_after",
                ],
                as_dict=True,
            ) or {}

            max_attempts = cint(settings.get("maximum_no_of_attempts_for_commands"))
            force_days   = cint(settings.get("force_close_after"))

            # 1️⃣ max‑attempts rule ------------------------------------------------
            if max_attempts and cint(self.no_of_attempts) >= max_attempts:
                if self.status not in ("Closed", "Completed"):
                    self.status = "Failed"
                    self.closed_on = now_datetime()
                    logging.info(
                        "BDC %s closed by max_attempts (%s)", self.name, max_attempts
                    )

            # 2️⃣ age‑based force‑close -------------------------------------------
            if (
                force_days
                and self.initiated_on
                and add_to_date(self.initiated_on, days=force_days, as_datetime=True) <= now_datetime()
            ):
                if self.status not in ("Closed", "Success", "Failed"):
                    self.status = "Failed"
                    self.closed_on = now_datetime()
                    logging.info(
                        "BDC %s force‑closed after %s days", self.name, force_days
                    )

        except Exception as exc:  # pragma: no cover
            frappe.log_error(frappe.get_traceback(), "BDC before_save failed")
            logging.error("before_save error: %s", exc, exc_info=True)


def add_command(
    device_id: str,
    user_id: str,
    brand: str,
    command_type: str,  # "Enroll User" | "Delete User"
) -> None:
    """
    Create one *Biometric Device Command* (status=Pending) unless an equivalent
    pending command already exists.
    """
    exists = frappe.db.exists(
        "Biometric Device Command",
        {
            "biometric_device":       device_id,
            "biometric_device_user":  user_id,
            "brand":                  brand,
            "command_type":           command_type,
            "status":                 "Pending", 
        },
    )
    if exists:
        return

    cmd = frappe.get_doc({
        "doctype":               "Biometric Device Command",
        "biometric_device":      device_id,
        "biometric_device_user": user_id,
        "brand":                 brand,
        "command_type":          command_type,
        "status":                "Pending",
    })
    cmd.insert(ignore_permissions=True)
    
    frappe.db.commit()