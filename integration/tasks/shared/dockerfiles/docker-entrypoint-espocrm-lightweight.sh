#!/usr/bin/env bash
set -euo pipefail

log(){ printf "[startup] %s\n" "$*"; }

DATA="${POSTGRES_DATA:-/var/lib/postgresql/data}"

# Detect Debian Postgres bindir (e.g., /usr/lib/postgresql/15/bin)
if command -v psql >/dev/null 2>&1; then
  PGVER="$(psql --version | awk '{print $3}' | cut -d. -f1)"
else
  echo "[startup] ERROR: psql not found" >&2; exit 1
fi
BINDIR="/usr/lib/postgresql/${PGVER}/bin"
export PATH="$BINDIR:$PATH"

log "PostgreSQL ${PGVER}, data dir: ${DATA}"
mkdir -p "$DATA"
chown -R postgres:postgres "$DATA"

# Initialize cluster if empty
if [ ! -s "$DATA/PG_VERSION" ]; then
  log "Running initdb…"
  su -s /bin/bash -c "initdb -D '$DATA' --encoding=UTF8" postgres
  # Bind only to loopback; trust only local connections
  { echo "listen_addresses = '127.0.0.1'"; } >> "$DATA/postgresql.conf"
  cat > "$DATA/pg_hba.conf" <<'HBA'
local   all   all                 trust
host    all   all   127.0.0.1/32  trust
HBA
  chown postgres:postgres "$DATA/postgresql.conf" "$DATA/pg_hba.conf"
fi

# Start Postgres in background, log to a file the postgres user owns
log "Starting postgres…"
su -s /bin/bash -c "nohup postgres -D '$DATA' \
  -c shared_buffers='${PG_SHARED_BUFFERS:-256MB}' \
  -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
  >> '$DATA/postgres.log' 2>&1 & disown" postgres

# Wait until it's accepting connections
log "Waiting for postgres on 127.0.0.1:5432…"
for i in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -p 5432 -q; then
    log "Postgres is ready."
    break
  fi
  sleep 1
  if [ "$i" -eq 60 ]; then
    log "ERROR: Postgres did not become ready in time. Tail: $(tail -n 20 "$DATA/postgres.log" 2>/dev/null || true)"
    exit 1
  fi
done

# Ensure role & DB exist
PSQL="psql -v ON_ERROR_STOP=1 --username=postgres"
su -s /bin/bash -c "$PSQL -tc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\" | grep -q 1 || $PSQL -c \"CREATE ROLE \\\"${POSTGRES_USER}\\\" LOGIN PASSWORD '${POSTGRES_PASSWORD}';\"" postgres
su -s /bin/bash -c "$PSQL -tc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\" | grep -q 1 || $PSQL -c \"CREATE DATABASE \\\"${POSTGRES_DB}\\\" OWNER \\\"${POSTGRES_USER}\\\" ENCODING 'UTF8';\"" postgres
log "Role & DB ensured."

# Check if EspoCRM tables exist - if not, force reinstall
log "Checking if EspoCRM database schema exists..."
TABLE_EXISTS=$(su -s /bin/bash -c "$PSQL -d ${POSTGRES_DB} -tc \"SELECT 1 FROM information_schema.tables WHERE table_name='user' LIMIT 1;\"" postgres 2>/dev/null | tr -d ' ' || echo "")
if [ "$TABLE_EXISTS" != "1" ]; then
  log "EspoCRM tables missing - forcing reinstall by removing all config files..."
  rm -f /var/www/html/data/config.php /var/www/html/data/config-internal.php 2>/dev/null || true
  # Also reset the install config that marks it as installed
  mkdir -p /var/www/html/install
  echo "<?php return array('isInstalled' => false);" > /var/www/html/install/config.php
  chown -R www-data:www-data /var/www/html/install 2>/dev/null || true
  log "Config files reset, EspoCRM will run fresh install"
fi

# Hand off to Espo / Apache
log "Starting Apache/Espo in background…"

# Run the official EspoCRM entrypoint which sets up the application and starts Apache
# This was preserved by the Dockerfile at build time
if [ -f /usr/local/bin/espocrm-original-entrypoint.sh ]; then
  log "Running preserved original EspoCRM entrypoint..."
  /usr/local/bin/espocrm-original-entrypoint.sh apache2-foreground &
  APACHE_PID=$!
else
  # Fallback: try common entrypoint locations
  log "WARNING: Preserved entrypoint not found, trying fallbacks..."
  if [ -f /entrypoint.sh ]; then
    /entrypoint.sh apache2-foreground &
    APACHE_PID=$!
  elif command -v apache2-foreground >/dev/null 2>&1; then
    log "WARNING: Starting Apache directly - EspoCRM may not be properly set up"
    apache2-foreground &
    APACHE_PID=$!
  else
    log "ERROR: No way to start Apache found"
    exit 1
  fi
