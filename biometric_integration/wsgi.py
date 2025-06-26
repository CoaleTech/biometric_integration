# biometric_integration/wsgi.py

import os
import sys
import logging

# --- Environment Bootstrap ---
# This code runs ONCE when Gunicorn starts a worker process.
# Its only job is to set up the correct paths so Frappe can be found.

# Determine the absolute path to the bench directory.
# This makes the application portable and not dependent on hardcoded paths.
try:
    BENCH_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    
    # Forcefully change the current working directory. All relative paths used by Frappe
    # will now correctly start from the bench root.
    os.chdir(BENCH_PATH)

    # Add the 'apps' directory to the system path to ensure all apps are importable.
    apps_path = os.path.join(BENCH_PATH, 'apps')
    if apps_path not in sys.path:
        sys.path.insert(0, apps_path)
except Exception as e:
    logging.getLogger("biometric_listener").error(f"CRITICAL: Failed to bootstrap bench environment. Error: {e}")
    raise

# --- End of Bootstrap ---

# Now that the environment is correct, we can safely import Frappe and the real listener app.
import frappe
from werkzeug.wrappers import Request
from biometric_integration.services.listener import application as listener_app
from biometric_integration.services.device_mapping import get_site_for_device

# This is the main application object that Gunicorn will run.
# It is a wrapper that sets up the site context for each request.
@Request.application
def application(request: Request):
    """
    Main WSGI application wrapper.

    This function is executed for EVERY request. It determines the correct site,
    initializes the Frappe context fully, and then passes control to the
    actual listener application. This eliminates the need for manual init/destroy
    calls within the application logic.
    """
    site = None
    try:
        # Determine which site this request is for.
        dev_id = request.headers.get('Dev-Id')
        if dev_id:
            site_info = get_site_for_device(dev_id)
            if site_info:
                site = site_info['site_name']
        
        # Fallback to the first site in sites.txt if no specific site is found
        if not site:
            with open(os.path.join(BENCH_PATH, "sites", "sites.txt"), "r") as f:
                site = f.readline().strip()

        # Initialize the site context. This is the core fix.
        # We explicitly tell Frappe where the sites and logs are.
        frappe.init(site, sites_path=os.path.join(BENCH_PATH, 'sites'))
        frappe.conf['logs_path'] = os.path.join(BENCH_PATH, 'logs')
        frappe.connect()
        frappe.set_user("Administrator")

        # Call the actual listener application from listener.py
        return listener_app(request.environ, lambda status, headers: None)

    except Exception:
        # If anything fails during initialization, log it and return a server error.
        frappe.log_error("Failed to process biometric request in WSGI wrapper")
        response = frappe.utils.response.report_error(500)
        return response
    finally:
        # The context is automatically destroyed after the request,
        # so we ensure the database connection is closed.
        if frappe.local.db:
            frappe.local.db.close()

