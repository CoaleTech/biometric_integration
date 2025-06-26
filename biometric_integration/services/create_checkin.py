import os
import logging
import frappe
from datetime import datetime
from frappe.model.document import Document
from biometric_integration.biometric_integration.doctype.biometric_integration_settings.biometric_integration_settings import get_erp_employee_id
from biometric_integration.utils.site_session import init_site, destroy_site

def create_employee_checkin(employee_field_value, timestamp, device_id=None, log_type=None):
    """
    Create an Employee Checkin record in the resolved site corresponding to the given device_id.

    Args:
        employee_field_value (int): The unique value identifying the employee (attendance_device_id).
        timestamp (str): The timestamp in '%Y-%m-%d %H:%M:%S' format.
        device_id (str): The unique device ID to resolve which site to connect to.
        log_type (str): "IN" or "OUT" indicating check-in direction.

    Returns:
        bool: True if the check-in was successfully created, False otherwise.
    """
    try:
        init_site(device_id=device_id)
        # Fetch settings with caching
        settings = frappe.get_cached_doc("Biometric Integration Settings")

        # Resolve ERP Employee ID using the provided device ID
        employee_id = get_erp_employee_id(employee_field_value)

        if not employee_id:
            if not settings.do_not_skip_unknown_employee_checkin:
                logging.warning(f"Skipping check-in for unknown Employee ID: {employee_field_value}")
                return False  # Skip processing as per settings

            logging.info(f"Processing check-in for unknown Employee ID: {employee_field_value}")

        # Prepare the Employee Checkin document
        checkin = frappe.new_doc("Employee Checkin")
        checkin.employee = employee_id
        checkin.log_type = log_type
        checkin.time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        checkin.device_id = device_id

        # Insert the document into the database
        checkin.insert(ignore_mandatory=True)
        frappe.db.commit()
        destroy_site()
        logging.info(f"Check-in successfully created for Employee {employee_id} at {timestamp}")
        return True

    except frappe.exceptions.ValidationError as ve:
        error_message = str(ve)

        if "already has a log with the same timestamp" in error_message:
            logging.warning(f"Duplicate check-in detected: {error_message}")
            return True  # Treat duplicates as success

        if "No Employee found for the given employee field value" in error_message:
            logging.warning(f"No associated Employee: {error_message}")
            return False

        logging.error(f"Validation error while creating check-in: {error_message}", exc_info=True)
        return False

    except Exception as e:
        logging.error(f"Unexpected error creating check-in: {str(e)}", exc_info=True)
        return False