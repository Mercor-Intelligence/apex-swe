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
# EspoCRM entrypoint setup (optional)
# Add runtime setup code here if your task needs it
# Localstack entrypoint setup (optional)
# Add runtime setup code here if your task needs it

# Create symlink for test compatibility
ln -sf /app/solution.py /app/renewal_flow.py
# Ensure PostgreSQL service stops when container stops
trap 'echo "Stopping PostgreSQL service..."; service postgresql stop || true' EXIT

# Create signal file to indicate setup is complete
touch /tmp/postgres_ready

echo "Integration task environment initialization completed!"
echo "Ready for integration testing..."

# Keep container running (similar to original sleep infinity)
exec "$@"
