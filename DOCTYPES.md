# Biometric Integration Doctypes

## Overview

The biometric integration app uses several doctypes to manage devices, users, commands, and settings. This document provides detailed information about each doctype, its fields, and configuration options.

## 1. Biometric Device

**Purpose**: Represents physical biometric devices (fingerprint scanners, etc.) connected to the system.

**Key Fields**:

### Basic Information
- **Serial** (Data, Required, Unique): Device serial number - must match the physical device exactly
- **Device Name** (Data, Required): Human-readable name for the device
- **Brand** (Select, Required): Device manufacturer
  - Options: ZKTeco, Suprema, EBKN, Hikvision

### Brand-Specific Fields
- **Device ID** (Int, Required for EBKN): Unique identifier for EBKN devices
- **Device IP** (Data, Required for Suprema/Hikvision): Network address of the device
- **Device Port** (Data, Required for Suprema): Network port for Suprema devices
- **Username/Password** (Data/Password, Required for Hikvision): API credentials for Hikvision devices
- **Sync Start/End Date Time** (Datetime, Required for Hikvision): Time range for attendance sync

### Status and Control
- **Disabled** (Check): When checked, device is inactive and won't receive commands
- **Push Protocol Configured** (Check): Indicates if device supports real-time push protocols
- **Has Pending Command** (Check, Read-only): System flag indicating queued commands
- **Disable Syncing Employees** (Check): Skip employee synchronization for this device
- **Maximum Sync Attempt** (Int, Default: 3): Maximum retry attempts for sync operations

### Sync Tracking
- **Last Synced Time** (Datetime): Timestamp of last successful sync
- **Last Synced ID** (Int): ID of last processed record

### Organizational
- **Project** (Link): Associated ERPNext Project
- **Branch** (Link): Associated ERPNext Branch

**Naming Rule**: By field `serial` (autoname)

**Permissions**: System Manager (full access)

**Links**: Connected to Biometric Device Command records

## 2. Biometric Device Command

**Purpose**: Manages commands sent to biometric devices (enroll users, delete users, etc.).

**Key Fields**:

### Relationships
- **Biometric Device** (Link, Required): Target device for the command
- **Biometric Device User** (Link): User affected by the command
- **Employee** (Link, Fetched): Linked ERPNext Employee record
- **Employee Name** (Data, Fetched): Employee's full name

### Command Details
- **Brand** (Data, Fetched): Device brand (from linked device)
- **Command Type** (Select, Required):
  - Get Enroll Data: Retrieve user's biometric template
  - Enroll User: Add/update user on device
  - Delete User: Remove user from device
- **Status** (Select, Default: Pending):
  - Pending: Queued for execution
  - Processing: Currently being executed
  - Closed: Manually closed
  - Failed: Failed after max attempts
  - Success: Successfully completed

### Timing and Attempts
- **Initiated On** (Datetime, Default: Now): When command was created
- **Closed On** (Datetime): When command was completed/failed
- **No of Attempts** (Int, Read-only): Number of execution attempts

### Response Tracking
- **Device Response** (Code, Read-only): Raw response from device

**Naming Rule**: Expression `{#}` (sequential numbering)

**Permissions**: System Manager (full access)

**Grid Settings**: 50 items per page

## 3. Biometric Device User

**Purpose**: Manages users across biometric devices, including enrollment data storage.

**Key Fields**:

### Basic Information
- **User ID** (Data, Required, Unique): User's identifier (PIN, employee ID, etc.)
- **Employee** (Link, Unique): Linked ERPNext Employee record
- **Employee Name** (Data, Fetched): Employee's full name

### Device Access Control
- **Allow User in All Devices** (Check): When checked, user can access all active devices
- **Allowed Devices** (Table): Child table specifying allowed devices (when not allowing all)
  - **Biometric Device** (Link): Specific device
  - **Brand** (Data, Fetched): Device brand
  - **Enroll Data Source** (Check, Read-only): Indicates which device provided the enrollment data

### Enrollment Data
- **ZKTeco Enroll Data** (Attach): Biometric template file for ZKTeco devices
- **EBKN Enroll Data** (Attach): Biometric template file for EBKN devices
- **Suprema Enroll Data** (Attach): Biometric template file for Suprema devices
- **Hikvision Enroll Data** (Attach): Biometric template file for Hikvision devices