fi

log "Apache/EspoCRM started with PID: $APACHE_PID"

# Wait for EspoCRM API to be ready
log "Waiting for EspoCRM API to be ready..."
BASE_URL="http://localhost:80"
ADMIN_USER="${ESPOCRM_ADMIN_USERNAME:-admin}"
ADMIN_PASS="${ESPOCRM_ADMIN_PASSWORD:-ChangeMe123}"

for i in {1..30}; do
  if curl -s -f -u "${ADMIN_USER}:${ADMIN_PASS}" "${BASE_URL}/api/v1/App/user" > /dev/null 2>&1; then
    log "EspoCRM API is ready!"
    break
  fi
  log "Waiting for API... (attempt $i/30)"
  sleep 2
done

# === Generate API key and add to MCP config ===
log "Generating API key for MCP integration..."

TS="$(date +%s)"
ROLE_NAME="all-permissions-${TS}"
API_USER_NAME="integration-bot-${TS}"

auth() { curl -sS -u "${ADMIN_USER}:${ADMIN_PASS}" "$@"; }

log "Discovering ACL scopes & actions..."
ACL_JSON="$(auth "${BASE_URL}/api/v1/Metadata?key=aclDefs")"
SCOPES_JSON="$(auth "${BASE_URL}/api/v1/Metadata?key=scopes")"

