# Biometric Integration for Frappe

A Frappe app for seamless integration with popular biometric attendance and access control devices. This app provides a robust, centralized architecture to handle real-time data from multiple device brands, including EBKN and ZKTeco.

## Project Status

* **EBKN Integration:** ✅ Stable and fully functional. Supports real-time attendance logs and command processing.
* **ZKTeco Integration:** 🚧 In active development. The core logic for handling the ADMS Push Protocol is in place but requires further testing.
* **Suprema Integration:** planned.

## Key Features

* **Multi-Brand Architecture:** A single, unified API endpoint handles requests from different device brands, routing them to brand-specific processors.
* **Real-Time Push Protocol Support:** Leverages a custom Nginx reverse proxy to listen for real-time data pushed from devices, eliminating the need for periodic polling.
* **Centralized Command & Control:** Queue up commands (e.g., "Enroll User," "Delete User") within Frappe, and the app will deliver them to the correct device when it next checks in.
* **Multi-Device User Sync:** Enroll a user on one device, and their biometric data (e.g., fingerprint template) can be automatically synchronized to all other devices they are assigned to.
* **Automated Setup:** Includes a custom `bench` command to automatically configure the required Nginx listener, simplifying the initial setup.

## How It Works (Architecture)

This app avoids the need for a separate, constantly running Python service. Instead, it uses a clever Nginx reverse proxy setup.

1.  A custom `bench` command adds a `server` block to your `nginx.conf`.
2.  This block listens on a dedicated port (e.g., 8998) for all incoming device communication.
3.  Nginx proxies all requests from this port to a single, guest-allowed Frappe API endpoint: `biometric_integration.api.handle_request`.
4.  This central API endpoint inspects the request and routes it to the appropriate brand processor (`ebkn_processor.py` or `zkteco_processor.py`), which then handles the specific protocol logic.

```
+-----------------+      +---------------------------+      +--------------------------+      +----------------------+
| Biometric Device|----->| Nginx Reverse Proxy       |----->| Frappe API Endpoint      |----->|  Brand-Specific      |
| (EBKN / ZKTeco) |      | (e.g., your_domain:8998)   |      | (handle_request)         |      |  Processor           |
+-----------------+      +---------------------------+      +--------------------------+      +----------------------+
```

## Installation

1.  Go to your bench directory:
    ```bash
    cd /path/to/your/frappe-bench
    ```

2.  Get the app from GitHub:
    ```bash
    bench get-app [https://github.com/KhaledBinAmir/biometric_integration](https://github.com/KhaledBinAmir/biometric_integration)
    ```

3.  Install the app on your site:
    ```bash
    bench --site your_site_name.local install-app biometric_integration
    ```

## Setup and Configuration

Follow these steps to get the system up and running.

### Step 1: Enable the Biometric Listener

This is a one-time setup step that configures Nginx. Choose a port that is not currently in use (e.g., 8998, 8008, etc.).

From your `frappe-bench` directory, run the following command:

```bash
bench biometric-listener enable --port 8998
```

This command will automatically add the required server block to your Nginx configuration and reload Nginx to apply the changes.

### Step 2: Check Listener Status

To confirm the listener is active and to find the URL for your devices, run:

```bash
bench biometric-listener --status
```

The output will show you the IP address and port that the system is listening on. This is the address you will configure your physical devices to point to.

**Example Output:**
```json
{
    "status": "enabled",
    "listening_ip": "0.0.0.0 (All Interfaces)",
    "port": 8998,
    "paths": {
        "ebkn": "http://your_public_ip:8998/ebkn",
        "zkteco": "http://your_public_ip:8998"
    }
}
```

### Step 3: Configure Devices in Frappe

1.  In your Frappe desk, go to the **Biometric Device** doctype.
2.  Create a new document for each physical device you want to connect.
3.  Enter the **Serial No** (this must match the Serial Number or Device ID from the physical device).
4.  Select the correct **Brand** (EBKN or ZKTeco).
5.  Save the document.

### Step 4: Configure the Physical Device

On your actual biometric hardware, navigate to the communication or network settings. You must configure the device to send data to the server address and port provided by the `status` command in Step 2.

-   **For EBKN Devices:** Point the device to the full path, e.g., `http://your_public_ip:8998/ebkn`.
-   **For ZKTeco Devices:** Point the device to the base address, e.g., `your_public_ip:8998`. The device will automatically call paths like `/iclock/cdata`.

## Supported Devices & Status

### EBKN

-   **Status:** ✅ **Stable & Recommended**
-   **Features:**
    -   Real-time attendance sync.
    -   Full command processing (Enroll, Delete, Get Info).
    -   Automatic user synchronization from ERP to device.

### ZKTeco

-   **Status:** 🚧 **In Development & Testing**
-   **Features:**
    -   Handles initial device handshake.
    -   Processes incoming attendance logs.
    -   Receives user enrollment data (fingerprints).
    -   Can send commands to devices.
-   **Important:** This integration requires ZKTeco devices that support the **ADMS (Push SDK) protocol**. This feature allows the device to "push" data to a server in real-time. If your device menu does not have an ADMS or "Cloud Server" setting, it may not be compatible out-of-the-box. Assistance may be available to enable this feature on certain models.

## Support and Contribution

This project is actively maintained. If you require assistance with setup, need to integrate a different brand of device, or would like to sponsor the development of new features, please feel free to get in touch.

-   **Contact:** [t.me/khaledbinamir](https://t.me/khaledbinamir)