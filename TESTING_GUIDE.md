# Testing Guide for Biometric Integration

## Overview

This guide covers testing procedures for the biometric integration app, including automated tests, manual testing, and troubleshooting.

## Automated Testing

### Test Script Execution

The app includes a comprehensive test script that validates core functionality:

```bash
cd /path/to/your/frappe-bench
python test_biometric_integration.py
```

**What it tests**:
- ✅ Module imports (core doctypes and functions)
- ✅ User creation functionality
- ✅ Command addition logic
- ✅ CLI utilities import
- ✅ API module accessibility

**Expected Output**:
```
Testing Biometric Integration App...

✓ Core modules imported successfully
✓ User creation function works: USER001
✓ Command addition function works
✓ Status logic works: enabled/disabled
✓ API module imported successfully

All basic tests passed! The biometric_integration app is functional.
```

### Running Tests in Frappe Environment

```bash
# Run specific app tests
bench --site your_site run-tests --app biometric_integration

# Run all tests
bench --site your_site run-tests
```

## Manual Testing Procedures

### 1. Listener Testing

#### Test Listener Enable/Disable

```bash
# Enable listener
bench --site your_site biometric-listener enable --port 8998

# Check status
bench --site your_site biometric-listener status

# Expected: Status shows "enabled" with correct port and URLs

# Disable listener
bench --site your_site biometric-listener disable

# Check status again
bench --site your_site biometric-listener status

# Expected: Status shows "disabled"
```

#### Test Port Accessibility

```bash
# Test if port is listening
netstat -tlnp | grep :8998
# or
ss -tlnp | grep :8998

# Test HTTP endpoint
curl http://localhost:8998/
# Expected: 404 (no handler for root path)

# Test EBKN endpoint
curl -X POST http://localhost:8998/ebkn \
  -H "Content-Type: application/octet-stream" \
  -d "test_data"
# Expected: Should not crash, check logs for processing
```

### 2. Device Testing

#### Create Test Device

1. **In ERPNext Desk**:
   - Go to Biometric Integration > Biometric Device
   - Create new record:
     ```
     Serial: TEST001
     Device Name: Test Device
     Brand: ZKTeco
     Push Protocol Configured: Yes
     ```

2. **Verify Device Creation**:
   - Record saves successfully
   - No validation errors

#### Test User Management

1. **Create Test User**:
   - Go to Biometric Integration > Biometric Device User
   - Create record:
     ```
     User ID: TESTUSER001
     Employee: [Select or create test employee]
     Allow User in All Devices: Yes
     ```

2. **Upload Test Enrollment Data**:
   - Upload a dummy file to ZKTeco Enroll Data field
   - Save record

3. **Verify Command Creation**:
   - Check Biometric Device Command list
   - Should see "Enroll User" command for TESTUSER001

### 3. API Testing

#### Test Main API Endpoint

```bash
# Test API accessibility
curl http://your_site/api/method/biometric_integration.api.handle_request

# Expected: Should return valid response or authentication challenge
```

#### Test Hikvision Sync (if applicable)

```bash
# Get API token first
TOKEN=$(curl -X POST http://your_site/api/method/login \
  -H "Content-Type: application/json" \
  -d '{"usr": "administrator", "pwd": "your_password"}' | jq -r '.message.api_key')

# Test Hikvision sync
curl -X POST http://your_site/api/method/biometric_integration.api.sync_hikvision_device \
  -H "Authorization: token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_serial": "TEST001"}'
```

### 4. Data Flow Testing

#### Simulate Device Communication

1. **EBKN Device Simulation**:
   ```bash
   # Simulate attendance data push
   curl -X POST http://localhost:8998/ebkn \
     -H "request_code: attendance" \
     -H "dev_id: TEST001" \
     -H "Content-Type: application/octet-stream" \
     -d "simulated_attendance_data"
   ```

2. **ZKTeco Device Simulation**:
   ```bash
   # Simulate ADMS push
   curl -X POST http://localhost:8998/iclock/cdata \
     -H "Content-Type: application/xml" \
     -d "<PushData><Attendance><UserID>TESTUSER001</UserID><Time>2024-01-01 09:00:00</Time></Attendance></PushData>"
   ```

3. **Check Data Processing**:
   - Monitor ERPNext logs
   - Check Employee Checkin records
   - Verify command status updates

## Integration Testing

### End-to-End Device Testing

#### With Real Device (Recommended)

1. **Setup Test Device**:
   - Configure physical device to point to test server
   - Use test port (e.g., 8999) to avoid production interference

2. **Test Attendance Flow**:
   - Record attendance on device
   - Verify data appears in ERPNext within seconds
   - Check Employee Checkin creation

3. **Test Command Flow**:
   - Create user in ERPNext with enrollment data
   - Verify device receives enrollment command
   - Check user appears on device

#### With Virtual Device (Development)

1. **Use Device Simulator**:
   - Some brands provide SDK simulators
   - Create custom scripts to simulate device behavior

