# Biometric Integration - Complete Setup and Usage Guide

## Overview

The Biometric Integration app provides seamless integration between ERPNext/Frappe and popular biometric attendance devices. It supports real-time data synchronization, user enrollment management, and command processing for multiple device brands.

## Supported Devices

| Brand | Status | Protocol | Features |
|-------|--------|----------|----------|
| **EBKN** | ✅ Stable | HTTP Push | Real-time attendance, full command processing, user sync |
| **ZKTeco** | 🚧 Development | ADMS Push | Attendance logs, user enrollment, command processing |
| **Suprema** | 📋 Planned | - | - |
| **Hikvision** | 🚧 Development | HTTP API | Attendance sync, manual/API-based |

## Architecture

The app uses a clever NGINX reverse proxy setup to avoid running a separate service:

```
Biometric Device → NGINX Proxy (Port 8998) → Frappe API → Brand Processor → Database
```

## Installation

### 1. Install the App

```bash
# Navigate to your bench directory
cd /path/to/your/frappe-bench

# Get the app from GitHub
bench get-app https://github.com/KhaledBinAmir/biometric_integration

# Install on your site
bench --site your_site_name install-app biometric_integration

# Run migrations
bench --site your_site_name migrate
```

### 2. Enable the Biometric Listener

Choose an unused port (e.g., 8998, 8008) and enable the listener:

```bash
# Enable listener on port 8998
bench --site your_site_name biometric-listener enable --port 8998

# Check status
bench --site your_site_name biometric-listener status
```

**Expected Output:**
```json
{
  "your_site_name": {
    "status": "enabled",
    "listening_ip": "0.0.0.0 (All Interfaces)",
    "port": 8998,
    "paths": {
      "ebkn": "http://your_public_ip:8998/ebkn",
      "suprema": "http://your_public_ip:8998",
      "zkteco": "http://your_public_ip:8998",
      "hikvision": "http://your_public_ip:8998"
    }
  }
}
```

### 3. Configure Firewall

Ensure your chosen port is open in the firewall:

```bash
# Ubuntu/Debian
sudo ufw allow 8998

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=8998/tcp
sudo firewall-cmd --reload

# Or using iptables
sudo iptables -A INPUT -p tcp --dport 8998 -j ACCEPT
```

## Configuration

### Biometric Integration Settings

1. Go to **Biometric Integration > Biometric Integration Settings**
2. Configure:
   - **Maximum Attempts for Commands**: How many times to retry failed commands (default: 3)
   - **Force Close After**: Days after which to auto-close stuck commands (default: 7)

### Device Configuration

#### 1. Create Biometric Device Records

For each physical device:

1. Go to **Biometric Integration > Biometric Device**
2. Create new record:
   - **Device Name**: Descriptive name (e.g., "Main Entrance ZKTeco")
   - **Serial No**: Must match device serial number exactly
   - **Brand**: Select from EBKN, ZKTeco, Suprema, Hikvision
   - **Disabled**: Uncheck to enable the device

#### 2. Configure Users

Users can be configured in two ways:

**Option A: Assign Specific Users to Devices**
1. Go to **Biometric Integration > Biometric Device User**
2. Create user records with biometric data
3. In the **Devices** child table, assign users to specific devices

**Option B: Global User Access**
1. In Biometric Device User record, check **Allow User in All Devices**
2. Upload enrollment data for each supported brand
3. Users will be automatically enrolled on all active devices

#### 3. Upload Enrollment Data

For each user and brand combination:

1. Capture fingerprint/template on the device
2. Export the enrollment data (usually as .dat or binary file)
3. In Biometric Device User record, upload to the appropriate field:
   - **ZKTeco**: `zkteco_enroll_data`
   - **EBKN**: `ebkn_enroll_data`
   - **Suprema**: `suprema_enroll_data`

## Device-Specific Setup

### EBKN Devices

1. **Device Configuration**:
   - Server Address: `http://your_server_ip:8998/ebkn`
   - Ensure device supports HTTP push protocol

2. **Supported Operations**:
   - Real-time attendance logging
   - User enrollment/deletion
   - Device status monitoring

### ZKTeco Devices (ADMS Push Protocol)

1. **Device Requirements**:
   - Must support ADMS (Push SDK) protocol
   - Check device menu for "ADMS" or "Cloud Server" settings

2. **Device Configuration**:
   - Server Address: `http://your_server_ip:8998`
   - The device will automatically use `/iclock/cdata` endpoint

3. **Supported Operations**:
   - Attendance data push
   - User enrollment data reception
   - Command responses

### Hikvision Devices

1. **Configuration**:
   - Server Address: `http://your_server_ip:8998`
   - API credentials in device settings

2. **Manual Sync**:
   ```bash
   # Sync specific device
   curl -X POST http://your_site/api/method/biometric_integration.api.sync_hikvision_device \
     -H "Authorization: token your_token" \
     -H "Content-Type: application/json" \
     -d '{"device_serial": "DEVICE123", "start_time": "2024-01-01 00:00:00"}'

   # Sync all devices
   curl -X POST http://your_site/api/method/biometric_integration.api.sync_all_hikvision_devices \
     -H "Authorization: token your_token"
   ```

## Usage and Operations

### Monitoring Commands

