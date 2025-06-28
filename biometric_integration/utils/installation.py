import os
import frappe
import logging
import shutil
from frappe.utils import get_sites

def after_uninstall():
    """Cleanup assets directory created by the biometric_integration app only if no site uses it."""
    app_name = "biometric_integration"
    try:
        # Check all sites to see if the app is still installed elsewhere
        found_app_in_site = False
        for site in get_sites():
            try:
                frappe.init(site=site)
                frappe.connect()
                if app_name in frappe.get_installed_apps():
                    found_app_in_site = True
                    break
            finally:
                if frappe.local.db:
                    frappe.destroy()

        if not found_app_in_site:
            assets_dir = os.path.join(frappe.utils.get_bench_path(), "sites", "assets", "biometric_assets")
            if os.path.exists(assets_dir):
                shutil.rmtree(assets_dir)
                logging.info("biometric_assets directory removed successfully.")
            else:
                logging.info("biometric_assets directory does not exist, no cleanup needed.")
        else:
             logging.info(f"App {app_name} is still installed in another site, not removing assets.")

    except Exception as e:
        logging.error(f"Error while cleaning up biometric_assets directory: {str(e)}")
