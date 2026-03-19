#!/bin/bash
# Function to check if MCP config is ready
check_mcp_config() {
    local config_file="/config/mcp-config.txt"

    # Check if config file exists
    if [ ! -f "$config_file" ]; then
        return 1
    fi

    # Count how many core services are configured
    local configured_services=0
    
    # Check for Mattermost (optional)
    if grep -q "export MATTERMOST_TOKEN=" "$config_file"; then
        configured_services=$((configured_services + 1))
    fi

    # Check for Plane (optional)
    if grep -q "export PLANE_API_KEY=" "$config_file"; then
        configured_services=$((configured_services + 1))
    fi
    
    # Check for Grafana (optional)
    if grep -q "export GRAFANA_URL=" "$config_file" && grep -q "export GRAFANA_API_KEY=" "$config_file"; then
        configured_services=$((configured_services + 1))
    fi

    # Require at least one service to be configured
    if [ "$configured_services" -eq 0 ]; then
        echo "No MCP services configured in $config_file"
        return 1
    fi

    return 0
}

# Check if MCP config is ready
check_mcp_config
exit $?
