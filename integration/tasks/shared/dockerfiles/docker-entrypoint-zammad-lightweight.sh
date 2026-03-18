#!/usr/bin/env bash
set -euo pipefail

# ---- Config (defaults can be overridden by env) ----
: "${ZAMMAD_FQDN:=localhost}"
: "${TZ:=Etc/UTC}"

# DB settings for local in-container Postgres
: "${POSTGRESQL_DB:=zammad_production}"
: "${POSTGRESQL_USER:=zammad}"
: "${POSTGRESQL_PASS:=zammad}"
PGDATA="/var/lib/postgresql/data"

# Point Zammad at in-container services
export POSTGRESQL_HOST=127.0.0.1
export POSTGRESQL_PORT=${POSTGRES_PORT:-5432}
export REDIS_URL="redis://127.0.0.1:6379"
export MEMCACHE_SERVERS="127.0.0.1:11211"
# Turn off ES for simplicity
export ELASTICSEARCH_ENABLED="${ELASTICSEARCH_ENABLED:-false}"

# Nginx port (matches the official image default)
export NGINX_PORT="${NGINX_PORT:-8080}"

# Rails environment
export RAILS_ENV=production
export RACK_ENV=production

# Make sure timezone is set coherently in container
ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime && echo "$TZ" > /etc/timezone

_term() {
  echo "Caught SIGTERM, stopping services..."
  # Try graceful stops
  supervisor_stop || true
  exit 0
}

supervisor_stop() {
  # Stop Zammad stack processes started below
  pkill -TERM -f "zammad-railsserver" || true
  pkill -TERM -f "zammad-scheduler" || true
  pkill -TERM -f "zammad-websocket" || true
  pkill -TERM -f "nginx: master" || true
  # Stop redis/memcached/postgres
  service redis-server stop || true
  service memcached stop || true
  # Find pg_ctl for stopping postgres
  PG_CTL=$(find /usr/lib/postgresql -name pg_ctl -type f 2>/dev/null | head -n1)
  if [ -n "$PG_CTL" ]; then
    su - postgres -c "'$PG_CTL' -D '$PGDATA' -m fast stop" || true
  fi
}

trap _term SIGTERM SIGINT

echo "==> Starting Redis"
service redis-server start

echo "==> Starting Memcached"
# 256MB is more than enough for local testing
# Use -v for verbose, -vv for very verbose, or omit for quiet
MEMCACHED_PARAMS=${MEMCACHED_PARAMS:-"-m 256 -u nobody"}
# Use system service for simplicity (params via env not trivial), or run directly:
service memcached stop || true
memcached $MEMCACHED_PARAMS &

# Find the Postgres binary path dynamically
PG_BIN=$(find /usr/lib/postgresql -name pg_ctl -type f 2>/dev/null | head -n1 | xargs dirname)
if [ -z "$PG_BIN" ]; then
  echo "ERROR: Could not find PostgreSQL binaries"
  exit 1
fi
echo "Found PostgreSQL binaries at: $PG_BIN"

echo "==> Preparing Postgres"
# Check if data directory exists and get its version
if [ -s "$PGDATA/PG_VERSION" ]; then
  DATA_VERSION=$(cat "$PGDATA/PG_VERSION")
  # Get current PostgreSQL major version
  CURRENT_VERSION=$("$PG_BIN/postgres" --version | grep -oP '\d+' | head -1)
  
  echo "Found existing data directory with PostgreSQL version $DATA_VERSION"
  echo "Current PostgreSQL version is $CURRENT_VERSION"
  
  if [ "$DATA_VERSION" != "$CURRENT_VERSION" ]; then
    echo "WARNING: PostgreSQL version mismatch!"
    echo "Data directory was initialized with version $DATA_VERSION but current version is $CURRENT_VERSION"
    echo "Backing up old data and reinitializing..."
    
    # Backup old data directory
    BACKUP_DIR="${PGDATA}.backup.v${DATA_VERSION}.$(date +%s)"
    mv "$PGDATA" "$BACKUP_DIR"
    echo "Old data backed up to: $BACKUP_DIR"
    
    # Create fresh data directory
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su - postgres -c "'$PG_BIN/initdb' -D '$PGDATA'"
  else
    echo "PostgreSQL version matches, using existing data directory"
  fi
