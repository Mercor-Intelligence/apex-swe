#!/bin/bash
# Docker Entrypoint for Mattermost with Embedded PostgreSQL in Lightweight Mode
# Uses Ubuntu-based Mattermost image

set -e

echo "🚀 Starting Mattermost with embedded PostgreSQL in lightweight mode..."

# Setup PostgreSQL data directory in tmpfs
echo "🔄 Setting up in-memory PostgreSQL for Mattermost..."
export PGDATA="/tmp/mattermost-postgres-data"
export POSTGRES_USER="mattermost"
export POSTGRES_PASSWORD="mattermost"
export POSTGRES_DB="mattermost"

# Start PostgreSQL service
service postgresql start

# Configure PostgreSQL to use port 5433 to avoid conflict with Plane
echo "🔄 Configuring PostgreSQL to use port 5433..."
sudo -u postgres sed -i "s/#port = 5432/port = 5433/" /etc/postgresql/14/main/postgresql.conf
sudo -u postgres sed -i "s/port = 5432/port = 5433/" /etc/postgresql/14/main/postgresql.conf

# Restart PostgreSQL with new port
service postgresql restart

# Wait for PostgreSQL on port 5433
echo "🔄 Waiting for PostgreSQL on port 5433..."
for i in $(seq 1 30); do
  if sudo -u postgres pg_isready -h localhost -p 5433; then
    echo "✅ PostgreSQL ready on port 5433!"
    break
  fi
  echo "   PostgreSQL not ready on port 5433, waiting... ($i/30)"
  sleep 2
done

# Create database and user
echo "🔄 Creating Mattermost database and user..."
sudo -u postgres createuser --createdb --login "$POSTGRES_USER" -p 5433 || true
sudo -u postgres createdb -O "$POSTGRES_USER" "$POSTGRES_DB" -p 5433 || true
sudo -u postgres psql -p 5433 -c "ALTER USER $POSTGRES_USER PASSWORD '$POSTGRES_PASSWORD';"

# Mattermost is already installed in the Docker image
echo "📦 Setting up Mattermost directories..."
# Ensure directories exist with proper permissions
mkdir -p /mattermost/logs
mkdir -p /mattermost/data
mkdir -p /mattermost/config
mkdir -p /mattermost/plugins
# Fix permissions for data directories
chmod -R 755 /mattermost/data
chmod -R 755 /mattermost/logs
chmod -R 755 /mattermost/config
chmod -R 755 /mattermost/plugins
chown -R mattermost:mattermost /mattermost/data
chown -R mattermost:mattermost /mattermost/logs
chown -R mattermost:mattermost /mattermost/config
chown -R mattermost:mattermost /mattermost/plugins

# Create Mattermost config
echo "🔄 Creating Mattermost configuration..."
cat > /mattermost/config/config.json << 'EOF'
{
  "ServiceSettings": {
    "SiteURL": "http://localhost:8065",
    "ListenAddress": ":8065",
    "EnableDeveloper": true,
    "EnableUserAccessTokens": true,
    "EnableLinkPreviews": false,
    "EnablePermalinkPreviews": false
  },
  "SqlSettings": {
    "DriverName": "postgres",
    "DataSource": "postgres://mattermost:mattermost@localhost:5433/mattermost?sslmode=disable&connect_timeout=10"
  },
  "EmailSettings": {
    "SendEmailNotifications": false,
    "RequireEmailVerification": false,
    "EnableSignUpWithEmail": true
  },
  "PluginSettings": {
    "Enable": false,
    "EnableUploads": false
  },
  "LogSettings": {
    "EnableConsole": true,
    "ConsoleLevel": "ERROR",
    "EnableFile": false
  },
  "DataRetentionSettings": {
    "EnableMessageDeletion": false,
    "EnableFileDeletion": false
  },
  "FileSettings": {
    "EnableFileAttachments": false,
    "EnableMobileUpload": false,
    "EnableMobileDownload": false
  },
  "ImageProxySettings": {
    "Enable": false
  }
}
EOF

echo "✅ Mattermost setup completed!"

