# Copyright (c) 2024-2025, Khaled Bin Amir
# SPDX-License-Identifier: MIT

import logging
import os
from logging.handlers import RotatingFileHandler
from frappe.utils import get_bench_path

def get_biometric_logger():
    """
    Configures and returns a dedicated, rotating logger for the biometric integration service.
    This ensures all related logs are written to a single, size-managed file.
    """
    logger_name = "biometric_listener"
    logger = logging.getLogger(logger_name)
    
    # Configure logger only once to prevent adding duplicate handlers on reloads.
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        log_file = os.path.join(get_bench_path(), "logs", "biometric_listener.log")
        
        # Use RotatingFileHandler to keep logs lightweight.
        # This will create up to 5 backup files of 1MB each.
        handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        
    return logger

# Create a single instance that can be imported by other modules.
logger = get_biometric_logger()