1. Go to **Biometric Integration > Biometric Device Command**
2. View command queue and status:
   - **Pending**: Waiting to be sent to device
   - **Success**: Successfully executed
   - **Failed**: Failed after max attempts
   - **Closed**: Manually or automatically closed

### Manual Command Creation

Commands are automatically created when:
- New users are assigned to devices
- Enrollment data is updated
- Users are removed from devices

### Real-time Attendance Processing

Attendance data flows automatically:
1. Device sends attendance log to configured endpoint
2. App processes and creates Employee Checkin records
3. Data appears in ERPNext attendance reports

### Troubleshooting

#### Listener Issues

```bash
# Check listener status
bench --site your_site biometric-listener status

# Restart listener
bench --site your_site biometric-listener disable
bench --site your_site biometric-listener enable --port 8998

# Check NGINX status
sudo systemctl status nginx
sudo nginx -t  # Test configuration
```

#### Device Connection Issues

1. **Verify Network Connectivity**:
   ```bash
   # Test connection from device network
   curl http://your_server_ip:8998/ebkn
   ```

2. **Check Device Logs**:
   - Review device network logs
   - Check ERPNext error logs for API failures

3. **Validate Configuration**:
   - Ensure device serial numbers match exactly
   - Verify port is open and accessible
   - Check NGINX configuration syntax

#### Data Sync Issues

1. **Check Command Status**:
   - Review Biometric Device Command records
   - Look for failed commands and error messages

2. **Validate User Data**:
   - Ensure enrollment data is uploaded
   - Check user-device assignments

3. **Test API Endpoints**:
   ```bash
   # Test API accessibility
   curl http://your_site/api/method/biometric_integration.api.handle_request
   ```

## Testing

### Automated Tests

Run the provided test script:

```bash
cd /path/to/your/frappe-bench
python test_biometric_integration.py
```

### Manual Testing

1. **Test Listener**:
   ```bash
   # Should return connection info
   curl http://localhost:8998/
   ```

2. **Test API Endpoint**:
   ```bash
   # Should return 404 (no handler for root)
   curl http://your_site/api/method/biometric_integration.api.handle_request
   ```

3. **Test Device Simulation**:
   ```bash
   # Simulate EBKN device ping
   curl -X POST http://localhost:8998/ebkn \
     -H "Content-Type: application/octet-stream" \
     -d "test_data"
   ```

## CLI Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `biometric-listener enable --port PORT` | Enable listener on specified port | `bench --site site biometric-listener enable --port 8998` |
| `biometric-listener disable` | Disable listener | `bench --site site biometric-listener disable` |
| `biometric-listener status` | Check listener status | `bench --site site biometric-listener status` |

## API Endpoints

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/api/method/biometric_integration.api.handle_request` | Any | Main device communication endpoint | Device-specific |
| `/api/method/biometric_integration.api.sync_hikvision_device` | POST | Manual Hikvision device sync | `device_serial`, `start_time`, `end_time` |
| `/api/method/biometric_integration.api.sync_all_hikvision_devices` | POST | Sync all Hikvision devices | None |

## Data Flow

### Attendance Processing
1. Device detects attendance event
2. Device sends HTTP request to configured endpoint
3. NGINX proxies request to Frappe API
4. Brand-specific processor handles the data
5. Attendance record created in ERPNext
6. Employee Checkin record generated

### Command Processing
1. User/Device changes trigger command creation
2. Commands queued in Biometric Device Command doctype
3. Device polls or receives push notification
4. Device executes command and reports status
5. Command status updated in ERPNext

## Security Considerations

1. **Network Security**:
   - Use HTTPS in production
   - Restrict port access to device networks only
   - Implement IP whitelisting if possible

2. **Data Security**:
   - Enrollment data stored as private files
   - Access controlled by Frappe permissions
   - Regular backup of biometric data

3. **API Security**:
   - Guest access allowed for device communication
   - Rate limiting recommended
   - Monitor for suspicious activity

## Maintenance

### Regular Tasks

1. **Monitor Command Queue**:
   - Check for stuck commands
   - Review failed command logs

2. **Clean Old Data**:
   - Archive old attendance records
   - Remove obsolete commands

3. **Update Device Firmware**:
   - Keep devices updated
   - Test compatibility after updates

### Backup Strategy

1. **Database Backup**: Standard ERPNext backup includes all biometric data
2. **File Backup**: Enrollment data files stored separately
3. **Configuration Backup**: Document device configurations

## Support

For issues and support:
- **Documentation**: This guide and app README
- **Logs**: Check ERPNext error logs and device logs
- **Community**: GitHub issues for bug reports
- **Contact**: Developer contact information in README

## Advanced Configuration

### Custom Processors

To add support for new device brands:

1. Create processor in `services/` directory
2. Implement handler function with standard signature
3. Add routing logic in `api.py`
4. Update CLI status output

### Custom Commands

Extend command types by:
1. Adding new command types to Biometric Device Command doctype
2. Implementing processing logic in brand processors
3. Updating device communication protocols

This comprehensive setup ensures reliable biometric device integration with your ERPNext system.</content>
<parameter name="filePath">/Users/mac/ERPNext/kimzon/apps/biometric_integration/BIOMETRIC_INTEGRATION_GUIDE.md