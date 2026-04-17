#!/bin/bash
# Comprehensive MCP configuration setup script
# This script configures ALL observability MCP services:
# - Grafana/Loki (log queries)
# - Mattermost (team discussions)
# - Plane (issue tracking)
#
# Run from the client container which has access to /config directory

# NOTE: Do NOT use set -e - we want to continue even if some services fail
# Commands like grep/jq may return non-zero when no match is found, which is expected

# DEBUG: Log ALL output to a file for debugging
# Write to /data/ which is mounted to host filesystem (persists after docker compose down)
DEBUG_LOG="/data/setup-debug.log"
exec > >(tee -a "$DEBUG_LOG") 2>&1
echo ""
echo "========================================"
echo "🚀 SETUP SCRIPT STARTED at $(date)"
echo "   Debug log: $DEBUG_LOG"
echo "========================================"
echo ""
echo "🔄 Setting up observability MCP environment variables..."

# Ensure config directory exists
if [ ! -d "/config" ]; then
    echo "⚠️ /config directory not found - observability MCP setup skipped"
    exit 0
fi

# Initialize or clear MCP config file
CONFIG_FILE="/config/mcp-config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "📝 Creating $CONFIG_FILE..."
    touch "$CONFIG_FILE"
fi

# Add header comment if file is empty
if [ ! -s "$CONFIG_FILE" ]; then
    cat >> "$CONFIG_FILE" << 'EOF'
# MCP Configuration for Observability Services
# This file is auto-generated - modifications may be overwritten
# Source this file before running MCP commands: set -a && source /config/mcp-config.txt && set +a

EOF
fi

###############################################
# 1. GRAFANA (Loki) MCP Configuration
###############################################

