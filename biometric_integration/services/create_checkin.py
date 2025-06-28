from __future__ import annotations
from datetime import datetime
import frappe

# Using the full, absolute path for the import.
from biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings import get_erp_employee_id

def create_employee_checkin(
    employee_field_value: str,
    timestamp: str,
    device_id: str | None = None,
    log_type: str | None = None
) -> bool:
    """
    Creates an Employee Checkin record. This version only logs critical,
    actionable errors.
    """
    try:
        settings = frappe.get_cached_doc("Biometric Integration Settings")
        employee_id = get_erp_employee_id(employee_field_value)

        # If employee is not found, either skip silently or proceed to insert
        # a check-in with a blank employee link, based on settings.
        if not employee_id and not settings.do_not_skip_unknown_employee_checkin:
            return False

        checkin = frappe.new_doc("Employee Checkin")
        checkin.employee = employee_id
        checkin.log_type = log_type
        checkin.time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        checkin.device_id = device_id

        checkin.insert(ignore_mandatory=True if not employee_id else False, ignore_permissions=True)
        frappe.db.commit()

        return True

    except frappe.exceptions.ValidationError as ve:
        # Silently ignore duplicate check-ins, as they are not a critical error.
        if "already has a log with the same timestamp" in str(ve):
            return True

        # Log other validation errors as they are critical and unexpected.
        frappe.log_error(
            title="Check-in Validation Error",
            message=frappe.get_traceback(),
            reference_doctype="Employee",
            reference_name=employee_id
        )
        return False

    except Exception:
        frappe.db.rollback()
        # Log any other unexpected exception as a critical error.
        frappe.log_error(
            title="Failed to Create Employee Check-in",
            message=frappe.get_traceback(),
            reference_doctype="Employee",
            reference_name=employee_id
        )
        return False
