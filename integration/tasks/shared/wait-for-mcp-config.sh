#!/bin/sh

# POSIX-compatible script to verify MCP configuration readiness.
# It supports an optional required list at /config/mcp-required.txt. When present,
# ALL listed requirements must be satisfied before returning success.

# Check a single requirement token against the config file.
# Known tokens map to multiple variable checks; unknown tokens are treated as VAR names.
check_requirement() {
    requirement="$1"
    config_file="$2"

    case "$requirement" in
        zammad)
            grep -q "^export ZAMMAD_URL=" "$config_file" || return 1
            grep -q "^export ZAMMAD_HTTP_TOKEN=" "$config_file" || return 1
            return 0
            ;;
        mattermost)
            grep -q "^export MATTERMOST_TOKEN=" "$config_file"
            return $?
            ;;
        plane|plane-api)
            grep -q "^export PLANE_API_KEY=" "$config_file"
            return $?
            ;;
        grafana)
            grep -q "^export GRAFANA_URL=" "$config_file" || return 1
            grep -q "^export GRAFANA_API_KEY=" "$config_file" || return 1
            return 0
            ;;
        prometheus)
            grep -q "^export PROMETHEUS_URL=" "$config_file"
            return $?
            ;;
        espocrm)
            grep -q "^export ESPOCRM_API_KEY=" "$config_file" || return 1
            return 0
            ;;
        medusa)
            grep -q "^export MEDUSA_PASSWORD=" "$config_file"
            return $?
            ;;
        *)
            # Treat as variable name; accept either VAR or export VAR form
            var_name="$requirement"
            case "$var_name" in
                export\ *) var_name=`echo "$var_name" | sed 's/^export[ ][ ]*//'` ;;
            esac
            var_name=`echo "$var_name" | cut -d '=' -f 1`
            [ -n "$var_name" ] && grep -q "^export ${var_name}=" "$config_file"
            return $?
            ;;
    esac
}

# Function to check if MCP config is ready
check_mcp_config() {
    config_file="/config/mcp-config.txt"
    required_file="/config/mcp-required.txt"

    # Config must exist
    if [ ! -f "$config_file" ]; then
        echo "Missing $config_file"
        return 1
    fi

    # If required list exists, all must be present
    if [ -f "$required_file" ]; then
        missing=""
        # Read non-empty, non-comment lines
        while IFS= read -r line || [ -n "$line" ]; do
            # Trim leading/trailing spaces
            trimmed=`echo "$line" | sed 's/^[ ][ ]*//;s/[ ][ ]*$//'`
            # Skip comments and empty lines
            echo "$trimmed" | grep -qE '^(#|$)' && continue

            if ! check_requirement "$trimmed" "$config_file"; then
                if [ -z "$missing" ]; then
                    missing="$trimmed"
                else
                    missing="$missing $trimmed"
                fi
            fi
        done < "$required_file"

        if [ -n "$missing" ]; then
            echo "Waiting for MCP configs: $missing"
            return 1
        fi
        return 0
    fi

    # Fallback behavior: only run when required file is missing due to failures
    configured_services=0
    grep -q "^export MATTERMOST_TOKEN=" "$config_file" && configured_services=`expr $configured_services + 1`
    grep -q "^export PLANE_API_KEY=" "$config_file" && configured_services=`expr $configured_services + 1`
    grep -q "^export GRAFANA_URL=" "$config_file" && grep -q "^export GRAFANA_API_KEY=" "$config_file" && configured_services=`expr $configured_services + 1`
    grep -q "^export PROMETHEUS_URL=" "$config_file" && configured_services=`expr $configured_services + 1`
    grep -q "^export ZAMMAD_URL=" "$config_file" && configured_services=`expr $configured_services + 1`

    if [ "$configured_services" -eq 0 ]; then
        echo "No MCP services configured in $config_file"
        return 1
    fi
    return 0
}

# Check if MCP config is ready
check_mcp_config
exit $?
