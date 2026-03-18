#!/bin/bash
# Docker Entrypoint for Integration Task - In-memory PostgreSQL Setup

set -e

echo "Starting integration task with in-memory PostgreSQL"

# Setup PostgreSQL using system service (simpler and more reliable)
echo "Setting up PostgreSQL..."
export POSTGRES_USER="${POSTGRES_USER:-testuser}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-testpass}"
export POSTGRES_DB="${POSTGRES_DB:-testdb}"

# Start PostgreSQL service
echo "Starting PostgreSQL service..."
service postgresql start

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
  if sudo -u postgres pg_isready -h localhost -p 5432; then
    echo "PostgreSQL ready!"
    break
  fi
  echo "   PostgreSQL not ready, waiting... ($i/30)"
  sleep 2
done

# Create database and user
echo "Creating database and user..."
sudo -u postgres createuser --createdb --login "$POSTGRES_USER" 2>/dev/null || echo "User may already exist"
sudo -u postgres createdb -O "$POSTGRES_USER" "$POSTGRES_DB" 2>/dev/null || echo "Database may already exist"
sudo -u postgres psql -c "ALTER USER $POSTGRES_USER PASSWORD '$POSTGRES_PASSWORD';"

# Set environment variables for applications
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo "PostgreSQL setup complete!"
echo "Database URL: $DATABASE_URL"

# ===== TOOL SETUP CODE =====

# Plane entrypoint setup (optional)
# Add runtime setup code here if your task needs it

# Zammad entrypoint setup - Wait for ticket 5 to exist
echo "Setting up Zammad test data..."

ZAMMAD_URL="http://zammad:8080"
ZAMMAD_USER="admin@example.com"
ZAMMAD_PASS="StrongPassw0rd@()"

# Wait for Zammad API to be ready and for ticket 5 to exist
# The Zammad container loads data from zammad-data.json which creates 5 tickets
echo "Waiting for Zammad API and ticket 5 to be ready..."
TICKET_CHECK="000"
for i in $(seq 1 60); do
  # Check if ticket 5 exists (suppress errors to not trigger set -e)
  TICKET_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "$ZAMMAD_URL/api/v1/tickets/5" -u "$ZAMMAD_USER:$ZAMMAD_PASS" 2>/dev/null || echo "000")
  if [ "$TICKET_CHECK" = "200" ]; then
    echo "✅ Ticket 5 exists and is ready!"
    break
  fi
  echo "   Ticket 5 not ready (status: $TICKET_CHECK), waiting... ($i/60)"
  sleep 3
done

# If ticket 5 still doesn't exist, create tickets until we have one
if [ "$TICKET_CHECK" != "200" ]; then
  echo "Ticket 5 not found after waiting. Creating tickets..."
  
  for j in $(seq 1 5); do
    TICKET_RESPONSE=$(curl -s -X POST "$ZAMMAD_URL/api/v1/tickets" \
      -u "$ZAMMAD_USER:$ZAMMAD_PASS" \
      -H "Content-Type: application/json" \
      -d "{
        \"title\": \"Test Webhook Ticket $j\",
        \"group\": \"Users\",
        \"state\": \"open\",
        \"priority\": \"2 normal\",
        \"customer\": \"admin@example.com\",
        \"article\": {
          \"subject\": \"Test Webhook Ticket $j\",
          \"body\": \"Test ticket for webhook integration testing.\",
          \"type\": \"note\",
          \"internal\": false
        }
      }" 2>/dev/null || true)
    
    if echo "$TICKET_RESPONSE" | grep -q '"id"' 2>/dev/null; then
      TICKET_ID=$(echo "$TICKET_RESPONSE" | grep -o '"id":[0-9]*' 2>/dev/null | head -1 | cut -d':' -f2 || echo "0")
      echo "Created ticket with ID: $TICKET_ID"
      if [ "$TICKET_ID" -ge 5 ] 2>/dev/null; then
        echo "✅ Ticket 5 now exists!"
        break
      fi
    fi
  done
fi

echo "Zammad setup complete (or skipped if unavailable)"

# Ensure PostgreSQL service stops when container stops
trap 'echo "Stopping PostgreSQL service..."; service postgresql stop || true' EXIT

# Create signal file to indicate setup is complete
touch /tmp/postgres_ready

echo "Integration task environment initialization completed!"
echo "Ready for integration testing..."

# Keep container running (similar to original sleep infinity)
exec "$@"