else
  echo "Initializing new Postgres data dir at $PGDATA"
  mkdir -p "$PGDATA"
  chown -R postgres:postgres "$PGDATA"
  su - postgres -c "'$PG_BIN/initdb' -D '$PGDATA'"
fi

echo "==> Starting Postgres"
su - postgres -c "'$PG_BIN/pg_ctl' -D '$PGDATA' -w start"

# Create DB + user if missing
echo "==> Ensuring database and role exist"
su - postgres -c "'$PG_BIN/psql' -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRESQL_USER}'\"" | grep -q 1 \
  || su - postgres -c "'$PG_BIN/psql' -c \"CREATE ROLE ${POSTGRESQL_USER} LOGIN PASSWORD '${POSTGRESQL_PASS}';\""

su - postgres -c "'$PG_BIN/psql' -tAc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRESQL_DB}'\"" | grep -q 1 \
  || su - postgres -c "'$PG_BIN/createdb' -O ${POSTGRESQL_USER} ${POSTGRESQL_DB}"

# Ensure the app can connect via password
su - postgres -c "'$PG_BIN/psql' -c \"ALTER USER ${POSTGRESQL_USER} WITH PASSWORD '${POSTGRESQL_PASS}';\""

# Find Zammad scripts - they might be in different locations
ZAMMAD_DIR="/opt/zammad"
if [ ! -d "$ZAMMAD_DIR" ]; then
  echo "ERROR: Zammad directory not found at $ZAMMAD_DIR"
  exit 1
fi

# Create database.yml if it doesn't exist
echo "==> Configuring database.yml"
cat > "$ZAMMAD_DIR/config/database.yml" <<EOF
production:
  adapter: postgresql
  database: ${POSTGRESQL_DB}
  username: ${POSTGRESQL_USER}
  password: ${POSTGRESQL_PASS}
  host: ${POSTGRESQL_HOST}
  port: ${POSTGRESQL_PORT}
  encoding: utf8
  pool: 50
EOF
chown zammad:zammad "$ZAMMAD_DIR/config/database.yml"
chmod 600 "$ZAMMAD_DIR/config/database.yml"

# Configure Nginx to proxy to Rails server
echo "==> Configuring Nginx"
cat > /etc/nginx/sites-available/zammad.conf <<'NGINXEOF'
upstream zammad-railsserver {
  server 127.0.0.1:3000;
}

upstream zammad-websocket {
  server 127.0.0.1:6042;
}