# Start Mattermost server in background to allow Discord upload
echo "🚀 Starting Mattermost server..."
cd /mattermost
./bin/mattermost &
MATTERMOST_PID=$!

# Wait for Mattermost to be ready
echo "🔄 Waiting for Mattermost API to be ready..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8065/api/v4/system/ping > /dev/null 2>&1; then
        echo "✅ Mattermost API is ready!"
        break
    fi
    echo "   Waiting for Mattermost API... ($i/60)"
    sleep 2
done

# Upload Discord messages if available
# Look for Discord scraped data in organized folder structure first, then legacy paths
SCRAPED_FILE=""
# New organized structure: /data/mattermost/
if [ -f "/data/mattermost/scraped.json" ]; then
    SCRAPED_FILE="/data/mattermost/scraped.json"
elif [ -f "/data/mattermost/scraped-discord.json" ]; then
    SCRAPED_FILE="/data/mattermost/scraped-discord.json"
# Legacy fallback: /data/ root (backwards compatibility)
elif [ -f "/data/scraped.json" ]; then
    SCRAPED_FILE="/data/scraped.json"
elif [ -n "$(find /data -maxdepth 1 -name 'scraped-*.json' 2>/dev/null | head -1)" ]; then
    SCRAPED_FILE=$(find /data -maxdepth 1 -name "scraped-*.json" 2>/dev/null | head -1)
fi

if [ -n "$SCRAPED_FILE" ]; then
    echo "🔄 Uploading Discord messages to Mattermost..."
    echo "ℹ️ Found Discord data: $SCRAPED_FILE"

    # Install required dependencies quietly
    echo "🔄 Installing dependencies..."
    apt-get update -qq > /dev/null 2>&1
    apt-get install -y jq -qq > /dev/null 2>&1
    pip3 install psycopg2-binary bcrypt requests -q > /dev/null 2>&1

    # Copy Discord data and run upload script
    cp "$SCRAPED_FILE" /tmp/scraped.json

    # Create fixed Discord upload script based on working upload-discord-to-mattermost.py
    cat > /tmp/discord_upload_fixed.py << 'DISCORD_UPLOAD_EOF'
#!/usr/bin/env python3
import psycopg2
import json
import time
import uuid
import bcrypt
import requests
from datetime import datetime

def print_success(msg): print(f"✅ {msg}")
def print_error(msg): print(f"❌ {msg}")
def print_info(msg): print(f"ℹ️ {msg}")
def print_step(msg): print(f"🔄 {msg}")

print_step("Setting up Mattermost admin and uploading Discord messages...")

# Setup admin user and API token
base_url = "http://localhost:8065"
admin_data = {
    "email": "admin@demo.local",
    "username": "admin",
    "password": "AdminUser123!",
    "first_name": "Admin",
    "last_name": "User"
}

# Create admin user (ignore if exists)
try:
    requests.post(f"{base_url}/api/v4/users", json=admin_data, timeout=10)
except:
    pass

# Login and get session token
login_data = {"login_id": "admin@demo.local", "password": "AdminUser123!"}
login_response = requests.post(f"{base_url}/api/v4/users/login", json=login_data, timeout=10)
session_token = login_response.headers.get("Token")

if not session_token:
    print_error("Failed to get session token")
    exit(1)

# Create API token
headers = {"Authorization": f"Bearer {session_token}"}
token_data = {"description": "MCP Integration Token"}
token_response = requests.post(f"{base_url}/api/v4/users/me/tokens",
                             json=token_data, headers=headers, timeout=10)
api_token = token_response.json().get("token")

if not api_token:
    print_error("Failed to create API token")
    exit(1)

print(f"MATTERMOST_TOKEN:{api_token}")

# Create team
team_data = {"name": "test-demo", "display_name": "Test Demo", "type": "O"}
requests.post(f"{base_url}/api/v4/teams", json=team_data, headers=headers, timeout=10)