ensure_grafana_config() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 Configuring Grafana/Loki MCP..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    local GF_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
    local GF_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin}"

    # Check if valid token already exists
    local existing_key
    existing_key=$(grep -E '^export GRAFANA_API_KEY=' "$CONFIG_FILE" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
    if [ -n "$existing_key" ] && [ "$existing_key" != "initial_placeholder" ]; then
        local code
        code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $existing_key" http://grafana:3000/api/datasources 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "✅ Existing Grafana token is valid"
            return 0
        else
            echo "⚠️ Existing token invalid (HTTP $code), regenerating..."
        fi
    fi

    # Wait for Grafana to be ready (increased timeout for slow starts)
    echo "⏳ Waiting for Grafana to be ready..."
    local ready=false
    for i in {1..300}; do
        local health_resp
        health_resp=$(curl -s http://grafana:3000/api/health 2>&1)
        if echo "$health_resp" | grep -q '"database".*"ok"'; then
            ready=true
            echo "✅ Grafana is ready (after ${i}s)"
            break
        fi
        if [ $((i % 30)) -eq 0 ]; then
            echo "   Still waiting for Grafana... ($i/300)"
            echo "   Health response: $health_resp"
        fi
        sleep 1
    done

    if [ "$ready" != true ]; then
        echo "❌ Grafana not healthy after timeout"
        # Still add direct Loki URL as fallback
        add_loki_direct_fallback
        return 1
    fi

    # Create service account
    echo "🔑 Creating Grafana service account..."
    local sa_resp sa_id
    sa_resp=$(curl -s -u "${GF_ADMIN_USER}:${GF_ADMIN_PASSWORD}" -H 'Content-Type: application/json' \
        -X POST http://grafana:3000/api/serviceaccounts \
        -d '{"name":"mcp-loki","role":"Admin"}' 2>/dev/null)
    sa_id=$(echo "$sa_resp" | jq -r '.id // empty' 2>/dev/null)

    # If creation failed, try to find existing
    if [ -z "$sa_id" ] || [ "$sa_id" = "null" ]; then
        echo "   Service account may exist, searching..."
        local sa_list
        sa_list=$(curl -s -u "${GF_ADMIN_USER}:${GF_ADMIN_PASSWORD}" 'http://grafana:3000/api/serviceaccounts/search?perpage=500' 2>/dev/null)
        sa_id=$(echo "$sa_list" | jq -r '.serviceAccounts[]? | select(.name=="mcp-loki") | .id' 2>/dev/null | head -n 1)
        
        # Try alternate API format
        if [ -z "$sa_id" ] || [ "$sa_id" = "null" ]; then
            sa_list=$(curl -s -u "${GF_ADMIN_USER}:${GF_ADMIN_PASSWORD}" 'http://grafana:3000/api/serviceaccounts?perpage=500' 2>/dev/null)
            sa_id=$(echo "$sa_list" | jq -r '.[]? | select(.name=="mcp-loki") | .id' 2>/dev/null | head -n 1)
        fi
    fi

    if [ -z "$sa_id" ] || [ "$sa_id" = "null" ]; then
        echo "❌ Failed to create or find Grafana service account"
        echo "   Response: $sa_resp"
        add_loki_direct_fallback
        return 1
    fi

    echo "   Service account ID: $sa_id"

    # Create token
    echo "🔑 Creating API token..."
    local token_resp token
    token_resp=$(curl -s -u "${GF_ADMIN_USER}:${GF_ADMIN_PASSWORD}" -H 'Content-Type: application/json' \
        -X POST "http://grafana:3000/api/serviceaccounts/${sa_id}/tokens" \
        -d "{\"name\":\"mcp-token-$(date +%s)\"}" 2>/dev/null)
    token=$(echo "$token_resp" | jq -r '.key // .token // empty' 2>/dev/null)

    if [ -z "$token" ] || [ "$token" = "null" ]; then
        echo "❌ Failed to create API token"
        echo "   Response: $token_resp"
        add_loki_direct_fallback
        return 1
    fi

    # Remove old Grafana config and add new
    sed -i '/^export GRAFANA_URL=/d' "$CONFIG_FILE" 2>/dev/null || true
    sed -i '/^export GRAFANA_API_KEY=/d' "$CONFIG_FILE" 2>/dev/null || true
    sed -i '/^export GRAFANA_DATASOURCE_UID=/d' "$CONFIG_FILE" 2>/dev/null || true
    sed -i '/^# Grafana/d' "$CONFIG_FILE" 2>/dev/null || true

    cat >> "$CONFIG_FILE" << EOF

# Grafana MCP Configuration
export GRAFANA_URL=http://grafana:3000
export GRAFANA_API_KEY=$token
export GRAFANA_DATASOURCE_UID=1
EOF

    # Validate token can access datasources
    local vcode
    vcode=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" http://grafana:3000/api/datasources 2>/dev/null || echo "000")
    if [ "$vcode" = "200" ]; then
        echo "✅ Grafana token validated - can list datasources"
    else
        echo "⚠️ Token validation failed (HTTP $vcode) - may not be able to access Loki via Grafana"
    fi

    # Test that we can actually query Loki through Grafana's proxy
    echo "🔍 Testing Loki query through Grafana proxy..."
    local loki_test
    loki_test=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $token" \
        "http://grafana:3000/api/datasources/proxy/1/loki/api/v1/labels" 2>/dev/null)
    local loki_code=$(echo "$loki_test" | tail -1)
    if [ "$loki_code" = "200" ]; then
        echo "✅ Loki query via Grafana proxy works"
    else
        echo "⚠️ Loki query via Grafana proxy failed (HTTP $loki_code)"
        echo "   Direct Loki URL (http://loki:3100) should still work"
    fi

    # Always add direct Loki URL as fallback
    add_loki_direct_fallback
    return 0
}

add_loki_direct_fallback() {
    # Add direct Loki URL for fallback (no auth required)
    if ! grep -q "export LOKI_URL=" "$CONFIG_FILE" 2>/dev/null; then
        cat >> "$CONFIG_FILE" << 'EOF'

# Direct Loki URL (fallback - no auth required)
export LOKI_URL=http://loki:3100
EOF
        echo "ℹ️ Added direct Loki URL as fallback"
    fi
}

###############################################
# 2a. MATTERMOST DATA LOADING (defined first so it can be called)
###############################################

ensure_mattermost_data() {
    local api_token="$1"
    
    echo ""
    echo "========================================"
    echo "🔍 ensure_mattermost_data() CALLED"
    echo "   api_token length: ${#api_token}"
    echo "   api_token prefix: ${api_token:0:10}..."
    echo "========================================"
    
    # Wait a bit more for Mattermost's internal database to be fully ready
    echo "   Waiting 15s for Mattermost database to stabilize..."
    sleep 15
    
    # Get team ID first (required for other API calls)
    local team_id
    team_id=$(curl -s -H "Authorization: Bearer $api_token" \
        "http://mattermost:8065/api/v4/teams/name/test-demo" 2>/dev/null | jq -r '.id // empty')
    
    if [ -z "$team_id" ] || [ "$team_id" = "null" ]; then
        echo "❌ Could not get team ID"
        return 1
    fi
    echo "   Team ID: $team_id"
    
    # Check if 'general' channel exists with messages (use correct API endpoint)
    local channels_resp
    channels_resp=$(curl -s -H "Authorization: Bearer $api_token" \
        "http://mattermost:8065/api/v4/teams/$team_id/channels" 2>/dev/null)
    
    echo "   DEBUG: channels_resp (first 500 chars):"
    echo "   ${channels_resp:0:500}"
    
    # Check 'general' channel first (Mattermost ECR container loads Discord data here)
    # Fall back to 'town-square' if general doesn't have data
    local channel_count
    channel_count=$(echo "$channels_resp" | jq -r '.[] | select(.name=="general") | .total_msg_count // 0' 2>/dev/null || echo "0")
    echo "   DEBUG: general msg count = '$channel_count'"
    
    if [ -n "$channel_count" ] && [ "$channel_count" -gt 100 ]; then
        echo "✅ Mattermost has $channel_count messages in 'general' channel - data already loaded by ECR container"
        return 0
    fi
    
    # Check town-square as fallback
    local ts_count
    ts_count=$(echo "$channels_resp" | jq -r '.[] | select(.name=="town-square") | .total_msg_count // 0' 2>/dev/null || echo "0")
    echo "   DEBUG: town-square msg count = '$ts_count'"
    
    if [ -n "$ts_count" ] && [ "$ts_count" -gt 100 ]; then
        echo "✅ Mattermost has $ts_count messages in 'town-square' channel - data already loaded"
        return 0
    fi
    
    echo "⚠️ Mattermost channels have low message counts (general=$channel_count, town-square=$ts_count)"
    echo "🔄 Loading Discord data from /data/mattermost/scraped.json..."
    
    # Check if data file exists
    echo "   DEBUG: Checking for data file at /data/mattermost/scraped.json"
    echo "   DEBUG: ls -la /data/mattermost/ output:"
    ls -la /data/mattermost/ 2>&1 || echo "   DEBUG: ls failed"
    
    if [ ! -f "/data/mattermost/scraped.json" ]; then
        echo "❌ Data file not found: /data/mattermost/scraped.json"
        return 1
    fi
    echo "   DEBUG: Data file exists!"
    
    local msg_count
    msg_count=$(jq 'if type == "array" then length elif .messages then (.messages | length) else 0 end' /data/mattermost/scraped.json 2>/dev/null || echo "0")
    echo "   Found $msg_count messages in scraped.json"
    
    if [ "$msg_count" -lt 1 ]; then
        echo "❌ No messages in data file"
        return 1
    fi
    
    # Check for 'general' channel first (Mattermost ECR container creates this with Discord data)
    # Fall back to 'town-square' if general doesn't exist
    local channel_id channel_name
    channel_id=$(echo "$channels_resp" | jq -r '.[] | select(.name=="general") | .id // empty' 2>/dev/null)
    channel_name="general"
    
    if [ -z "$channel_id" ] || [ ${#channel_id} -ne 26 ]; then
        # Try town-square as fallback
        channel_id=$(echo "$channels_resp" | jq -r '.[] | select(.name=="town-square") | .id // empty' 2>/dev/null)
        channel_name="town-square"
    fi
    
    echo "   DEBUG: $channel_name channel_id = '$channel_id'"
    
    # Final validation
    if [ -z "$channel_id" ] || [ ${#channel_id} -ne 26 ]; then
        echo "❌ Could not find suitable channel (general or town-square)"
        echo "   channel_id value: '$channel_id'"
        return 1
    fi
    echo "   Using '$channel_name' channel ID: $channel_id"
    
    # Upload SAMPLED messages - every 10th message for ~1000-1500 representative messages
    # This keeps the dataset manageable while preserving context diversity
    # Sampling allows Mattermost to index messages quickly so search works reliably
    
    local sample_rate=10
    if [ "$msg_count" -lt 1000 ]; then
        sample_rate=1  # Small datasets: upload everything
    elif [ "$msg_count" -lt 5000 ]; then
        sample_rate=5  # Medium datasets: every 5th message
    fi
    # Large datasets (>5000): every 10th message
    
    local target_msgs=$((msg_count / sample_rate))
    echo "   Uploading sampled messages (every ${sample_rate}th message = ~$target_msgs messages)..."
    echo "   Sampling preserves context diversity while keeping dataset indexable for search."
    
    # Create sampled messages file (handle both array and object-with-messages formats)
    jq -c "(if type == \"array\" then . elif .messages then .messages else [] end) | to_entries | map(select(.key % $sample_rate == 0)) | .[].value" \
        /data/mattermost/scraped.json 2>/dev/null > /tmp/sampled_msgs.json
    
    local uploaded=0
    local batch_count=0
    local curl_pids=()

    while IFS= read -r msg; do
        local content
        content=$(echo "$msg" | jq -r '(if .content | type == "object" then .content.body else null end) // .content // .message // empty | if type == "string" then . else empty end' 2>/dev/null | head -c 4000)

        if [ -n "$content" ] && [ "$content" != "null" ] && [ ${#content} -gt 5 ]; then
            # Escape for JSON
            local escaped_content
            escaped_content=$(echo "$content" | jq -Rs . 2>/dev/null)

            # Upload in batches of 10 parallel requests
            curl -s -m 10 -X POST "http://mattermost:8065/api/v4/posts" \
                -H "Authorization: Bearer $api_token" \
                -H "Content-Type: application/json" \
                -d "{\"channel_id\":\"$channel_id\",\"message\":$escaped_content}" \
                >/dev/null 2>&1 &
            curl_pids+=($!)

            uploaded=$((uploaded + 1))
            batch_count=$((batch_count + 1))

            # Wait every 10 messages (allows Mattermost to process and index)
            # Use explicit PIDs to avoid waiting on tee process substitution
            if [ $batch_count -ge 10 ]; then
                for pid in "${curl_pids[@]}"; do
                    wait "$pid" 2>/dev/null
                done
                curl_pids=()
                batch_count=0
            fi

            # Progress report every 100 messages
            if [ $((uploaded % 100)) -eq 0 ]; then
                echo "   Uploaded $uploaded messages..."
            fi
        fi
    done < /tmp/sampled_msgs.json

    # Wait for all remaining uploads to complete (explicit PIDs)
    for pid in "${curl_pids[@]}"; do
        wait "$pid" 2>/dev/null
    done
    rm -f /tmp/sampled_msgs.json
    
    # Wait for Mattermost to index the messages
    echo "   Waiting 15s for Mattermost to index messages..."
    sleep 15
    
    # Give Mattermost a moment to update stats
    sleep 3
    
    # Verify final count
    local final_count
    final_count=$(curl -s -H "Authorization: Bearer $api_token" \
        "http://mattermost:8065/api/v4/channels/$channel_id/stats" 2>/dev/null | jq -r '.message_count // 0')
    
    if [ "$final_count" -gt 0 ]; then
        echo "✅ Mattermost data loading complete - $final_count messages in '$channel_name' channel"
    else
        echo "⚠️ Mattermost stats show 0, but uploaded $uploaded messages (may take time to update)"
    fi
    
    echo ""
    echo "   NOTE: Use 'mattermost_fetch' on '$channel_name' channel to retrieve messages."
    echo "   Search may not work reliably - fetch is more dependable."
    return 0
}

###############################################
# 2b. MATTERMOST MCP Configuration
###############################################

ensure_mattermost_config() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "💬 Configuring Mattermost MCP..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Wait for Mattermost API to be ready (may take a while for Discord upload to complete)
    echo "⏳ Waiting for Mattermost API to be ready..."
    local ready=false
    for i in {1..300}; do
        local ping_resp
        ping_resp=$(curl -s http://mattermost:8065/api/v4/system/ping 2>&1)
        if echo "$ping_resp" | grep -q "OK"; then
            ready=true
            echo "✅ Mattermost API is responding (after ${i}s)"
            break
        fi
        if [ $((i % 30)) -eq 0 ]; then
            echo "   Still waiting for Mattermost... ($i/300)"
            echo "   Ping response: $ping_resp"
        fi
        sleep 1
    done

    if [ "$ready" != true ]; then
        echo "❌ Mattermost API not ready after timeout"
        return 1
    fi

    # Check if Mattermost container already wrote a valid token
    local existing_token
    existing_token=$(grep -E '^export MATTERMOST_TOKEN=' "$CONFIG_FILE" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
    if [ -n "$existing_token" ] && [ "$existing_token" != "placeholder" ] && [ ${#existing_token} -gt 10 ]; then
        local code
        code=$(curl -s -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer $existing_token" \
            http://mattermost:8065/api/v4/users/me 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "✅ Using existing valid Mattermost token"
            # Ensure all required fields are present
            grep -q "^export MATTERMOST_ENDPOINT=" "$CONFIG_FILE" || echo "export MATTERMOST_ENDPOINT=http://mattermost:8065/api/v4" >> "$CONFIG_FILE"
            grep -q "^export MATTERMOST_TEAM=" "$CONFIG_FILE" || echo "export MATTERMOST_TEAM=test-demo" >> "$CONFIG_FILE"
            # IMPORTANT: Still need to verify/load Discord data even with existing token
            echo "   DEBUG: About to call ensure_mattermost_data with existing_token"
            ensure_mattermost_data "$existing_token"
            local data_result=$?
            echo "   DEBUG: ensure_mattermost_data returned: $data_result"
            return 0
        fi
        echo "⚠️ Existing token invalid (HTTP $code), creating new one..."
    fi

    # Create/login admin user and get API token
    echo "🔑 Setting up Mattermost authentication..."
    local admin_email="admin@demo.local"
    local admin_password="AdminUser123!"

    # Try to create admin user (ignore errors if exists)
    curl -s -X POST http://mattermost:8065/api/v4/users \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$admin_email\",\"username\":\"admin\",\"password\":\"$admin_password\",\"first_name\":\"Admin\",\"last_name\":\"User\"}" \
        >/dev/null 2>&1 || true

    sleep 2

    # Login to get session token
    echo "🔑 Logging in to Mattermost..."
    local login_resp session_token
    login_resp=$(curl -s -i -X POST http://mattermost:8065/api/v4/users/login \
        -H "Content-Type: application/json" \
        -d "{\"login_id\":\"$admin_email\",\"password\":\"$admin_password\"}" 2>/dev/null)
    session_token=$(echo "$login_resp" | grep -i "^Token:" | awk '{print $2}' | tr -d '\r\n')

    if [ -z "$session_token" ]; then
        echo "❌ Failed to login to Mattermost"
        echo "   Response headers: $(echo "$login_resp" | head -10)"
        return 1
    fi
    echo "   Session token obtained: ${session_token:0:10}..."

    # Create API token (personal access token)
    echo "🔑 Creating API token..."
    local token_resp api_token
    token_resp=$(curl -s -X POST http://mattermost:8065/api/v4/users/me/tokens \
        -H "Authorization: Bearer $session_token" \
        -H "Content-Type: application/json" \
        -d '{"description":"MCP Integration Token"}' 2>/dev/null)
    api_token=$(echo "$token_resp" | jq -r '.token // empty' 2>/dev/null)

    if [ -z "$api_token" ] || [ "$api_token" = "null" ]; then
        echo "❌ Failed to create API token"
        echo "   Response: $token_resp"
        return 1
    fi
    echo "   API token created: ${api_token:0:10}..."

    # Verify the API token works
    local verify_code
    verify_code=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer $api_token" \
        http://mattermost:8065/api/v4/users/me 2>/dev/null)
    if [ "$verify_code" != "200" ]; then
        echo "❌ API token verification failed (HTTP $verify_code)"
        return 1
    fi
    echo "✅ API token verified"

    # Create team if needed
    echo "🔧 Ensuring team exists..."
    curl -s -X POST http://mattermost:8065/api/v4/teams \
        -H "Authorization: Bearer $api_token" \
        -H "Content-Type: application/json" \
        -d '{"name":"test-demo","display_name":"Test Demo","type":"O"}' \
        >/dev/null 2>&1 || true

    # Write Mattermost config (remove old entries first)
    sed -i '/^export MATTERMOST_/d' "$CONFIG_FILE" 2>/dev/null || true
    
    cat >> "$CONFIG_FILE" << EOF

# Mattermost MCP Configuration
export MATTERMOST_ENDPOINT=http://mattermost:8065/api/v4
export MATTERMOST_TOKEN=$api_token
export MATTERMOST_TEAM=test-demo
export MATTERMOST_URL=http://mattermost:8065
EOF

    echo "✅ Mattermost configured successfully"
    
    # Now verify and load Discord data if needed
    echo "   DEBUG: About to call ensure_mattermost_data with api_token"
    ensure_mattermost_data "$api_token"
    local data_result=$?
    echo "   DEBUG: ensure_mattermost_data returned: $data_result"
    
    return 0
}

###############################################
# 3a. PLANE DATA Loading
###############################################

ensure_plane_data() {
    local api_token="$1"
    
    echo ""
    echo "========================================"
    echo "🔍 ensure_plane_data() CALLED"
    echo "   api_token prefix: ${api_token:0:15}..."
    echo "========================================"
    
    # Check if data file exists
    echo "   DEBUG: Checking for data file at /data/plane/issues.json"
    ls -la /data/plane/ 2>&1 || echo "   DEBUG: ls failed"
    
    if [ ! -f "/data/plane/issues.json" ]; then
        echo "⚠️ Data file not found: /data/plane/issues.json (not required, continuing)"
        return 0
    fi
    echo "   DEBUG: Data file exists!"
    
    local issue_count
    issue_count=$(jq 'length' /data/plane/issues.json 2>/dev/null || echo "0")
    echo "   Found $issue_count issues in issues.json"
    
    if [ "$issue_count" -lt 1 ]; then
        echo "⚠️ No issues in data file"
        return 0
    fi
    
    # Get workspace info
    echo "   Getting workspace list..."
    local workspaces_resp
    workspaces_resp=$(curl -s -H "X-API-Key: $api_token" \
        "http://plane-api:8000/api/v1/workspaces/" 2>/dev/null)
    echo "   DEBUG: workspaces response (first 300 chars): ${workspaces_resp:0:300}"
    
    # Extract workspace slug
    local workspace_slug
    workspace_slug=$(echo "$workspaces_resp" | jq -r '.results[0].slug // .results[0].name // .[0].slug // .[0].name // empty' 2>/dev/null)
    
    # If no workspace exists, wait longer for ECR container to create it
    if [ -z "$workspace_slug" ] || [ "$workspace_slug" = "null" ]; then
        echo "⚠️ No workspace found - ECR container may still be initializing"
        echo "   Waiting additional time for Plane migrations and data import..."
        
        # Wait up to 3 more minutes for workspace to appear
        for i in {1..36}; do
            sleep 5
            workspaces_resp=$(curl -s -H "X-API-Key: $api_token" \
                "http://plane-api:8000/api/v1/workspaces/" 2>/dev/null)
            workspace_slug=$(echo "$workspaces_resp" | jq -r '.results[0].slug // .results[0].name // .[0].slug // .[0].name // empty' 2>/dev/null)
            
            if [ -n "$workspace_slug" ] && [ "$workspace_slug" != "null" ]; then
                echo "✅ Workspace appeared after extended wait: $workspace_slug"
                break
            fi
            
            if [ $((i % 6)) -eq 0 ]; then
                echo "   Still waiting for workspace... ($((i * 5))s)"
            fi
        done
        
        if [ -z "$workspace_slug" ] || [ "$workspace_slug" = "null" ]; then
            echo "❌ Workspace never appeared - Plane ECR container may have failed"
            echo "   Plane MCP will not work for this task"
            return 1
        fi
    fi
    
    echo "   Workspace slug: $workspace_slug"
    
    # Update config with correct workspace slug
    if ! grep -q "^export PLANE_WORKSPACE_SLUG=$workspace_slug" "$CONFIG_FILE"; then
        sed -i "s/^export PLANE_WORKSPACE_SLUG=.*/export PLANE_WORKSPACE_SLUG=$workspace_slug/" "$CONFIG_FILE" 2>/dev/null || true
    fi
    
    # Get projects
    echo "   Getting projects list..."
    local projects_resp
    projects_resp=$(curl -s -H "X-API-Key: $api_token" \
        "http://plane-api:8000/api/v1/workspaces/$workspace_slug/projects/" 2>/dev/null)
    echo "   DEBUG: projects response (first 300 chars): ${projects_resp:0:300}"
    
    # Check if issues already exist
    local project_id
    project_id=$(echo "$projects_resp" | jq -r '.results[0].id // .[0].id // empty' 2>/dev/null)
    
    if [ -n "$project_id" ] && [ "$project_id" != "null" ]; then
        echo "   Project ID: $project_id"
        
        # Check existing issues
        local issues_resp
        issues_resp=$(curl -s -H "X-API-Key: $api_token" \
            "http://plane-api:8000/api/v1/workspaces/$workspace_slug/projects/$project_id/issues/" 2>/dev/null)
        local existing_issues
        existing_issues=$(echo "$issues_resp" | jq 'if type == "array" then length else (.results | length) // 0 end' 2>/dev/null || echo "0")
        
        if [ "$existing_issues" -gt 0 ]; then
            echo "✅ Plane already has $existing_issues issues - data already loaded"
            return 0
        fi
    fi
    
    echo "⚠️ Plane has no issues loaded - ECR container may have failed to import data"
    echo "   This is expected in some cases - the ECR container handles data loading"
    
    return 0
}

###############################################
# 3b. PLANE MCP Configuration
###############################################

ensure_plane_config() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 Configuring Plane MCP..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # First, wait for Plane container to write its config (it does this in its entrypoint)
    echo "⏳ Waiting for Plane container to initialize..."
    for i in {1..360}; do
        # Check if Plane already wrote its token to the config
        local existing_token
        existing_token=$(grep -E '^export PLANE_API_KEY=' "$CONFIG_FILE" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
        if [ -n "$existing_token" ] && [ "$existing_token" != "placeholder" ] && [[ "$existing_token" == plane_* ]]; then
            # Validate token
            local code
            code=$(curl -s -o /dev/null -w '%{http_code}' \
                -H "X-API-Key: $existing_token" \
                http://plane-api:8000/api/v1/workspaces/ 2>/dev/null || echo "000")
            if [ "$code" = "200" ]; then
                echo "✅ Plane token found and validated (written by Plane container)"
                # Ensure all required fields are present
                if ! grep -q "^export PLANE_API_HOST_URL=" "$CONFIG_FILE"; then
                    echo "export PLANE_API_HOST_URL=http://plane-api:8000" >> "$CONFIG_FILE"
                fi
                if ! grep -q "^export PLANE_WORKSPACE_SLUG=" "$CONFIG_FILE"; then
                    echo "export PLANE_WORKSPACE_SLUG=test-demo" >> "$CONFIG_FILE"
                fi
                # Verify data is loaded
                ensure_plane_data "$existing_token"
                return 0
            fi
        fi
        if [ $((i % 30)) -eq 0 ]; then
            echo "   Still waiting for Plane to write config... ($i/360) - migrations may be running"
        fi
        sleep 2
    done

    echo "⚠️ Plane container didn't write valid config after 12 minutes"
    echo "🔄 Attempting manual Plane setup..."
    
    # Try to ping Plane API
    local plane_health
    plane_health=$(curl -s -o /dev/null -w '%{http_code}' http://plane-api:8000/ 2>/dev/null || echo "000")
    echo "   Plane health check: HTTP $plane_health"
    
    if [ "$plane_health" = "000" ]; then
        echo "❌ Plane API not responding - container may have failed to start"
        # Add placeholder config
        if ! grep -q "^export PLANE_API_HOST_URL=" "$CONFIG_FILE"; then
            cat >> "$CONFIG_FILE" << 'EOF'

# Plane MCP Configuration (placeholder - Plane failed to initialize)
export PLANE_API_HOST_URL=http://plane-api:8000
export PLANE_API_KEY=placeholder_plane_not_available
export PLANE_WORKSPACE_SLUG=test-demo
EOF
        fi
        return 1
    fi
    
    # Plane is responding but didn't write config - may still be running migrations
    # Try a few more times with longer waits
    echo "   Plane is responding - waiting longer for setup completion..."
    for i in {1..60}; do
        local existing_token
        existing_token=$(grep -E '^export PLANE_API_KEY=' "$CONFIG_FILE" 2>/dev/null | tail -n 1 | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
        if [ -n "$existing_token" ] && [[ "$existing_token" == plane_* ]]; then
            local code
            code=$(curl -s -o /dev/null -w '%{http_code}' \
                -H "X-API-Key: $existing_token" \
                http://plane-api:8000/api/v1/workspaces/ 2>/dev/null || echo "000")
            if [ "$code" = "200" ]; then
                echo "✅ Plane config appeared after extended wait"
                if ! grep -q "^export PLANE_API_HOST_URL=" "$CONFIG_FILE"; then
                    echo "export PLANE_API_HOST_URL=http://plane-api:8000" >> "$CONFIG_FILE"
                fi
                if ! grep -q "^export PLANE_WORKSPACE_SLUG=" "$CONFIG_FILE"; then
                    echo "export PLANE_WORKSPACE_SLUG=test-demo" >> "$CONFIG_FILE"
                fi
                ensure_plane_data "$existing_token"
                return 0
            fi
        fi
        if [ $((i % 10)) -eq 0 ]; then
            echo "   Extended wait... ($i/60)"
        fi
        sleep 5
    done
    
    echo "⚠️ Plane setup timed out - adding placeholder config"
    if ! grep -q "^export PLANE_API_HOST_URL=" "$CONFIG_FILE"; then
        cat >> "$CONFIG_FILE" << 'EOF'

# Plane MCP Configuration (placeholder - Plane may still be initializing)
export PLANE_API_HOST_URL=http://plane-api:8000
export PLANE_API_KEY=placeholder_awaiting_plane_init
export PLANE_WORKSPACE_SLUG=test-demo
EOF
    fi

    return 1
}

###############################################
# Main execution
###############################################

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     MCP Configuration Setup for Observability Services       ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# Initial delay to let services start up
echo ""
echo "⏳ Waiting 15 seconds for services to initialize..."
sleep 15

# Configure each service
grafana_ok=false
mattermost_ok=false
plane_ok=false

# Run Grafana config first (quick)
ensure_grafana_config && grafana_ok=true || true

# Run Mattermost and Plane in parallel for speed
# Mattermost config (includes data loading) - run in foreground
# Plane config - run in background since it waits for ECR container
echo ""
echo "🚀 Starting Plane configuration in background (waits for ECR container)..."
ensure_plane_config &
plane_pid=$!

# Run Mattermost config (faster data loading now)
ensure_mattermost_config && mattermost_ok=true || true

# Wait for Plane config to complete (max 60 more seconds)
echo ""
echo "⏳ Waiting for Plane configuration to complete..."
for i in {1..12}; do
    if ! kill -0 $plane_pid 2>/dev/null; then
        break
    fi
    sleep 5
done
wait $plane_pid 2>/dev/null || true

# Check if Plane configuration succeeded
if grep -q "^export PLANE_API_KEY=plane_" "$CONFIG_FILE" 2>/dev/null; then
    plane_ok=true
    echo "✅ Plane configuration completed"
else
    echo "⚠️ Plane configuration may not have completed"
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Configuration Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ "$grafana_ok" = true ]; then
    echo "  ✅ Grafana/Loki: Configured"
else
    echo "  ⚠️  Grafana/Loki: Failed (direct Loki URL available as fallback)"
fi

if [ "$mattermost_ok" = true ]; then
    echo "  ✅ Mattermost:   Configured"
else
    echo "  ⚠️  Mattermost:   Not configured (service may not be ready)"
fi

if [ "$plane_ok" = true ]; then
    echo "  ✅ Plane:        Configured"
else
    echo "  ⚠️  Plane:        Not configured (service may still be initializing)"
fi

echo ""
echo "📍 Config file: $CONFIG_FILE"
echo ""
echo "📄 Current MCP config contents:"
echo "─────────────────────────────────"
cat "$CONFIG_FILE"
echo "─────────────────────────────────"

# Final verification - check required variables
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Verifying Required Environment Variables"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Source the config to verify
set -a
source "$CONFIG_FILE"
set +a

verify_var() {
    local var_name="$1"
    local var_value="${!var_name}"
    if [ -n "$var_value" ] && [ "$var_value" != "placeholder" ] && [[ "$var_value" != *"placeholder"* ]]; then
        echo "  ✅ $var_name = ${var_value:0:30}..."
        return 0
    else
        echo "  ❌ $var_name = (missing or placeholder)"
        return 1
    fi
}

echo ""
echo "Grafana/Loki:"
verify_var "GRAFANA_URL" || true
verify_var "GRAFANA_API_KEY" || true
verify_var "LOKI_URL" || true

echo ""
echo "Mattermost:"
verify_var "MATTERMOST_ENDPOINT" || true
verify_var "MATTERMOST_TOKEN" || true
verify_var "MATTERMOST_TEAM" || true

echo ""
echo "Plane:"
verify_var "PLANE_API_HOST_URL" || true
verify_var "PLANE_API_KEY" || true

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 Testing MCP Servers"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Test Mattermost MCP
echo ""
echo "Testing Mattermost MCP..."
if [ -n "$MATTERMOST_ENDPOINT" ] && [ -n "$MATTERMOST_TOKEN" ] && [ -n "$MATTERMOST_TEAM" ]; then
    MM_TEST=$({
        echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1.0"},"capabilities":{}}}';
        echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}';
        echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}';
    } | timeout 10 node /app/mcp-servers/mattermost/dist/main.js 2>&1)
    if echo "$MM_TEST" | grep -q "mattermost_"; then
        echo "  ✅ Mattermost MCP server responds correctly"
    else
        echo "  ❌ Mattermost MCP server failed"
        echo "  Error: $MM_TEST" | head -5
    fi
else
    echo "  ⚠️ Skipped - missing environment variables"
fi

# Test Plane MCP
echo ""
echo "Testing Plane MCP..."
if [ -n "$PLANE_API_HOST_URL" ] && [ -n "$PLANE_API_KEY" ]; then
    PLANE_TEST=$({
        echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1.0"},"capabilities":{}}}';
        echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}';
        echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}';
    } | timeout 10 node /app/mcp-servers/plane/build/index.js 2>&1)
    if echo "$PLANE_TEST" | grep -q "get_projects"; then
        echo "  ✅ Plane MCP server responds correctly"
    else
        echo "  ❌ Plane MCP server failed"
        echo "  Error: $PLANE_TEST" | head -5
    fi
else
    echo "  ⚠️ Skipped - missing environment variables"
fi

# Test Loki direct API (always available)
echo ""
echo "Testing Direct Loki API..."
LOKI_TEST=$(curl -s "http://loki:3100/ready" 2>&1)
if echo "$LOKI_TEST" | grep -q "ready"; then
    echo "  ✅ Direct Loki API is available at http://loki:3100"
else
    echo "  ❌ Direct Loki API not ready"
fi

echo ""
echo "✅ MCP configuration setup completed!"
echo ""
echo "========================================"
echo "📋 DEBUG SUMMARY at $(date)"
echo "========================================"
echo "grafana_ok=$grafana_ok"
echo "mattermost_ok=$mattermost_ok"
echo "plane_ok=$plane_ok"
echo ""
echo "Contents of $CONFIG_FILE:"
cat "$CONFIG_FILE" 2>/dev/null || echo "(file not found)"
echo ""
echo "Debug log saved to: $DEBUG_LOG"
echo "========================================"

# Create marker file to indicate setup is complete
# This is used by the healthcheck to wait for setup before starting the agent
touch /tmp/mcp-setup-complete
echo "✅ Setup complete marker created: /tmp/mcp-setup-complete"
