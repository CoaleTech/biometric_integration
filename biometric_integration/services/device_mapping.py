import frappe
import json
import os
import logging

def get_biometric_assets_dir():
    """
    Get the path to the global biometric_assets directory located in:
    frappe-bench/sites/assets/biometric_assets
    """
    bench_path = frappe.utils.get_bench_path()
    assets_dir = os.path.join(bench_path, "sites", "assets", "biometric_assets")
    os.makedirs(assets_dir, exist_ok=True)
    return assets_dir

def get_device_site_map_path():
    """
    Get the path to the device-site mapping JSON file (device_site.json) in the biometric_assets directory.
    """
    assets_dir = get_biometric_assets_dir()
    file_path = os.path.join(assets_dir, "device_site.json")
    logging.debug(f"Device site map path resolved to: {file_path}")
    return file_path

def load_device_site_map():
    """
    Load the device-site map from the device_site.json file.

    Returns:
        dict: The device-site mapping.
    """
    file_path = get_device_site_map_path()
    logging.debug(f"Loading device site map from: {file_path}")

    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                device_site_map = json.load(f)
                logging.debug(f"Loaded device site map: {device_site_map}")
                return device_site_map
        except Exception as e:
            logging.error(f"Error loading device site map: {str(e)}")
            return {}
    else:
        logging.error(f"Device site map file does not exist at: {file_path}. Returning empty map.")
        return {}

def save_device_site_map(device_site_map):
    """
    Save the device-site map to the device_site.json file.

    Args:
        device_site_map (dict): The device-site mapping to save.
    """
    file_path = get_device_site_map_path()
    logging.debug(f"Saving device site map to: {file_path}")
    try:
        with open(file_path, "w") as f:
            json.dump(device_site_map, f, indent=4)
            logging.debug("Device site map saved successfully.")
    except Exception as e:
        logging.error(f"Error saving device site map: {str(e)}")

def get_site_for_device(device_id):
    """
    Fetch the site name and has_pending_command for a given device ID using the JSON file.

    Args:
        device_id (str): The ID of the biometric device.

    Returns:
        dict: Contains 'site_name' and 'has_pending_command' or None if not found.
    """
    try:
        logging.debug(f"Fetching site for device ID: {device_id}")
        device_site_map = load_device_site_map()
        device_info = device_site_map.get(device_id)

        if not device_info:
            logging.error(f"Device ID {device_id} is not mapped to any site.")
            return None

        logging.debug(f"Resolved site info for device ID {device_id}: {device_info}")
        return {
            "site_name": device_info.get("site_name"),
            "disabled" : device_info.get("disabled", 0),
            "has_pending_command": device_info.get("has_pending_command", 0)
        }
    except Exception as e:
        logging.error(f"Error fetching site for device ID {device_id}: {str(e)}")
        return None