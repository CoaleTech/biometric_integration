# biometric_integration/services/supervisor_util.py

import configparser
import os
import pwd
import subprocess
import frappe

# --- Configuration Constants ---
BENCH_PATH = frappe.utils.get_bench_path()
SUP_CONF = os.path.join(BENCH_PATH, "config", "supervisor.conf")
PROGRAM_NAME = f"{os.path.basename(BENCH_PATH)}-biometric-listener"
SECTION = f"program:{PROGRAM_NAME}"

# --- Helper Functions ---
def _conf_parser() -> configparser.ConfigParser:
    if not os.path.exists(SUP_CONF):
        raise FileNotFoundError("Run `bench setup supervisor` once before enabling the listener")
    cfg = configparser.ConfigParser()
    cfg.read(SUP_CONF)
    return cfg

def _get_web_user(cfg: configparser.ConfigParser) -> str:
    web_section = f"program:{os.path.basename(BENCH_PATH)}-frappe-web"
    return cfg.get(web_section, "user", fallback=pwd.getpwuid(os.getuid()).pw_name)

def _write_and_reload(cfg: configparser.ConfigParser) -> None:
    with open(SUP_CONF, "w") as fh:
        cfg.write(fh)
    _supervisorctl("reread")
    _supervisorctl("update")

def _supervisorctl(*args) -> None:
    try:
        subprocess.check_call(["supervisorctl", *args], cwd=BENCH_PATH, capture_output=True)
    except Exception:
        pass # Silently ignore if supervisord isn’t running

# --- Public API ---
def program_exists() -> bool:
    return SECTION in _conf_parser()

def add_program(port: int) -> None:
    cfg = _conf_parser()
    
    gunicorn_command = (
        f"{os.path.join(BENCH_PATH, 'env', 'bin', 'gunicorn')} "
        f"-w 1 --threads 4 "
        "--header-map dangerous "
        f"--bind 0.0.0.0:{port} "
        # We no longer need --chdir as the SITES_PATH env var is more robust.
        "biometric_integration.services.listener:application"
    )

    # --- THE DEFINITIVE FIX ---
    # We set the SITES_PATH environment variable, which is the canonical way
    # to tell the Frappe framework where the bench is located when running
    # in a non-standard context like this.
    environment_vars = f'BIOMETRIC_PORT={port},SITES_PATH="{BENCH_PATH}"'
    # --------------------------

    cfg[SECTION] = {
        "command": gunicorn_command,
        "autostart": "true",
        "autorestart": "true",
        "stdout_logfile": os.path.join(BENCH_PATH, 'logs', f"{PROGRAM_NAME}.log"),
        "stderr_logfile": os.path.join(BENCH_PATH, 'logs', f"{PROGRAM_NAME}.error.log"),
        "user": _get_web_user(cfg),
        "directory": BENCH_PATH, # Still good practice to set this.
        "environment": environment_vars,
    }

    _write_and_reload(cfg)
    _supervisorctl("start", PROGRAM_NAME)

def remove_program() -> None:
    _supervisorctl("stop", PROGRAM_NAME)
    cfg = _conf_parser()
    if SECTION in cfg:
        cfg.remove_section(SECTION)
        _write_and_reload(cfg)
