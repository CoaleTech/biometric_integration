from __future__ import annotations
import re
import random
import frappe
from frappe.model.document import Document

class BiometricIntegrationSettings(Document):
    def validate(self):
        """Validate settings related to Employee ID mapping."""
        if (self.employee_id_mapping_method == "Use Device ID Field" and not self.device_id_field):
            frappe.throw("Device ID Field is required when mapping method is ‘Use Device ID Field’.")
        if (self.employee_id_mapping_method == "Clean Employee ID with Regex" and not self.clean_id_regex):
            frappe.throw("Clean-ID regex is required for that mapping mode.")
        if self.clean_id_regex:
            try: re.compile(self.clean_id_regex)
            except re.error: frappe.throw("Invalid regex pattern for Clean-ID.")
        try:
            employees = frappe.get_all("Employee", pluck="name", limit=30)
            sample = random.sample(employees, min(5, len(employees)))
            self.example_cleaned_ids = "\n".join(f"{i} → {re.sub(self.clean_id_regex or '', '', i)}" for i in sample)
        except Exception: self.example_cleaned_ids = "Could not generate examples."

def get_device_employee_id(employee_id: str) -> str | None:
    """Converts an ERP Employee ID to a Device Employee ID."""
    if not employee_id:
        frappe.log_error(title="Missing Employee ID", message="get_device_employee_id called with no Employee ID.")
        return None
    settings = frappe.get_cached_doc("Biometric Integration Settings")
    try:
        if settings.employee_id_mapping_method == "Use Device ID Field":
            device_employee_id = frappe.get_value("Employee", employee_id, settings.device_id_field)
            if not device_employee_id:
                frappe.log_error(title="Device ID Not Found", message=f"Could not find value in field '{settings.device_id_field}'.", reference_doctype="Employee", reference_name=employee_id)
                return None
            return device_employee_id
        elif settings.employee_id_mapping_method == "Clean Employee ID with Regex":
            if not settings.clean_id_regex:
                frappe.log_error(title="Regex Not Configured", message="Employee ID mapping method is 'Clean ID with Regex' but no regex is provided in settings.")
                return None
            return re.sub(settings.clean_id_regex, "", employee_id)
        else:
            frappe.log_error(title="Unsupported Mapping Method", message=f"Unsupported mapping method: {settings.employee_id_mapping_method}")
            return None
    except Exception:
        frappe.log_error(title="ID Mapping Exception", message=frappe.get_traceback(), reference_doctype="Employee", reference_name=employee_id)
        return None

def get_erp_employee_id(device_employee_id: str) -> str | None:
    """Converts a Device Employee ID to an ERP Employee ID."""
    if not device_employee_id:
        frappe.log_error(title="Missing Device ID", message="get_erp_employee_id called with no Device Employee ID.")
        return None
    settings = frappe.get_cached_doc("Biometric Integration Settings")
    try:
        if settings.employee_id_mapping_method == "Use Device ID Field":
            erp_employee_id = frappe.get_value("Employee", {settings.device_id_field: device_employee_id}, "name")
            if not erp_employee_id:
                frappe.log_error(title="Employee Not Found by Device ID", message=f"No Employee found with Device ID '{device_employee_id}' in field '{settings.device_id_field}'.")
                return None
            return erp_employee_id
        elif settings.employee_id_mapping_method == "Clean Employee ID with Regex":
            erp_employee_id = frappe.get_value("Employee", {"name": device_employee_id}, "name")
            if not erp_employee_id:
                frappe.log_error(title="Employee Not Found by Cleaned ID", message=f"No Employee found with name matching the cleaned ID '{device_employee_id}'.")
                return None
            return erp_employee_id
        else:
            frappe.log_error(title="Unsupported Mapping Method", message=f"Unsupported mapping method: {settings.employee_id_mapping_method}")
            return None
    except Exception:
        frappe.log_error(title="ID Mapping Exception", message=frappe.get_traceback())
        return None
