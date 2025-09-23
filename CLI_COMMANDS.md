# Biometric Integration CLI Commands

## Overview

The biometric integration app provides a comprehensive CLI interface for managing biometric device listeners through the `bench` command system.

## Command Structure

All commands follow the pattern:
```bash
bench --site [site_name] biometric-listener [command] [options]
```

## Commands

### 1. Enable Listener

**Command**: `biometric-listener enable`

**Description**: Enables the NGINX listener for biometric devices on a specified port.

**Syntax**:
```bash
bench --site [site_name] biometric-listener enable --port [port_number]
```

**Parameters**:
- `--port` (required): The TCP port number to listen on (e.g., 8998, 8008)

**Examples**:
```bash
# Enable listener on port 8998
bench --site mysite.local biometric-listener enable --port 8998

# Enable on a different port
bench --site production biometric-listener enable --port 8008
```

**What it does**:
1. Validates the site exists and is accessible
2. Checks if a port is already configured (reads from site_config.json)
3. Requires `--port` if no port is configured
4. Injects NGINX server block configuration
5. Updates site configuration with the port number
6. Reloads NGINX to apply changes

**Success Output**:
```
Successfully enabled listener for mysite.local on port 8998.
```

**Error Handling**:
- Missing site: `Error: Please specify a site using: bench --site SITENAME biometric-listener enable`
- Missing port: `Error: --port is required when no port is set in site_config.json`
- NGINX errors: Displays the specific error message

### 2. Disable Listener

**Command**: `biometric-listener disable`

**Description**: Disables the NGINX listener and removes all related configuration.

**Syntax**:
```bash
bench --site [site_name] biometric-listener disable
```

**Parameters**: None required

**Examples**:
```bash
# Disable listener for a site
bench --site mysite.local biometric-listener disable
```

**What it does**:
1. Validates the site exists
2. Reads current port from site configuration
3. Removes the NGINX server block for that site/port combination
4. Removes port configuration from site_config.json
5. Reloads NGINX to apply changes

**Success Output**:
```
Successfully disabled listener for mysite.local.
```

**When already disabled**:
```
Listener is not enabled for site mysite.local.
```

### 3. Check Status

**Command**: `biometric-listener status`

**Description**: Displays the current status of biometric listeners.

**Syntax**:
```bash
bench --site [site_name] biometric-listener status
# or
bench biometric-listener status  # Check all sites
```

**Parameters**: None

**Examples**:
```bash
# Check status for specific site
bench --site mysite.local biometric-listener status

# Check status for all sites
bench biometric-listener status
```

**Output Format**: JSON with detailed status information

**Enabled Status Example**:
```json
{
  "mysite.local": {
    "status": "enabled",
    "listening_ip": "0.0.0.0 (All Interfaces)",
    "port": 8998,
    "paths": {
      "ebkn": "http://192.168.1.100:8998/ebkn",
      "suprema": "http://192.168.1.100:8998",
      "zkteco": "http://192.168.1.100:8998",
      "hikvision": "http://192.168.1.100:8998"
    }
  }
}
```

**Disabled Status Example**:
```json
{
  "mysite.local": {
    "status": "disabled"
  }
}
```

**Multiple Sites Example**:
```json
{
  "site1.local": {
    "status": "enabled",
    "listening_ip": "0.0.0.0 (All Interfaces)",
    "port": 8998,
    "paths": {
      "ebkn": "http://192.168.1.100:8998/ebkn",
      "zkteco": "http://192.168.1.100:8998"
    }
  },
  "site2.local": {
    "status": "disabled"
  }
}
```

## Configuration Details

### Site Configuration

The listener port is stored in `site_config.json` under the key `biometric_listener_port`.

**Example site_config.json**:
```json
{
  "db_name": "mysite",
  "db_password": "password",
  "biometric_listener_port": 8998
}
```

### NGINX Configuration

The command modifies `/path/to/bench/config/nginx.conf` by adding server blocks like:

```nginx
# -- BIOMETRIC_LISTENER_START_mysite.local_8998 --
server {
    listen 8998;
    server_name _;
    underscores_in_headers on;

    location / {
        set $backend_url http://frappe-bench-frappe/api/method/biometric_integration.api.handle_request;
        proxy_pass $backend_url;

        proxy_set_header Host yoursite.com;

        # Header transformations for device compatibility
        proxy_set_header X-Request-Code $http_request_code;
        proxy_set_header X-Dev-Id $http_dev_id;
        proxy_set_header X-Blk-No $http_blk_no;
        proxy_set_header X-Trans-Id $http_trans_id;
        proxy_set_header X-Cmd-Return-Code $http_cmd_return_code;

        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Original-Request-URI $request_uri;
        proxy_pass_request_headers on;
    }
}
# -- BIOMETRIC_LISTENER_END_mysite.local_8998 --
```

## Troubleshooting

### Common Issues

1. **Permission Denied**:
   ```
   Error reloading NGINX: sudo: command not found
   ```
   **Solution**: Ensure sudo is available and user has permissions, or run as root.

2. **Port Already in Use**:
   ```
   Error: Port 8998 is already in use
   ```
   **Solution**: Choose a different port or free up the existing port.

3. **NGINX Configuration Error**:
   ```
   Error reloading NGINX: [error message]
   ```
   **Solution**: Check NGINX configuration syntax with `sudo nginx -t`

4. **Site Not Found**:
   ```
   Error: Site mysite.local not found
   ```
   **Solution**: Verify site name and ensure it exists in sites directory.

### Verification Steps

1. **Check NGINX Status**:
   ```bash
   sudo systemctl status nginx
   ```

2. **Test Configuration**:
   ```bash
   sudo nginx -t
   ```

3. **Test Port Listening**:
   ```bash
   netstat -tlnp | grep :8998
   # or
   ss -tlnp | grep :8998
   ```

4. **Test Endpoint**:
   ```bash
   curl http://localhost:8998/
   # Should return 404 (expected for root path)
   ```

## Best Practices

1. **Port Selection**:
   - Choose ports above 1024 to avoid requiring root privileges
   - Use consistent ports across environments (8998 for dev, 8999 for staging, etc.)
   - Document port usage in your infrastructure documentation

2. **Security**:
   - Restrict port access to device network segments only
   - Use firewall rules to limit access
   - Monitor access logs for suspicious activity

3. **Monitoring**:
   - Regularly check listener status
   - Monitor NGINX error logs
   - Set up alerts for NGINX reload failures

4. **Backup**:
   - Backup site_config.json before making changes
   - Document all port configurations
   - Include NGINX configuration in backups

## Integration with Deployment

### Automated Setup

For automated deployments, you can script the listener setup:

```bash
#!/bin/bash
SITE_NAME=$1
PORT=$2

# Enable biometric listener
bench --site $SITE_NAME biometric-listener enable --port $PORT

# Verify setup
bench --site $SITE_NAME biometric-listener status
```

### Docker Considerations

When using Docker:
- Ensure port mapping in docker-compose.yml
- Use host networking if needed for device access
- Verify NGINX container has proper permissions

### Load Balancing

For high-availability setups:
- Configure load balancer to route device traffic
- Ensure session stickiness for device-specific commands
- Monitor health endpoints for each instance

This CLI interface provides complete control over the biometric device integration infrastructure.</content>
<parameter name="filePath">/Users/mac/ERPNext/kimzon/apps/biometric_integration/CLI_COMMANDS.md