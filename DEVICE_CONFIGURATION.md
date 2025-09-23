# Device-Specific Configuration Guide

## Overview

This guide provides detailed configuration instructions for each supported biometric device brand. Each brand has unique requirements and setup procedures.

## EBKN Devices

### Supported Models
- All EBKN biometric devices with HTTP push capability

### ERPNext Configuration

1. **Create Device Record**:
   ```
   Serial: [Device Serial Number]
   Device Name: [Descriptive Name]
   Brand: EBKN
   Device ID: [Unique numeric ID, e.g., 1, 2, 3]
   Push Protocol Configured: Yes
   ```

2. **Device Network Settings**:
   - The device will push data to the configured listener port
   - No additional IP/port configuration required in ERPNext

### Device Configuration

1. **Access Device Web Interface**:
   - Connect to device using browser or management software
   - Default IP: Usually 192.168.1.201 or similar

2. **Configure Push Settings**:
   ```
   Server Address: http://[YOUR_SERVER_IP]:[LISTENER_PORT]/ebkn
   Push Protocol: Enable
   Push Interval: Real-time (if available)
   ```

3. **Authentication** (if required):
   - Some EBKN models require username/password
   - Configure in device settings if needed

### Data Flow

- **Attendance**: Device pushes attendance logs in real-time
- **Commands**: ERPNext sends enroll/delete commands via HTTP responses
- **Protocol**: Custom EBKN protocol with header-based communication

### Troubleshooting

- **No Data Received**: Check device push settings and network connectivity
- **Command Failures**: Verify Device ID matches exactly
- **Connection Issues**: Ensure port 8998 is accessible from device network

## ZKTeco Devices (ADMS Push Protocol)

### Requirements
- **Critical**: Device MUST support ADMS (Push SDK) protocol
- Check device menu for "ADMS" or "Cloud Server" settings
- Not all ZKTeco models support this feature

### ERPNext Configuration

1. **Create Device Record**:
   ```
   Serial: [Device Serial Number - exact match required]
   Device Name: [Descriptive Name]
   Brand: ZKTeco
   Push Protocol Configured: Yes
   ```

2. **No Additional Network Config**: Push protocol handles communication

### Device Configuration

1. **Enable ADMS Push**:
   - Access device menu → Communication → Cloud Server/ADMS
   - Enable push protocol
   - Set server address: `http://[YOUR_SERVER_IP]:[LISTENER_PORT]`

2. **Push Settings**:
   ```
   Server Address: http://[YOUR_SERVER_IP]:[LISTENER_PORT]
   Port: [LISTENER_PORT, e.g., 8998]
   Protocol: HTTP Push
   Push Interval: Real-time
   ```

3. **Advanced Settings** (if available):
   ```
   Push Attendance: Yes
   Push User Data: Yes
   Push Commands: Yes
   ```

### Supported Operations

- ✅ **Real-time Attendance**: Automatic push when attendance recorded
- ✅ **User Enrollment**: Receive fingerprint templates from device
- ✅ **Command Processing**: Execute enroll/delete commands
- ✅ **Device Status**: Monitor device connectivity

### Data Flow

1. **Attendance Push**: Device sends `/iclock/cdata` requests with attendance data
2. **User Data Push**: Device sends enrollment data when users are enrolled
3. **Command Response**: Device acknowledges command execution
4. **Heartbeat**: Periodic connectivity checks

### Troubleshooting

- **ADMS Not Available**: Device model doesn't support push protocol
- **No Push Data**: Check ADMS settings and server connectivity
- **Enrollment Data Missing**: Ensure device is configured to push user data
- **Commands Not Executing**: Verify device serial number matches exactly

## Suprema Devices

### Status
🚧 **Planned** - Core framework ready, device-specific implementation pending

### Expected Configuration

1. **ERPNext Setup**:
   ```
   Serial: [Device Serial]
   Device Name: [Name]
   Brand: Suprema
   Device IP: [Device IP Address]
   Device Port: [Device Port, usually 4001]
   Push Protocol Configured: Yes
   ```

2. **Device Setup** (Expected):
   ```
   Server Address: http://[SERVER_IP]:[PORT]
   Push Protocol: Enable
   Real-time Sync: Yes
   ```

### Current Status
- Framework integrated
- Device-specific processor needs implementation
- Contact developer for timeline

## Hikvision Devices

### Configuration Method
- **Primary**: API-based polling (not push)
- **Secondary**: Webhook support (limited models)

### ERPNext Configuration

1. **Create Device Record**:
   ```
   Serial: [Device Serial]
   Device Name: [Name]
   Brand: Hikvision
   Device IP: [Device IP]
   Username: [API Username]
   Password: [API Password]
   Sync Start Date Time: [Start date for sync]
   Sync End Date Time: [End date for sync]
   ```

2. **API Credentials**:
   - Use device web interface admin credentials
   - Or create dedicated API user

### Device Configuration

1. **Enable API Access**:
   - Access device web interface
   - Enable ISAPI (HTTP API)
   - Configure API authentication

2. **Network Settings**:
   ```
   HTTP Port: Usually 80 or 8080
   HTTPS: Optional, configure if needed
   API Access: Enable
   ```

### Data Synchronization

