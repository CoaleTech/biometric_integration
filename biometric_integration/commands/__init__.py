import click
import frappe
import json

from biometric_integration.commands.utils import (
    enable_listener_logic,
    disable_listener_logic,
    get_status_logic,
    get_config_key, # FIX: Import the correct, public function name
    LISTENER_PORT_KEY
)

from frappe.commands import pass_context

@click.group("biometric-listener")
def listener():
    """Manage NGINX listeners for biometric devices."""
    pass

@listener.command("enable")
@click.option("--port", type=int, help="The port to listen on. Reads from site_config.json if omitted.")
@pass_context
def enable(context, port):
    """Enables the NGINX listener for a site. The site is specified via the global --site flag."""
    try:
        site = context.sites[0]
    except IndexError:
        click.secho("Error: Please specify a site using: bench --site SITENAME biometric-listener enable", fg="red")
        return
    
    try:
        frappe.connect(site=site)
        
        # FIX: Use the correct function to read from config
        if not port:
            port = get_config_key(LISTENER_PORT_KEY)
        
        if not port:
            click.secho("Error: --port is required when no port is set in site_config.json", fg="red")
            return

        success, message = enable_listener_logic(site, port)
        click.secho(message, fg="green" if success else "red")
    except Exception as e:
        click.secho(f"An error occurred on site {site}: {e}", fg="red")
    finally:
        if frappe.local.db:
            frappe.destroy()

@listener.command("disable")
@pass_context
def disable(context):
    """Disables the NGINX listener for a site. The site is specified via the global --site flag."""
    try:
        site = context.sites[0]
    except IndexError:
        click.secho("Error: Please specify a site using: bench --site SITENAME biometric-listener disable", fg="red")
        return

    try:
        frappe.connect(site=site)
        success, message = disable_listener_logic(site)
        click.secho(message, fg="green" if success else "red")
    except Exception as e:
        click.secho(f"An error occurred on site {site}: {e}", fg="red")
    finally:
        if frappe.local.db:
            frappe.destroy()

@listener.command("status")
@pass_context
def status(context):
    """Checks the status of biometric listeners. Use --site to check a specific site, or no flag for all sites."""
    sites_to_check = context.sites or frappe.utils.get_sites()
    all_statuses = {}

    for s in sites_to_check:
        try:
            frappe.connect(site=s)
            all_statuses[s] = get_status_logic(s)
        except Exception as e:
            all_statuses[s] = {"status": "error", "message": str(e)}
        finally:
            if frappe.local.db:
                frappe.destroy()
    
    click.echo(json.dumps(all_statuses, indent=2))


# This is the entry point that bench will discover
commands = [listener]
