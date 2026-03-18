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

# Create users table and insert dummy data
echo "🔄 Creating users table and inserting dummy data..."
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB << 'SQL'
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert dummy data
INSERT INTO users (first_name, last_name, email) VALUES
    ('John', 'Doe', 'john.doe@example.com'),
    ('Jane', 'Smith', 'jane.smith@example.com'),
    ('Bob', 'Johnson', 'bob.johnson@example.com'),
    ('Alice', 'Williams', 'alice.williams@example.com'),
    ('Charlie', 'Brown', 'charlie.brown@example.com'),
    ('David', 'Miller', 'david.miller@example.com'),
    ('Emma', 'Davis', 'emma.davis@example.com'),
    ('Michael', 'Wilson', 'michael.wilson@example.com'),
    ('Sarah', 'Moore', 'sarah.moore@example.com'),
    ('James', 'Taylor', 'james.taylor@example.com'),
    ('Lisa', 'Anderson', 'lisa.anderson@example.com')
ON CONFLICT (email) DO NOTHING;

-- Insert additional users with 2023 dates
INSERT INTO users (first_name, last_name, email, created_at, updated_at) VALUES
    ('Robert', 'Garcia', 'robert.garcia@example.com', '2023-01-15 10:30:00', '2023-01-15 10:30:00'),
    ('Maria', 'Rodriguez', 'maria.rodriguez@example.com', '2023-03-22 14:45:00', '2023-03-22 14:45:00'),
    ('Kevin', 'Martinez', 'kevin.martinez@example.com', '2023-05-10 09:15:00', '2023-05-10 09:15:00'),
    ('Jennifer', 'Lopez', 'jennifer.lopez@example.com', '2023-07-08 16:20:00', '2023-07-08 16:20:00'),
    ('Thomas', 'Gonzalez', 'thomas.gonzalez@example.com', '2023-09-14 11:00:00', '2023-09-14 11:00:00'),
    ('Patricia', 'Hernandez', 'patricia.hernandez@example.com', '2023-11-25 13:30:00', '2023-11-25 13:30:00')
ON CONFLICT (email) DO NOTHING;
SQL

if [ $? -eq 0 ]; then
    echo "✅ Users table created and dummy data inserted successfully!"
else
    echo "❌ Failed to create users table or insert dummy data"
    exit 1
fi

echo "PostgreSQL setup complete!"
echo "Database URL: $DATABASE_URL"

# ===== TOOL SETUP CODE =====

# Plane entrypoint setup (optional)
# Add runtime setup code here if your task needs it
# EspoCRM entrypoint setup (optional)
# Add runtime setup code here if your task needs it

# Ensure PostgreSQL service stops when container stops
trap 'echo "Stopping PostgreSQL service..."; service postgresql stop || true' EXIT

# Create signal file to indicate setup is complete
touch /tmp/postgres_ready

echo "Integration task environment initialization completed!"
echo "Ready for integration testing..."

# Keep container running (similar to original sleep infinity)
exec "$@"