**Manual Sync**:
```bash
# Sync specific device
curl -X POST http://your_site/api/method/biometric_integration.api.sync_hikvision_device \
  -H "Authorization: token your_token" \
  -H "Content-Type: application/json" \
  -d '{"device_serial": "DEVICE123", "start_time": "2024-01-01 00:00:00"}'
```

**Scheduled Sync**:
```bash
# Sync all Hikvision devices
curl -X POST http://your_site/api/method/biometric_integration.api.sync_all_hikvision_devices \
  -H "Authorization: token your_token"
```

### Supported Operations

- ✅ **Attendance Sync**: Pull attendance data via API
- ✅ **Manual Control**: API-based device management
- ❌ **Real-time Push**: Not supported (polling-based)
- ❌ **Command Push**: Limited support

## Generic Device Setup Steps

### 1. Pre-Configuration Checklist

- [ ] Device serial number noted
- [ ] Device IP address and port (if applicable)
- [ ] API credentials (if applicable)
- [ ] Network connectivity to ERPNext server
- [ ] Firewall allows access to listener port

### 2. ERPNext Device Creation

1. Navigate to **Biometric Integration > Biometric Device**
2. Click **New**
3. Fill required fields based on brand
4. Save record

### 3. Device Network Configuration

**For Push-Protocol Devices (EBKN, ZKTeco)**:
```
Server Address: http://[ERPNext_IP]:[LISTENER_PORT]/[brand_path]
Protocol: HTTP Push
Real-time: Enable
```

**For API-Based Devices (Hikvision)**:
```
IP Address: [Device_IP]
Port: [Device_Port]
API Username: [Username]
API Password: [Password]
```

### 4. Test Connectivity

1. **Check Listener Status**:
   ```bash
   bench --site your_site biometric-listener status
   ```

2. **Test Device Connection**:
   - Ping device from server
   - Check device logs for connection attempts
   - Monitor ERPNext logs for incoming requests

3. **Verify Data Flow**:
   - Trigger test attendance event
   - Check if data appears in ERPNext
   - Review command execution

### 5. User Enrollment

1. **Create Biometric Device User** records
2. **Upload enrollment data** for each brand
3. **Assign users to devices** or enable global access
4. **Monitor enrollment commands** in command queue

## Device Compatibility Matrix

| Feature | EBKN | ZKTeco | Suprema | Hikvision |
|---------|------|--------|---------|-----------|
| Real-time Push | ✅ | ✅ | ❌ | ❌ |
| Attendance Sync | ✅ | ✅ | ❌ | ✅ |
| User Enrollment | ✅ | ✅ | ❌ | ❌ |
| Command Processing | ✅ | ✅ | ❌ | ❌ |
| API Integration | ❌ | ❌ | ❌ | ✅ |
| Push Protocol | Custom | ADMS | - | Limited |

## Network Requirements

### Port Access
- **Listener Port** (e.g., 8998): Must be accessible from device networks
- **Device Ports**: Usually 80, 4370, 4001, etc. (server to device)

### Firewall Rules
```bash
# Allow device access to listener
sudo ufw allow from [DEVICE_NETWORK] to any port [LISTENER_PORT]

# Allow server access to device APIs (if needed)
sudo ufw allow from [SERVER_IP] to [DEVICE_IP] port [DEVICE_PORT]
```

### Network Security
- Use VPN for remote devices
- Implement IP whitelisting
- Monitor access logs
- Regular security updates

## Troubleshooting Common Issues

### No Data Received

1. **Check Network Connectivity**:
   ```bash
   ping [DEVICE_IP]
   telnet [DEVICE_IP] [DEVICE_PORT]
   ```

2. **Verify Configuration**:
   - Device server address matches ERPNext URL
   - Port numbers correct
   - Push protocol enabled

3. **Check Logs**:
   - Device system logs
   - ERPNext error logs
   - NGINX access logs

### Commands Not Executing

1. **Verify Serial Numbers**: Must match exactly
2. **Check Device Status**: Ensure device is enabled
3. **Review Command Queue**: Check for errors in Biometric Device Command
4. **Test API Endpoint**: Manual API calls to verify connectivity

### Enrollment Data Issues

1. **File Format**: Ensure correct biometric template format
2. **File Permissions**: Check file access in ERPNext
3. **Brand Compatibility**: Verify enrollment data matches device brand
4. **Data Integrity**: Validate uploaded files are not corrupted

### Performance Issues

1. **Command Queue**: Monitor pending commands
2. **Device Load**: Check device capacity and load
3. **Network Latency**: Measure round-trip times
4. **Database Performance**: Monitor ERPNext database queries

## Advanced Configuration

### Custom Branding

To add support for new device brands:

1. **Create Processor**: Add `services/[brand]_processor.py`
2. **Update API Router**: Modify `api.py` routing logic
3. **Add Brand Support**: Update brand selection options
4. **Test Integration**: Comprehensive testing required

### High Availability

For production deployments:

1. **Load Balancing**: Distribute requests across multiple servers
2. **Database Replication**: Ensure data consistency
3. **Backup Systems**: Redundant biometric devices
4. **Monitoring**: Comprehensive logging and alerting

This guide provides the foundation for configuring any supported biometric device with the ERPNext integration system.</content>
<parameter name="filePath">/Users/mac/ERPNext/kimzon/apps/biometric_integration/DEVICE_CONFIGURATION.md