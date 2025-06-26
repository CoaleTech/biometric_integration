# biometric_integration/commands/__init__.py

import click
import subprocess
from biometric_integration.services.common_conf import get_port, set_port
from biometric_integration.services.supervisor_util import (
    add_program,
    remove_program,
    program_exists,
    PROGRAM_NAME
)

# --- Helper to show status ---
def _show_status():
    ctx = click.get_current_context()
    ctx.invoke(status)

# --- Command Group Definition ---
@click.group("biometric-listener")
def listener():
    """Enable, disable, or check the status of the biometric listener service."""
    pass

# --- Enable Command ---
@listener.command("enable")
@click.option("-p", "--port", type=int, help="Custom TCP port (default 8998).")
def enable(port: int | None):
    """Adds the listener to Supervisor and starts it."""
    if program_exists():
        click.secho("Listener is already enabled. Showing status.", fg="yellow")
        _show_status()
        return

    port_to_set = port or get_port()
    set_port(port_to_set)
    click.echo(f"Enabling listener on port {port_to_set}...")
    add_program(port_to_set)
    click.secho("Listener enabled successfully. Current status:", fg="green")
    _show_status()

# --- Disable Command ---
@listener.command("disable")
def disable():
    """Stops and removes the listener from Supervisor."""
    if not program_exists():
        click.secho("Listener is not enabled. Nothing to do.", fg="yellow")
        return

    click.echo("Disabling listener...")
    remove_program()
    click.secho("Listener disabled successfully.", fg="green")

# --- Status Command ---
@listener.command("status")
def status():
    """Checks the running state and configuration of the listener."""
    if not program_exists():
        click.secho("Listener is not configured.", fg="red")
        click.echo("Use 'bench biometric-listener enable' to set it up.")
        return

    port = get_port()
    click.echo(click.style("Biometric Listener Status", bold=True))
    click.echo(f"─" * 30)
    click.echo(f"Port           : {port}")
    
    try:
        # Check supervisor for the running state
        output = subprocess.check_output(["supervisorctl", "status", PROGRAM_NAME], text=True)
        state = output.split()[1]
        pid_info = " ".join(output.split()[2:])
        if state == "RUNNING":
            click.echo(f"Service State  : {click.style(state, fg='green')} ({pid_info})")
        else:
            click.echo(f"Service State  : {click.style(state, fg='red')} ({pid_info})")

    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo(f"Service State  : {click.style('UNKNOWN', fg='red')} (Could not query supervisor)")
    
    click.echo(f"─" * 30)


# Expose commands to the bench CLI
commands = [listener]