# Load and upload Discord messages using PROPER method from working script
try:
    with open("/tmp/scraped.json", "r") as f:
        data = json.load(f)
    
    # Handle both array and object-with-messages formats
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict) and "messages" in data:
        messages = data["messages"]
    else:
        messages = []

    print_info(f"Processing {len(messages)} Discord messages...")


    # Filter Discord messages based on git commit timestamp to prevent future data leakage
    def get_git_commit_timestamp():
        """Get the timestamp of the current git commit from pre-computed file or repo"""
        import subprocess
        import os

        # First, try to read pre-computed timestamp from data directory
        timestamp_file = '/data/git_commit_timestamp.txt'

        # Wait for timestamp file to be ready (with timeout)
        import time
        max_wait = 30  # seconds
        wait_time = 0
        while not os.path.exists(timestamp_file) and wait_time < max_wait:
            print_info(f"Waiting for git commit timestamp file... ({wait_time}s/{max_wait}s)")
            time.sleep(2)
            wait_time += 2

        if os.path.exists(timestamp_file):
            try:
                with open(timestamp_file, 'r') as f:
                    commit_timestamp_str = f.read().strip()
                commit_dt = datetime.fromisoformat(commit_timestamp_str.replace('Z', '+00:00'))
                print_info(f"Using pre-computed git commit timestamp: {commit_timestamp_str}")
                return commit_dt
            except Exception as e:
                print_error(f"Error reading pre-computed timestamp: {e}")

        # Fallback: Try multiple possible repo locations (for direct access)
        possible_paths = ['/repo', '/testbed', '/workspace', '/app', '/opt/django', '/django']
        repo_path = None

        for path in possible_paths:
            if os.path.exists(path) and os.path.exists(os.path.join(path, '.git')):
                repo_path = path
                print_info(f"Found git repo at: {repo_path}")
                break

        if not repo_path:
            print_info("No git repo found and no pre-computed timestamp available")
            print_info(f"Searched repo locations: {', '.join(possible_paths)}")
            print_info(f"Searched timestamp file: {timestamp_file}")
            print_info("To enable filtering, create git_commit_timestamp.txt in /data with commit timestamp")
            return None

        try:
            # Get current commit timestamp in ISO format
            result = subprocess.run([
                'git', '-C', repo_path, 'log', '-1', '--format=%cI'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                commit_timestamp_str = result.stdout.strip()
                # Parse ISO timestamp to datetime
                commit_dt = datetime.fromisoformat(commit_timestamp_str.replace('Z', '+00:00'))
                print_info(f"Git commit timestamp: {commit_timestamp_str}")
                return commit_dt
            else:
                print_error(f"Failed to get git commit timestamp: {result.stderr}")
                return None
        except Exception as e:
            print_error(f"Error getting git commit timestamp: {e}")
            return None

    def filter_messages_by_timestamp(messages, cutoff_timestamp):
        """Filter Discord messages to only include those sent before the cutoff timestamp"""
        if cutoff_timestamp is None:
            return messages

        from datetime import datetime, timezone

        # Ensure cutoff_timestamp is timezone-aware
        if cutoff_timestamp.tzinfo is None:
            cutoff_timestamp = cutoff_timestamp.replace(tzinfo=timezone.utc)

        filtered_messages = []
        for msg in messages:
            try:
                # Parse Discord message timestamp
                timestamp_str = msg.get('timestamp', '')
                if not timestamp_str:
                    continue

                # Discord timestamp format: "2023-11-11T16:56:56.231000+00:00"
                msg_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                # Ensure msg_dt is timezone-aware
                if msg_dt.tzinfo is None:
                    msg_dt = msg_dt.replace(tzinfo=timezone.utc)

                # Only include messages sent before the git commit timestamp
                if msg_dt <= cutoff_timestamp:
                    filtered_messages.append(msg)

            except Exception as e:
                print_error(f"Error parsing timestamp for message {msg.get('id', 'unknown')}: {e}")
                # Include message if we can't parse timestamp (fail-safe)
                filtered_messages.append(msg)

        return filtered_messages

    # Apply timestamp filtering
    git_timestamp = get_git_commit_timestamp()
    if git_timestamp:
        original_count = len(messages)
        messages = filter_messages_by_timestamp(messages, git_timestamp)
        filtered_count = len(messages)
        print_info(f"Filtered messages: {original_count} → {filtered_count} (removed {original_count - filtered_count} future messages)")
    else:
        print_info("Skipping timestamp filtering - using all messages")

    # Connect to database
    conn = psycopg2.connect(host="localhost", port=5433, database="mattermost",
                           user="mattermost", password="mattermost")
    cursor = conn.cursor()

    # Get team and admin IDs
    cursor.execute("SELECT id FROM teams WHERE name = 'test-demo'")
    team_result = cursor.fetchone()
    if not team_result:
        print_error("Team not found")
        exit(1)
    team_id = team_result[0]

    cursor.execute("SELECT id FROM users WHERE email = 'admin@demo.local'")
    admin_result = cursor.fetchone()
    if not admin_result:
        print_error("Admin user not found")
        exit(1)
    admin_id = admin_result[0]

    # Create general channel with FULL schema (like working script)
    channel_id = str(uuid.uuid4()).replace("-", "")[:26]
    now = int(time.time() * 1000)

    cursor.execute("""
        INSERT INTO channels (
            id, createat, updateat, deleteat, teamid, type, displayname, name,
            header, purpose, lastpostat, totalmsgcount, extraupdateat, creatorid,
            schemeid, groupconstrained, shared, totalmsgcountroot, lastrootpostat
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (teamid, name) DO NOTHING
    """, (
        channel_id, now, now, 0, team_id, "O", "General", "general",
        "", "Discord messages from pylint community", now, 0, now, admin_id,
        "", False, False, 0, now
    ))

    # Get the actual channel ID (in case it already existed)
    cursor.execute("SELECT id FROM channels WHERE name = 'general' AND teamid = %s", (team_id,))
    channel_result = cursor.fetchone()
    if channel_result:
        channel_id = channel_result[0]

    # Ensure admin is member of channel with FULL schema (CRITICAL for UI visibility)
    cursor.execute("""
        INSERT INTO channelmembers (
            channelid, userid, roles, lastviewedat, msgcount, mentioncount, notifyprops, lastupdateat,
            schemeuser, schemeadmin, schemeguest, mentioncountroot, msgcountroot, urgentmentioncount
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (channelid, userid) DO NOTHING
    """, (
        channel_id, admin_id, "channel_admin channel_user", now, 0, 0, "{}", now,
        True, True, False, 0, 0, 0
    ))

    # Create individual users for each Discord author (like working script)
    user_cache = {"admin": admin_id}

    def create_user_for_author(author_data):
        if not author_data:
            return admin_id

        author_name = author_data.get("global_name") or author_data.get("username") or "Anonymous"
        username = author_name.lower().replace(" ", "").replace("@", "").replace("#", "")[:20]
        if not username or not username[0].isalpha():
            username = "anonymous"

        if username in user_cache:
            return user_cache[username]

        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        if result:
            user_cache[username] = result[0]
            return result[0]

        # Create user with FULL schema (like working script)
        user_id = str(uuid.uuid4()).replace("-", "")[:26]
        password_hash = bcrypt.hashpw("password123".encode(), bcrypt.gensalt()).decode()

        cursor.execute("""
            INSERT INTO users (
                id, createat, updateat, deleteat, username, password, authdata, authservice, email,
                emailverified, nickname, firstname, lastname, roles, allowmarketing, props, notifyprops,
                lastpasswordupdate, lastpictureupdate, failedattempts, locale, mfaactive, mfasecret,
                position, timezone
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, now, now, 0, username, password_hash, f"discord:{username}", "", f"{username}@discord.com",
            True, author_name, author_name.split()[0] if author_name else username,
            author_name.split()[-1] if len(author_name.split()) > 1 else "", "system_user", False,
            "{}", "{}", now, now, 0, "en", False, "", "", "{}"
        ))

        # Add user to team (CRITICAL)
        cursor.execute("""
            INSERT INTO teammembers (
                teamid, userid, roles, deleteat, schemeuser, schemeadmin, schemeguest, createat
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (teamid, userid) DO NOTHING
        """, (team_id, user_id, "team_user", 0, True, False, False, now))

        # Add user to channel (CRITICAL for UI visibility)
        cursor.execute("""
            INSERT INTO channelmembers (
                channelid, userid, roles, lastviewedat, msgcount, mentioncount, notifyprops, lastupdateat,
                schemeuser, schemeadmin, schemeguest, mentioncountroot, msgcountroot, urgentmentioncount
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (channelid, userid) DO NOTHING
        """, (
            channel_id, user_id, "channel_user", now, 0, 0, "{}", now,
            True, False, False, 0, 0, 0
        ))

        user_cache[username] = user_id
        return user_id

    # Upload messages with proper user attribution and timestamps (like working script)
    uploaded = 0
    for i, msg in enumerate(messages[:500]):  # Limit for performance
        try:
            content = msg.get("content", "").strip()
            if not content:
                continue

            # Parse Discord timestamp (CRITICAL - use original timestamps)
            timestamp_str = msg.get("timestamp")
            if timestamp_str:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                timestamp = int(dt.timestamp() * 1000)
            else:
                timestamp = now

            # Create user for author (like working script)
            author_data = msg.get("author", {})
            user_id = create_user_for_author(author_data)

            # Create post with FULL schema (like working script)
            post_id = str(uuid.uuid4()).replace("-", "")[:26]
            cursor.execute("""
                INSERT INTO posts (
                    id, createat, updateat, deleteat, userid, channelid, rootid, originalid,
                    message, type, props, hashtags, filenames, fileids, hasreactions, editat, ispinned, remoteid
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::json, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s
                )
            """, (
                post_id, timestamp, now, 0, user_id, channel_id, "", "",
                content, "", "{}", "", "[]", "[]", False, 0, False, ""
            ))

            uploaded += 1

            if i % 100 == 0:
                print_info(f"Uploaded {i}/{len(messages)} messages...")

        except Exception as e:
            print_error(f"Failed to upload message {i}: {e}")
            continue

    # Update channel counters (CRITICAL for UI visibility)
    cursor.execute("""
        UPDATE channels
        SET totalmsgcount = (SELECT COUNT(*) FROM posts WHERE channelid = %s),
            lastpostat = COALESCE((SELECT MAX(createat) FROM posts WHERE channelid = %s), 0)
        WHERE id = %s
    """, (channel_id, channel_id, channel_id))

    conn.commit()
    conn.close()

    print_success(f"Uploaded {uploaded} Discord messages with proper user attribution and UI visibility")

except Exception as e:
    print_error(f"Discord upload failed: {e}")
DISCORD_UPLOAD_EOF

    # Run the fixed Discord upload script and capture output
    echo "🔄 Running Discord upload with proper schema..."
    UPLOAD_OUTPUT=$(python3 /tmp/discord_upload_fixed.py 2>/tmp/mattermost_errors.log)
    echo "$UPLOAD_OUTPUT" | grep -E "(🔄|✅|❌|ℹ️|MATTERMOST_TOKEN:)"

    # Extract the API token from the captured output (NOT by running again!)
    MATTERMOST_TOKEN=$(echo "$UPLOAD_OUTPUT" | grep "MATTERMOST_TOKEN:" | cut -d: -f2 | tr -d ' ')

    if [ -n "$MATTERMOST_TOKEN" ]; then
        echo "🔄 Mattermost token extracted successfully"
        echo "ℹ️ Mattermost Token: ${MATTERMOST_TOKEN:0:20}..."
        echo "ℹ️ Mattermost Team: test-demo"

        # Create config.local.json for Mattermost MCP server
        echo "🔄 Creating Mattermost MCP server configuration..."
        mkdir -p /app/mcp-servers/mattermost
        cat > /app/mcp-servers/mattermost/config.local.json << MATTERMOST_CONFIG_EOF
{
  "mattermostUrl": "http://mattermost:8065/api/v4",
  "token": "$MATTERMOST_TOKEN",
  "teamId": "test-demo",
  "monitoring": {
    "enabled": false,
    "schedule": "*/15 * * * *",
    "channels": ["general"],
    "topics": ["general"],
    "messageLimit": 50
  }
}
MATTERMOST_CONFIG_EOF

        echo "✅ Mattermost MCP server config created: /app/mcp-servers/mattermost/config.local.json"
    else
        echo "⚠️ No Mattermost token extracted from setup"
        echo "📋 Checking error log..."
        cat /tmp/mattermost_errors.log
    fi

else
    echo "ℹ️ No Discord data found, skipping Discord upload"
    echo "ℹ️ Checked: /data/mattermost/scraped.json, /data/scraped.json"

    # Generate a Mattermost token even without Discord data for MCP functionality
    echo "🔄 Generating Mattermost API token for MCP integration..."

    # Create a simple admin user and get a token
    MATTERMOST_TOKEN=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d '{"email":"admin@test.com","username":"admin","password":"admin123","first_name":"Admin","last_name":"User"}' \
        http://localhost:8065/api/v4/users 2>/dev/null | jq -r '.id // empty' | head -1)

    if [ -n "$MATTERMOST_TOKEN" ]; then
        # Get actual API token for the user
        MATTERMOST_TOKEN=$(curl -s -X POST \
            -H "Content-Type: application/json" \
            -d '{"description":"MCP Server Token"}' \
            -u admin:admin123 \
            http://localhost:8065/api/v4/users/me/tokens 2>/dev/null | jq -r '.token // empty')
    fi

    # If token generation fails, create a placeholder that at least allows connection attempts
    if [ -z "$MATTERMOST_TOKEN" ]; then
        echo "⚠️ Could not generate Mattermost token, using minimal config"
        MATTERMOST_TOKEN="minimal_config_token"
    fi

    echo "ℹ️ Generated Mattermost Token: ${MATTERMOST_TOKEN:0:20}..."
fi

# Build Mattermost MCP server (always, regardless of Discord data)
if [ -d "/app/mcp-servers/mattermost" ]; then
    echo "🔄 Building Mattermost MCP server..."
    cd /app/mcp-servers/mattermost
    npm install && npm run build
    echo "✅ Mattermost MCP server built successfully"
    cd /app
fi

# Always update MCP config and create config.local.json (moved outside conditional)
if [ -n "$MATTERMOST_TOKEN" ]; then
    echo "🔄 Updating MCP configuration with Mattermost token..."

    # Ensure config directory exists
    mkdir -p /config

    # Add Mattermost config to MCP config file
    echo "🔄 Adding Mattermost configuration to MCP config..."

    # Simply append Mattermost config to the file (use 'mattermost' hostname for consistency)
    echo "export MATTERMOST_URL=http://mattermost:8065" >> /config/mcp-config.txt
    echo "export MATTERMOST_TOKEN=$MATTERMOST_TOKEN" >> /config/mcp-config.txt
    echo "export MATTERMOST_ENDPOINT=http://mattermost:8065/api/v4" >> /config/mcp-config.txt
    echo "export MATTERMOST_TEAM=test-demo" >> /config/mcp-config.txt

    echo "✅ Mattermost config added to MCP config"
    echo "ℹ️ Mattermost Token: ${MATTERMOST_TOKEN:0:20}..."
    echo "ℹ️ Mattermost Team: test-demo"

    # Create config.local.json for Mattermost MCP server in shared config volume
    echo "🔄 Creating Mattermost MCP server configuration..."
    cat > /config/mattermost-mcp-config.json << MATTERMOST_CONFIG_EOF
{
  "mattermostUrl": "http://mattermost:8065/api/v4",
  "token": "$MATTERMOST_TOKEN",
  "teamId": "test-demo",
  "monitoring": {
    "enabled": false,
    "schedule": "*/15 * * * *",
    "channels": ["general"],
    "topics": ["general"],
    "messageLimit": 50
  }
}
MATTERMOST_CONFIG_EOF

    echo "✅ Mattermost MCP server config created: /config/mattermost-mcp-config.json"
else
    echo "⚠️ No Mattermost token available, skipping MCP config update"
fi

# Keep Mattermost running
echo "🎉 Mattermost initialization completed!"
wait $MATTERMOST_PID