# Build Role.data from aclDefs (give broad permissions to all scopes)
log "Building role data..."
ROLE_DATA="$(
  jq -n \
    --argjson aclDefs "${ACL_JSON}" \
    --argjson scopes "${SCOPES_JSON}" \
    --argjson def '["create","read","edit","delete","stream"]' '
      $aclDefs
      | to_entries
      | map(
          select(
            ($scopes[.key].acl // false) != false and
            ($scopes[.key].acl // false) != "boolean"
          )
          | . as $scope
          | $scopes[.key] as $scopeMeta
          | ($scopeMeta.aclActionList // (.value.aclActionList // $def)) as $actions
          | ($scopeMeta.aclLevelList // ["yes","all","team","own","no"]) as $defaultLevels
          | {
              key: .key,
              value: (
                $actions
                | reduce .[] as $act ({};
                    . + {
                      ($act): (
                        ($scopeMeta.aclActionLevelListMap[$act] // $defaultLevels) as $levels
                        | if ($act == "create") then
                            (if ($levels | index("yes")) then "yes"
                             elif ($levels | index("all")) then "all"
                             elif ($levels | index("own")) then "own"
                             elif ($levels | index("team")) then "team"
                             else "no" end)
                          else
                            (if ($levels | index("all")) then "all"
                             elif ($levels | index("yes")) then "yes"
                             elif ($levels | index("team")) then "team"
                             elif ($levels | index("own")) then "own"
                             else "no" end)
                          end
                      )
                    }
                  )
              )
            }
        )
      | from_entries
    '
)"

log "Discovering Role fields & enums..."
ROLE_FIELDS="$(auth "${BASE_URL}/api/v1/Metadata?key=entityDefs.Role.fields")"

# Build the "special permissions" object based on what fields the server supports
SPECIALS_JSON="$(
  printf '%s' "${ROLE_FIELDS}" | jq '
    def pick($opts; $prefs):
      reduce $prefs[] as $p (null;
        if . == null and ($opts | index($p)) then $p else . end
      );

    def add_field($f; $prefs):
      if has($f) then
        (.[ $f ].options // []) as $opts
        | (pick($opts; $prefs)) as $v
        | if $v then { ($f): $v } else {} end
      else {} end;

    add_field("assignmentPermission"; ["all","team","no"])
    + add_field("userPermission";   ["all","team","no"])
    + add_field("messagePermission";   ["all","team","no"])
    + add_field("portalPermission";    ["yes","no"])
    + add_field("groupEmailAccountPermission"; ["all","team","no"])
    + add_field("exportPermission";    ["yes","no"])
    + add_field("massUpdatePermission";["yes","no"])
    + add_field("dataPrivacyPermission"; ["yes","no"])
    + add_field("followerManagementPermission"; ["all","team","no"])
    + add_field("auditPermission";     ["yes","no"])
    + add_field("mentionPermission";   ["all","team","no"])
    + add_field("userCalendarPermission"; ["all","team","no"])
  '
)"

log "Creating Role '${ROLE_NAME}'..."
ROLE_PAYLOAD="$(jq -n \
  --arg name "${ROLE_NAME}" \
  --argjson data "${ROLE_DATA}" \
  --argjson specials "${SPECIALS_JSON}" \
  '{name:$name, isActive:true, data:$data} + $specials'
)"

ROLE_RES="$(curl -sS -u "${ADMIN_USER}:${ADMIN_PASS}" -X POST "${BASE_URL}/api/v1/Role" \
  -H "Content-Type: application/json" -d "${ROLE_PAYLOAD}")"

ROLE_ID="$(echo "$ROLE_RES" | jq -r '.id // empty')"
if [ -z "${ROLE_ID}" ] || [ "${ROLE_ID}" = "null" ]; then
  log "Warning: Could not create role. Response: ${ROLE_RES}"
  log "Continuing anyway..."
else
  log "Created Role id=${ROLE_ID}"
fi

log "Creating API User '${API_USER_NAME}'..."
API_USER_PAYLOAD="$(jq -n --arg name "${API_USER_NAME}" --arg rid "${ROLE_ID}" \
  '{userName:$name, type:"api", authMethod:"ApiKey", rolesIds:[$rid]}')"

API_USER_RES="$(curl -sS -u "${ADMIN_USER}:${ADMIN_PASS}" -X POST "${BASE_URL}/api/v1/User" \
  -H "Content-Type: application/json" -d "${API_USER_PAYLOAD}")"

API_USER_ID="$(echo "$API_USER_RES" | jq -r '.id // empty')"
if [ -z "${API_USER_ID}" ] || [ "${API_USER_ID}" = "null" ]; then
  log "Warning: Could not create API user. Response: ${API_USER_RES}"
  log "Continuing anyway..."
else
  log "Created API User id=${API_USER_ID}"
  
  # Fetch API key
  log "Fetching API key..."
  API_USER_FETCH="$(auth "${BASE_URL}/api/v1/User/${API_USER_ID}?select=id,userName,apiKey")"
  API_KEY="$(echo "$API_USER_FETCH" | jq -r '.apiKey // empty')"
  
  if [ -n "$API_KEY" ] && [ "$API_KEY" != "null" ]; then
    log "API key created: $API_KEY"
    
    # Add EspoCRM config to MCP config file
    if [ -d "/config" ]; then
      log "Adding EspoCRM configuration to MCP config..."
      echo "export ESPOCRM_URL=http://espocrm:80" >> /config/mcp-config.txt
      echo "export ESPOCRM_API_KEY=$API_KEY" >> /config/mcp-config.txt
      echo "export ESPOCRM_AUTH_METHOD=apikey" >> /config/mcp-config.txt
      log "EspoCRM config added to MCP config"
      log "EspoCRM URL: http://espocrm:80/api/v1"
      log "EspoCRM API Key: $API_KEY"
      log "EspoCRM Auth Method: apikey"
    else
      log "No /config directory found, skipping MCP config update"
      log "Generated API key: $API_KEY"
    fi
  else
    log "Failed to fetch API key"
    log "Response: $API_USER_FETCH"
  fi
fi

# === Seed data from JSON file ===
SEED_FILE="/data/espocrm-data.json"
if [ -f "$SEED_FILE" ]; then
  log "Found seed data file, loading..."
  
  # Helper function to create entity and store ID
  create_entity() {
    local entity_type="$1"
    local payload="$2"
    local result
    local http_code
    
    # Include HTTP status code in response
    result="$(curl -sS -w "\nHTTP_CODE:%{http_code}" -u "${ADMIN_USER}:${ADMIN_PASS}" \
      -X POST "${BASE_URL}/api/v1/${entity_type}" \
      -H "Content-Type: application/json" \
      -d "${payload}")"
    
    http_code=$(echo "$result" | grep "HTTP_CODE:" | cut -d: -f2)
    result=$(echo "$result" | grep -v "HTTP_CODE:")
    
    local entity_id
    # Handle both object responses and array error responses
    entity_id="$(echo "$result" | jq -r 'if type == "object" then .id // empty else empty end' 2>/dev/null || echo "")"
    
    if [ -n "$entity_id" ] && [ "$entity_id" != "null" ]; then
      log "Created ${entity_type}: ${entity_id}" >&2
      echo "$entity_id"
    else
      log "Warning: Could not create ${entity_type} (HTTP $http_code): $result" >&2
      echo ""
    fi
  }
  
  # Create Accounts first (they're referenced by other entities)
  log "Seeding Accounts..."
  declare -A account_ids
  account_count=$(jq '.accounts | length' "$SEED_FILE")
  
  for i in $(seq 0 $((account_count - 1))); do
    account_data=$(jq ".accounts[$i]" "$SEED_FILE")
    account_name=$(echo "$account_data" | jq -r '.name')
    
    # First check if account already exists (use printf to avoid trailing newline)
    encoded_name=$(printf '%s' "$account_name" | jq -sRr @uri)
    existing_id=$(curl -sS -u "${ADMIN_USER}:${ADMIN_PASS}" \
      "${BASE_URL}/api/v1/Account?select=id,name&where%5B0%5D%5Btype%5D=equals&where%5B0%5D%5Battribute%5D=name&where%5B0%5D%5Bvalue%5D=${encoded_name}" \
      -H "Content-Type: application/json" 2>/dev/null | jq -r '.list[0].id // empty' 2>/dev/null || echo "")
    
    if [ -n "$existing_id" ] && [ "$existing_id" != "null" ]; then
      log "Account '${account_name}' already exists with ID: ${existing_id}"
      account_ids["$account_name"]="$existing_id"
    else
      # Add small delay between API calls to avoid rate limiting
      sleep 0.5
      account_id=$(create_entity "Account" "$account_data")
      if [ -n "$account_id" ] && [ "$account_id" != "null" ]; then
        account_ids["$account_name"]="$account_id"
      else
        # Retry once after short delay
        log "Retrying Account creation for '${account_name}'..."
        sleep 1
        account_id=$(create_entity "Account" "$account_data")
        if [ -n "$account_id" ] && [ "$account_id" != "null" ]; then
          account_ids["$account_name"]="$account_id"
        fi
      fi
    fi
  done
  
  # Create Contacts (link to accounts if they exist)
  log "Seeding Contacts..."
  contact_count=$(jq '.contacts | length' "$SEED_FILE")
  
  for i in $(seq 0 $((contact_count - 1))); do
    contact_data=$(jq ".contacts[$i]" "$SEED_FILE")
    account_name=$(echo "$contact_data" | jq -r '.accountName // empty')
    
    # If account exists, add accountId to payload
    if [ -n "$account_name" ] && [ -n "${account_ids[$account_name]:-}" ]; then
      account_id="${account_ids[$account_name]:-}"
      contact_data=$(echo "$contact_data" | jq --arg aid "$account_id" '. + {accountId: $aid} | del(.accountName)')
    else
      contact_data=$(echo "$contact_data" | jq 'del(.accountName)')
    fi
    
    create_entity "Contact" "$contact_data"
  done
  
  # Create Leads
  log "Seeding Leads..."
  lead_count=$(jq '.leads | length' "$SEED_FILE")
  
  for i in $(seq 0 $((lead_count - 1))); do
    lead_data=$(jq ".leads[$i]" "$SEED_FILE")
    create_entity "Lead" "$lead_data"
  done
  
  # Delete existing opportunities to avoid duplicates from previous runs - no artificial limits
  log "Cleaning up existing opportunities..."
  existing_opps=$(curl -sS -u "${ADMIN_USER}:${ADMIN_PASS}" \
    "${BASE_URL}/api/v1/Opportunity?select=id&maxSize=10000" \
    -H "Content-Type: application/json" 2>/dev/null | jq -r '.list[].id // empty' 2>/dev/null || echo "")
  for opp_id in $existing_opps; do
    if [ -n "$opp_id" ]; then
      curl -sS -X DELETE -u "${ADMIN_USER}:${ADMIN_PASS}" \
        "${BASE_URL}/api/v1/Opportunity/${opp_id}" \
        -H "Content-Type: application/json" 2>/dev/null || true
    fi
  done
  log "Cleaned up existing opportunities"

  # Create Opportunities (link to accounts if they exist)
  log "Seeding Opportunities..."
  opp_count=$(jq '.opportunities | length' "$SEED_FILE")
  
  for i in $(seq 0 $((opp_count - 1))); do
    opp_data=$(jq ".opportunities[$i]" "$SEED_FILE")
    account_name=$(echo "$opp_data" | jq -r '.accountName // empty')
    
    # If account exists, add accountId to payload
    if [ -n "$account_name" ] && [ -n "${account_ids[$account_name]:-}" ]; then
      account_id="${account_ids[$account_name]:-}"
      opp_data=$(echo "$opp_data" | jq --arg aid "$account_id" '. + {accountId: $aid} | del(.accountName)')
    else
      opp_data=$(echo "$opp_data" | jq 'del(.accountName)')
    fi
    
    create_entity "Opportunity" "$opp_data"
  done
  
  log "Data seeding completed!"
  # Write marker file so the harness knows seed data is ready
  touch /config/.espocrm-seed-complete
else
  log "No seed data file found at $SEED_FILE, skipping..."
  # Still write marker - no seed data to wait for
  touch /config/.espocrm-seed-complete
fi

log "All services started. EspoCRM should be available"

# Keep container running by waiting on Apache process
log "Waiting on Apache (PID: $APACHE_PID) to keep container alive..."
wait $APACHE_PID