**Naming Rule**: By field `user_id` (autoname)

**Permissions**: System Manager (full access)

**Search Fields**: user_id, employee

**Title Field**: employee_name

## 4. Biometric Integration Settings

**Purpose**: Global settings for the biometric integration system.

**Type**: Single doctype (only one record exists)

**Key Fields**:

### Command Management
- **Force Close Incomplete Commands After (Days)** (Int, Default: 30): Auto-close stuck commands
- **Maximum No of Attempts for Commands** (Int, Default: 3): Global retry limit

### Employee Mapping
- **Device ID Field** (Data, Default: attendance_device_id): Employee field used for device ID mapping
- **Do Not Skip Unknown Employee Checkin** (Check): Create checkins even for unknown employee IDs

### Listener Information (Read-only)
- **Listener Status**: Current status of the NGINX listener
- **Listener Port**: Configured listening port
- **ZKTeco Webhook URL**: Full URL for ZKTeco devices
- **EBKN Webhook URL**: Full URL for EBKN devices
- **Hikvision Webhook URL**: Full URL for Hikvision devices
- **Suprema Webhook URL**: Full URL for Suprema devices

**Permissions**: System Manager (full access)

## 5. Biometric Device User Detail

**Purpose**: Child table for Biometric Device User, specifying device-specific access.

**Type**: Table doctype (child table)

**Key Fields**:
- **Biometric Device** (Link, Required): Specific device the user can access
- **Brand** (Data, Fetched): Device brand
- **Enroll Data Source** (Check, Read-only): Marks the device that provided enrollment data

**Editable Grid**: Yes (can be edited inline)

## Configuration Workflows

### Setting Up a New Device

1. **Create Biometric Device Record**:
   ```
   Serial: ABC123
   Device Name: Main Entrance Scanner
   Brand: ZKTeco
   Push Protocol Configured: Yes
   ```

2. **Configure Device Network** (if applicable):
   ```
   Device IP: 192.168.1.100
   Device Port: 4370
   ```

3. **Point Device to ERPNext**:
   - Server Address: `http://your-server-ip:8998`
   - The device will automatically use brand-specific paths

### Adding a User

**Option 1: Global Access**
1. Create Biometric Device User:
   ```
   User ID: 001
   Employee: EMP001
   Allow User in All Devices: Yes
   ```
2. Upload enrollment data for each brand used

**Option 2: Specific Devices**
1. Create Biometric Device User:
   ```
   User ID: 001
   Employee: EMP001
   Allow User in All Devices: No
   ```
2. Add devices in the "Allowed Devices" table
3. Upload enrollment data

### Monitoring Commands

1. **View Command Queue**: Go to Biometric Device Command list
2. **Filter by Status**: Use filters to see pending/failed commands
3. **Check Device Response**: Review raw responses for troubleshooting

### System Settings

1. **Access Settings**: Biometric Integration > Biometric Integration Settings
2. **Configure Timeouts**:
   ```
   Force Close After: 30 days
   Maximum Attempts: 3
   ```
3. **Employee Mapping**:
   ```
   Device ID Field: attendance_device_id
   ```

## Data Relationships

```
Biometric Device (1) ──── (Many) Biometric Device Command
    │
    └─── (Many) Biometric Device User Detail
                    │
                    └─── (1) Biometric Device User
                                   │
                                   └─── (1) Employee
```

## Permissions

All doctypes require **System Manager** role for full access. The app is designed for administrative use only.

## Automation

The system automatically:
- Creates enrollment commands when users are added to devices
- Creates deletion commands when users are removed
- Syncs enrollment data across compatible devices
- Closes stuck commands after configured timeouts
- Tracks sync status and attempt counts

## Best Practices

1. **Device Serial Numbers**: Must exactly match physical device configuration
2. **User IDs**: Should be consistent across devices for the same user
3. **Enrollment Data**: Keep backups of biometric templates
4. **Command Monitoring**: Regularly review failed commands
5. **Settings Review**: Periodically check and update global settings

This doctype structure provides a comprehensive framework for managing biometric device integration with ERPNext.</content>
<parameter name="filePath">/Users/mac/ERPNext/kimzon/apps/biometric_integration/DOCTYPES.md