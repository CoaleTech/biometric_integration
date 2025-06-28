import frappe
import os

def get_biometric_assets_dir():
    """
    Get the path to the global biometric_assets directory located in:
    frappe-bench/sites/assets/biometric_assets
    """
    bench_path = frappe.utils.get_bench_path()
    assets_dir = os.path.join(bench_path, "sites", "assets", "biometric_assets")
    os.makedirs(assets_dir, exist_ok=True)
    return assets_dir
