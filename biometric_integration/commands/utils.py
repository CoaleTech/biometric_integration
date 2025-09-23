import os
import re
import subprocess
import json
import urllib.request
import platform
import click
import frappe
from frappe.utils import get_bench_path, get_url, get_site_path
from frappe.installer import update_site_config

# --- Constants ---
NGINX_CONF_PATH = os.path.join(get_bench_path(), "config", "nginx.conf")
LISTENER_PORT_KEY = "biometric_listener_port"

# --- Site Config Helpers ---
def get_config_key(key):
    """Reads a key from the current site's config using the Frappe API."""
    return frappe.conf.get(key)

def _set_config_key(key, value):
    """Writes a key-value pair to the current site's config using the Frappe API."""
    update_site_config(key, value, site_config_path=get_site_path("site_config.json"))

def _remove_config_key(key):
    """Removes a key from the current site's config."""
    site_config_path = get_site_path("site_config.json")
    if not os.path.exists(site_config_path):
        return
    with open(site_config_path, "r") as f:
        conf = json.load(f)
    if conf.pop(key, None):
        with open(site_config_path, "w") as f:
            json.dump(conf, f, indent=4)

# --- NGINX and Logic Helpers ---
def _get_server_block_content(site, port):
    """Generates the full server block for the given site and port."""
    site_url = get_url()
    hostname = site_url.split("//")[-1].split("/")[0].split(":")[0]

    backend_service = "http://frappe-bench-frappe"
    api_path = "/api/method/biometric_integration.api.handle_request"
    final_proxy_url = f"{backend_service}{api_path}"
    
    return f"""
# -- BIOMETRIC_LISTENER_START_{site}_{port} --
server {{
    listen {port};
    server_name _;
    underscores_in_headers on; # Keep this for good measure

    location / {{
        set $backend_url {final_proxy_url};
        proxy_pass $backend_url;
        
        proxy_set_header Host {hostname};
        
        # FIX: Manually transform underscore headers to hyphenated X- headers.
        # This prevents Gunicorn from dropping them.
        proxy_set_header X-Request-Code $http_request_code;
        proxy_set_header X-Dev-Id $http_dev_id;
        proxy_set_header X-Blk-No $http_blk_no;
        proxy_set_header X-Trans-Id $http_trans_id;
        proxy_set_header X-Cmd-Return-Code $http_cmd_return_code;
        
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Original-Request-URI $request_uri;
        proxy_pass_request_headers on;
    }}
}}
# -- BIOMETRIC_LISTENER_END_{site}_{port} --
"""

def _reload_nginx():
    """Safely reloads the NGINX service."""
    try:
        click.secho("Attempting to reload NGINX...", fg="yellow")

        # Detect OS and use appropriate reload command
        system = platform.system().lower()
        if system == "linux":
            # Linux systems typically use systemctl or service
            try:
                subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True, capture_output=True, text=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback to service command
                subprocess.run(["sudo", "service", "nginx", "reload"], check=True, capture_output=True, text=True)
        elif system == "darwin":  # macOS
            # macOS with Homebrew nginx
            subprocess.run(["sudo", "nginx", "-s", "reload"], check=True, capture_output=True, text=True)
        else:
            # Other systems - try nginx -s reload
            subprocess.run(["sudo", "nginx", "-s", "reload"], check=True, capture_output=True, text=True)

        click.secho("NGINX reloaded successfully.", fg="green")
        return True, ""
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_message = f"Error reloading NGINX: {e.stderr or e}"
        click.secho(error_message, fg="red")
        return False, error_message

def _update_nginx_config(new_content):
    with open(NGINX_CONF_PATH, "w") as f:
        f.write(new_content)

def enable_listener_logic(site, port):
    """Core logic to inject NGINX config and update site config."""
    if not os.path.exists(NGINX_CONF_PATH):
        return False, f"NGINX config not found at: {NGINX_CONF_PATH}"

    with open(NGINX_CONF_PATH, "r") as f:
        content = f.read()

    start_marker = f"# -- BIOMETRIC_LISTENER_START_{site}_{port} --"
    if start_marker in content:
        return True, f"Listener for site {site} on port {port} already exists."

    new_server_block = _get_server_block_content(site, port)
    _update_nginx_config(content.strip() + "\n\n" + new_server_block)
    
    _set_config_key(LISTENER_PORT_KEY, port)

    success, message = _reload_nginx()
    return (True, f"Successfully enabled listener for {site} on port {port}.") if success else (False, message)

def disable_listener_logic(site):
    """Core logic to remove NGINX config and update site config."""
    port = get_config_key(LISTENER_PORT_KEY)
    if not port:
        return True, f"Listener is not enabled for site {site}."

    if not os.path.exists(NGINX_CONF_PATH):
        return False, f"NGINX config not found at: {NGINX_CONF_PATH}"
        
    with open(NGINX_CONF_PATH, "r") as f:
        content = f.read()

    start_marker = f"# -- BIOMETRIC_LISTENER_START_{site}_{port} --"
    end_marker = f"# -- BIOMETRIC_LISTENER_END_{site}_{port} --"
    pattern = re.compile(f"\\s*{re.escape(start_marker)}.*?{re.escape(end_marker)}", re.DOTALL)
    _update_nginx_config(pattern.sub("", content))
    
    _remove_config_key(LISTENER_PORT_KEY)

    success, message = _reload_nginx()
    return (True, f"Successfully disabled listener for {site}.") if success else (False, message)

def get_status_logic(site):
    """Core logic to get the status of a listener."""
    port = get_config_key(LISTENER_PORT_KEY)
    
    listen_ip_display = "0.0.0.0 (All Interfaces)"
    
    if port:
        try:
            path_ip = urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode("utf-8")
        except Exception as e:
            frappe.log_error(f"Could not fetch public IP from ipify: {e}", "Biometric Integration")
            site_url = get_url()
            path_ip = site_url.split("//")[-1].split("/")[0].split(":")[0]

        return {
            "status": "enabled",
            "listening_ip": listen_ip_display,
            "port": port,
            "paths": {
                "ebkn": f"http://{path_ip}:{port}/ebkn",
                "suprema": f"http://{path_ip}:{port}",
                "zkteco": f"http://{path_ip}:{port}",
                "hikvision": f"http://{path_ip}:{port}",
            },
        }
    else:
        return {"status": "disabled"}