server {
  listen 8080;
  server_name _;

  root /opt/zammad/public;

  access_log /var/log/nginx/zammad.access.log;
  error_log  /var/log/nginx/zammad.error.log;

  client_max_body_size 50M;

  location ~ ^/(assets|fonts|images)/ {
    expires max;
    add_header Cache-Control public;
  }

  location /ws {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "Upgrade";
    proxy_set_header CLIENT_IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
    proxy_pass http://zammad-websocket;
  }

  location / {
    proxy_set_header Host $http_host;
    proxy_set_header CLIENT_IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 180;
    proxy_pass http://zammad-railsserver;

    gzip on;
    gzip_types text/plain text/xml text/css image/svg+xml application/javascript application/x-javascript application/json application/xml;
    gzip_proxied any;
  }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/zammad.conf /etc/nginx/sites-enabled/zammad.conf
rm -f /etc/nginx/sites-enabled/default

# Enable AutoWizard if config file exists (must be set before starting services)
if [ -f /usr/local/bin/zammad-auto-wizard.json ]; then
  echo "==> Enabling Auto-Wizard"
  export AUTOWIZARD_JSON="$(cat /usr/local/bin/zammad-auto-wizard.json)"
fi

# Check if Zammad wrapper scripts exist, otherwise find them
if command -v zammad-init >/dev/null 2>&1; then
  ZAMMAD_INIT="zammad-init"
  ZAMMAD_RAILSSERVER="zammad-railsserver"
  ZAMMAD_SCHEDULER="zammad-scheduler"
  ZAMMAD_WEBSOCKET="zammad-websocket"
else
  # Scripts might be in /usr/local/bin or we need to use direct commands
  if [ -f "/usr/local/bin/zammad-init" ]; then
    ZAMMAD_INIT="/usr/local/bin/zammad-init"
    ZAMMAD_RAILSSERVER="/usr/local/bin/zammad-railsserver"
    ZAMMAD_SCHEDULER="/usr/local/bin/zammad-scheduler"
    ZAMMAD_WEBSOCKET="/usr/local/bin/zammad-websocket"
  else
    echo "WARNING: Zammad wrapper scripts not found, using direct commands"
    # We'll use gosu to run as zammad user with proper environment
    # Pass AutoWizard env vars if set (append instead of overwrite)
    ENV_VARS=""
    if [ -n "${AUTOWIZARD_JSON:-}" ]; then
      # Safely quote JSON for shell
      ENV_VARS="env AUTOWIZARD_JSON=$(printf %q "$AUTOWIZARD_JSON")"
    fi
    if [ -n "${AUTOWIZARD_RELATIVE_PATH:-}" ]; then
      if [ -n "$ENV_VARS" ]; then
        ENV_VARS="$ENV_VARS AUTOWIZARD_RELATIVE_PATH=$(printf %q "$AUTOWIZARD_RELATIVE_PATH")"
      else
        ENV_VARS="env AUTOWIZARD_RELATIVE_PATH=$(printf %q "$AUTOWIZARD_RELATIVE_PATH")"
      fi
    fi
    ZAMMAD_INIT="$ENV_VARS gosu zammad bash -lc 'cd $ZAMMAD_DIR && bundle exec rake db:migrate && bundle exec rake db:seed'"
    ZAMMAD_RAILSSERVER="$ENV_VARS gosu zammad bash -lc 'cd $ZAMMAD_DIR && bundle exec rails server -b 127.0.0.1 -p 3000'"
    ZAMMAD_SCHEDULER="$ENV_VARS gosu zammad bash -lc 'cd $ZAMMAD_DIR && ./script/background-worker.rb start'"
    ZAMMAD_WEBSOCKET="$ENV_VARS gosu zammad bash -lc 'cd $ZAMMAD_DIR && bundle exec script/websocket-server.rb start -b 127.0.0.1 -p 6042'"
  fi
fi

# === Auto-Wizard (file-based, safest) ===
if [ -f /usr/local/bin/zammad-auto-wizard.json ]; then
  echo "==> Enabling Auto-Wizard"
  install -o zammad -g zammad -m 0644 \
    /usr/local/bin/zammad-auto-wizard.json /opt/zammad/auto_wizard.json
  export AUTOWIZARD_RELATIVE_PATH="auto_wizard.json"
fi


# Run Zammad init (migrations, seeds, etc.)
# This is idempotent; it will skip if already up-to-date.
echo "==> Running zammad-init"
eval $ZAMMAD_INIT

# === Force the wizard once (idempotent) ===
if [ -n "${AUTOWIZARD_RELATIVE_PATH:-}" ]; then
  echo "==> Running Auto-Wizard"
  gosu zammad bash -lc "cd /opt/zammad && bundle exec rails r 'AutoWizard.setup'"
  
  # Mark system as fully initialized to skip setup wizard in UI
  echo "==> Marking system as initialized (skip setup wizard UI)"
  gosu zammad bash -lc "cd /opt/zammad && bundle exec rails r \"Setting.set('system_init_done', true)\""
  gosu zammad bash -lc "cd /opt/zammad && bundle exec rails r \"Setting.set('import_mode', false)\""
fi

# Check if we have JSON data to load later (after API is ready)
ZAMMAD_DATA_FILE=$(find /data -name "zammad-data.json" 2>/dev/null | head -1)

# Start Zammad services (background)
echo "==> Starting Zammad railsserver"
eval $ZAMMAD_RAILSSERVER &

echo "==> Starting Zammad scheduler"
eval $ZAMMAD_SCHEDULER &

echo "==> Starting Zammad websocket"
eval $ZAMMAD_WEBSOCKET &

echo "==> Starting Nginx"
nginx -g 'daemon off;' &

# Wait for Zammad API to be ready
echo "==> Waiting for Zammad API to be ready..."
for i in {1..30}; do
  if curl -s -f http://localhost:8080/api/v1/users/me -u "admin@example.com:StrongPassw0rd@()" > /dev/null 2>&1; then
    echo "==> Zammad API is ready!"
    break
  fi
  echo "Waiting for API... (attempt $i/30)"
  sleep 2
done

# === Load Zammad data from JSON if available ===
if [ -n "$ZAMMAD_DATA_FILE" ]; then
  set -x  # Enable debug mode for this section
  echo "==> Loading Zammad data from JSON: $ZAMMAD_DATA_FILE"
  
  echo "==> Checking if data file is readable..."
  if [ -r "$ZAMMAD_DATA_FILE" ]; then
    echo "==> Data file is readable"
    echo "==> File size: $(stat -c%s "$ZAMMAD_DATA_FILE" 2>/dev/null || stat -f%z "$ZAMMAD_DATA_FILE" 2>/dev/null) bytes"
  else
    echo "ERROR: Data file is not readable"
  fi
  
  echo "==> Creating data upload script..."
  cat > /tmp/zammad_upload.py << 'ZAMMAD_UPLOAD_EOF'
#!/usr/bin/env python3
import json
import time
import requests
import sys

BASE_URL = "http://localhost:8080/api/v1"
AUTH = ("admin@example.com", "StrongPassw0rd@()")

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

print(f"Loading data: {data['metadata']['dataset_name']}")

def api_call(method, endpoint, json_data=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            url = f"{BASE_URL}{endpoint}"
            if method == "GET":
                response = requests.get(url, auth=AUTH, timeout=10)
            elif method == "POST":
                response = requests.post(url, auth=AUTH, json=json_data, timeout=10)
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None
    return None

user_map = {}
org_map = {}
group_map = {}

print(f"Creating {len(data.get('organizations', []))} organizations")
for org in data.get('organizations', []):
    org_data = {
        "name": org["name"],
        "note": org.get("note", ""),
        "active": org.get("active", True)
    }
    if org.get("domain"):
        org_data["domain"] = org["domain"]
    
    result = api_call("POST", "/organizations", org_data)
    if result:
        org_map[org["id"]] = result["id"]
        print(f"Created organization: {org['name']}")

print(f"Setting up {len(data.get('groups', []))} groups")
existing_groups = api_call("GET", "/groups")
if existing_groups:
    for group in data.get('groups', []):
        found = False
        for eg in existing_groups:
            if eg["name"] == group["name"]:
                group_map[group["id"]] = eg["name"]
                print(f"Using existing group: {group['name']}")
                found = True
                break
        if not found:
            group_map[group["id"]] = "Users"

print(f"Creating {len(data.get('users', []))} users")
for user in data.get('users', []):
    user_data = {
        "email": user["email"],
        "firstname": user["firstname"],
        "lastname": user["lastname"],
        "roles": [user.get("role", "Customer")]
    }
    
    if user.get("organization_id") and user["organization_id"] in org_map:
        user_data["organization_id"] = org_map[user["organization_id"]]
    if user.get("phone"):
        user_data["phone"] = user["phone"]
    if user.get("note"):
        user_data["note"] = user["note"]
    
    result = api_call("POST", "/users", user_data)
    if result:
        user_map[user["id"]] = result["id"]
        print(f"Created user: {user['email']}")

print(f"Creating {len(data.get('tickets', []))} tickets")
for ticket in data.get('tickets', []):
    articles = ticket.get('articles', [])
    if not articles:
        continue
    
    first_article = articles[0]
    ticket_data = {
        "title": ticket["title"],
        "group": group_map.get(ticket["group_id"], "Users"),
        "customer_id": user_map.get(ticket["customer_id"]),
        "state": ticket.get("state", "new"),
        "priority": ticket.get("priority", "2 normal"),
        "article": {
            "subject": first_article.get("subject", ticket["title"]),
            "body": first_article["body"],
            "type": first_article.get("type", "note"),
            "internal": first_article.get("internal", False)
        }
    }
    
    if ticket.get("owner_id") and ticket["owner_id"] in user_map:
        ticket_data["owner_id"] = user_map[ticket["owner_id"]]
    if ticket.get("tags"):
        ticket_data["tags"] = ",".join(ticket["tags"])
    
    result = api_call("POST", "/tickets", ticket_data)
    if result:
        ticket_id = result["id"]
        print(f"Created ticket: {ticket['title']}")
        
        for article in articles[1:]:
            article_data = {
                "subject": article.get("subject", "Re: " + ticket["title"]),
                "body": article["body"],
                "type": article.get("type", "note"),
                "internal": article.get("internal", False),
                "sender": article.get("sender", "Customer"),
                "from": article.get("from", user_map.get(article.get("created_by_id"), ""))
            }
            
            api_call("POST", f"/ticket_articles", {"ticket_id": ticket_id, **article_data})

print("Zammad data upload complete")
ZAMMAD_UPLOAD_EOF

  echo "==> Verifying upload script was created..."
  if [ -f /tmp/zammad_upload.py ]; then
    echo "==> Upload script created successfully ($(wc -l < /tmp/zammad_upload.py) lines)"
    echo "==> Running data upload script..."
    set +x  # Disable debug for cleaner Python output
    if python3 /tmp/zammad_upload.py "$ZAMMAD_DATA_FILE"; then
      echo "==> Data upload script completed successfully"
    else
      EXIT_CODE=$?
      echo "ERROR: Data upload script failed with exit code $EXIT_CODE"
      echo "ERROR: Check logs above for Python errors"
      # Don't exit - continue to generate MCP config anyway
    fi
  else
    echo "ERROR: Upload script was not created at /tmp/zammad_upload.py"
  fi
  echo "==> Data loading section complete"
else
  echo "==> No zammad-data.json found, skipping data upload"
fi

# === Generate API token and add to MCP config ===
echo "==> Generating API token for MCP integration..."

# Use the HTTP API endpoint to create an access token
HTTP_TOKEN_RESPONSE=$(curl -s -X POST http://localhost:8080/api/v1/user_access_token \
  -u "admin@example.com:StrongPassw0rd@()" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MCP Integration Token",
    "permission": ["admin", "ticket.agent"]
  }')

# Extract token from JSON response (using grep/sed as jq may not be available)
HTTP_TOKEN=$(echo "$HTTP_TOKEN_RESPONSE" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

if [ -n "$HTTP_TOKEN" ] && [ "$HTTP_TOKEN" != "null" ]; then
  echo "==> API token created: $HTTP_TOKEN"
  
  # Add Zammad config to MCP config file
  if [ -d "/config" ]; then
    echo "==> Adding Zammad configuration to MCP config..."
    echo "export ZAMMAD_URL=http://zammad:8080/api/v1" >> /config/mcp-config.txt
    echo "export ZAMMAD_HTTP_TOKEN=$HTTP_TOKEN" >> /config/mcp-config.txt
    echo "==> Zammad config added to MCP config"
    echo "Zammad URL: http://zammad:8080/api/v1"
    echo "Zammad HTTP Token: $HTTP_TOKEN"
  else
    echo "No /config directory found, skipping MCP config update"
    echo "Generated HTTP token: $HTTP_TOKEN"
  fi
else
  echo "Failed to create HTTP token"
  echo "Response: $HTTP_TOKEN_RESPONSE"
fi


echo "==> All services started. Zammad should be available on http://localhost:${NGINX_PORT}"
# Keep the container in the foreground by tailing logs
# Tail a couple of useful logs; adjust as needed
tail -n+1 -F \
  /var/log/postgresql/postgresql-*.log \
  /var/log/redis/redis-server.log \
  /var/log/nginx/access.log \
  /var/log/nginx/error.log \
  /opt/zammad/log/*.log