2. **Mock API Responses**:
   ```python
   # Example simulation script
   import requests
   import time

   SERVER_URL = "http://localhost:8998"

   # Simulate attendance
   def send_attendance():
       data = {
           "user_id": "TEST001",
           "timestamp": "2024-01-01 09:00:00",
           "device_id": "TESTDEVICE"
       }
       response = requests.post(f"{SERVER_URL}/ebkn", json=data)
       print(f"Attendance response: {response.status_code}")

   # Simulate periodic pings
   while True:
       send_attendance()
       time.sleep(30)  # Every 30 seconds
   ```

## Performance Testing

### Load Testing

1. **Multiple Device Simulation**:
   ```bash
   # Run multiple concurrent requests
   for i in {1..10}; do
     curl -X POST http://localhost:8998/ebkn \
       -H "dev_id: DEVICE$i" \
       -d "test_data_$i" &
   done
   ```

2. **Monitor System Resources**:
   ```bash
   # Check CPU/memory usage
   top -p $(pgrep -f frappe)

   # Monitor NGINX
   sudo nginx -s reload
   sudo systemctl status nginx
   ```

### Stress Testing

1. **High-Frequency Requests**:
   - Simulate 100+ attendance events per minute
   - Monitor response times
   - Check for dropped requests

2. **Large Payloads**:
   - Test with maximum enrollment data sizes
   - Verify file upload limits
   - Check memory usage

## Troubleshooting Tests

### Log Analysis

1. **Check ERPNext Logs**:
   ```bash
   # View recent logs
   bench --site your_site doctor

   # Check error logs
   tail -f sites/your_site/logs/error.log
   ```

2. **Check NGINX Logs**:
   ```bash
   sudo tail -f /var/log/nginx/access.log
   sudo tail -f /var/log/nginx/error.log
   ```

3. **Check Bench Logs**:
   ```bash
   tail -f logs/bench.log
   ```

### Common Test Failures

#### Listener Not Starting
```
Error: Port 8998 is already in use
```
**Solution**: Use different port or free existing port
```bash
sudo netstat -tlnp | grep :8998
sudo kill -9 [PID]
```

#### NGINX Configuration Error
```
Error reloading NGINX: [error]
```
**Solution**: Check NGINX syntax
```bash
sudo nginx -t
sudo nginx -s reload
```

#### API Authentication Issues
```
403 Forbidden
```
**Solution**: Check API key and permissions
```bash
# Test with proper authentication
curl -X POST http://your_site/api/method/biometric_integration.api.handle_request \
  -H "Authorization: token your_api_key"
```

#### Database Connection Issues
```
Connection refused
```
**Solution**: Check Frappe site status
```bash
bench --site your_site status
bench --site your_site restart
```

## Test Data Management

### Creating Test Data

```python
# Python script to create test data
import frappe

def create_test_data():
    # Create test device
    device = frappe.get_doc({
        "doctype": "Biometric Device",
        "serial": "TEST001",
        "device_name": "Test Device",
        "brand": "ZKTeco",
        "push_protocol_configured": 1
    })
    device.insert()

    # Create test user
    user = frappe.get_doc({
        "doctype": "Biometric Device User",
        "user_id": "TESTUSER001",
        "allow_user_in_all_devices": 1
    })
    user.insert()

    frappe.db.commit()
    print("Test data created successfully")

if __name__ == "__main__":
    frappe.init(site="your_site")
    frappe.connect()
    create_test_data()
    frappe.destroy()
```

### Cleaning Test Data

```python
# Clean up test data
import frappe

def cleanup_test_data():
    # Delete test records
    frappe.db.delete("Biometric Device Command", {"biometric_device": "TEST001"})
    frappe.db.delete("Biometric Device User", {"user_id": "TESTUSER001"})
    frappe.db.delete("Biometric Device", {"serial": "TEST001"})
    frappe.db.commit()
    print("Test data cleaned up")

if __name__ == "__main__":
    frappe.init(site="your_site")
    frappe.connect()
    cleanup_test_data()
    frappe.destroy()
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Biometric Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Setup Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install frappe-bench
        bench init frappe-bench --skip-assets
        cd frappe-bench
        bench get-app biometric_integration
        bench new-site test.local
        bench --site test.local install-app biometric_integration

    - name: Run tests
      run: |
        cd frappe-bench
        python test_biometric_integration.py
```

## Test Coverage Areas

- ✅ **Unit Tests**: Individual function testing
- ✅ **Integration Tests**: Component interaction
- ✅ **API Tests**: Endpoint validation
- ✅ **CLI Tests**: Command-line interface
- ✅ **Performance Tests**: Load and stress testing
- ✅ **Security Tests**: Authentication and authorization
- ✅ **Compatibility Tests**: Multi-device scenarios

## Best Practices

1. **Test Isolation**: Use separate test site/database
2. **Data Cleanup**: Always clean up test data
3. **Version Control**: Keep test scripts in version control
4. **Documentation**: Document test procedures and expected results
5. **Automation**: Automate repetitive tests
6. **Monitoring**: Monitor test results and failures
7. **Regression Testing**: Run full test suite before releases

This comprehensive testing approach ensures the biometric integration system works reliably across different scenarios and device types.</content>
<parameter name="filePath">/Users/mac/ERPNext/kimzon/apps/biometric_integration/TESTING_GUIDE.md