# biometric_integration/utils/site_session.py

import os
import logging
import frappe
from biometric_integration.services.device_mapping import get_site_for_device

logger = logging.getLogger("biometric_listener")

def get_bench_path():
    """
    Gets the bench path with maximum robustness for a Gunicorn environment.
    1. Tries the SITES_PATH environment variable (the canonical way).
    2. Falls back to calculating from this file's known location.
    3. As a last resort, uses the current working directory.
    """
    # 1. The canonical way: from environment variable set by Supervisor
    sites_path_env = os.environ.get("SITES_PATH")
    if sites_path_env and os.path.isdir(os.path.join(sites_path_env, 'sites')):
        return sites_path_env

    # 2. Fallback: calculate from this file's location
    try:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
        if 'sites' in os.listdir(path):
            return path
    except Exception:
        pass

    # 3. Last resort: current working directory
    return os.getcwd()


# Determine the bench path once when the module is loaded.
_BENCH_PATH = get_bench_path()


def init_site(device_id: str = None, site_name: str = None):
    """
    Initializes a Frappe environment, defensively setting all paths to ensure
    correct operation within a Gunicorn worker.
    """
    if not site_name:
        if not device_id:
            raise ValueError("Either site_name or device_id is required to initialize site.")

        logger.debug(f"Looking up site for device_id: {device_id}")
        device_info = get_site_for_device(device_id)

        if not device_info or not device_info.get("site_name"):
            raise ValueError(f"No site mapping found for device_id: {device_id}")
        
        site_name = device_info["site_name"]
        
    site_name = site_name.strip()
    logger.info(f"Attempting to initialize Frappe context for site: '{site_name}'")
    logger.info(f"Using Bench Path: {_BENCH_PATH}")

    try:
        # Step 1: Initialize the site, EXPLICITLY passing the sites_path.
        # This mirrors `frappe/app.py` and is more robust than relying on the env var alone.
        sites_path = os.path.join(_BENCH_PATH, 'sites')
        frappe.init(site=site_name, sites_path=sites_path)

        # Step 2: Manually inject the correct logs_path into the loaded configuration.
        # This is the most direct way to fix the logging FileNotFoundError.
        frappe.conf['logs_path'] = os.path.join(_BENCH_PATH, 'logs')
        
        # Step 3 (Defensive): If a 'database' logger already exists, it might be broken
        # due to Gunicorn's startup process. Remove it to force Frappe to create a
        # new one using our correct config.
        if 'database' in frappe.loggers:
            del frappe.loggers['database']

        # Step 4: Now, safely connect to the database.
        frappe.connect()

        # Step 5: Set the user.
        frappe.set_user("Administrator")
        logger.info(f"Frappe context successfully initialized for site '{site_name}'")

    except Exception as e:
        logger.error(f"Failed to initialize site '{site_name}': {e}", exc_info=True)
        frappe.destroy()
        raise

def destroy_site():
    """
    Completely destroys the Frappe context to clean up the session.
    """
    if hasattr(frappe.local, 'db') and frappe.local.db:
        frappe.local.db.close()
    
    frappe.destroy()
    logger.info("Frappe context destroyed.")

