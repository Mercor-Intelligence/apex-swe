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

# Wait for MailHog SMTP to be ready
echo "Waiting for MailHog SMTP to be ready..."
for i in $(seq 1 60); do
  if nc -z mailhog 1025 2>/dev/null; then
    echo "MailHog SMTP is ready on port 1025!"
    sleep 2
    echo "MailHog is ready to receive emails"
    break
  fi
  echo "   MailHog SMTP not ready, waiting... ($i/60)"
  sleep 2
done

# Check if MailHog is ready
if ! nc -z mailhog 1025 2>/dev/null; then
  echo "Warning: MailHog SMTP may not be fully ready"
fi

# Seed test email to MailHog - with retries and verification
echo "Sending test email to MailHog..."
python3 << 'EOF'
import smtplib
from email.message import EmailMessage
import time
import urllib.request
import json
import sys

# Retry logic for sending email
max_retries = 5
for attempt in range(max_retries):
    try:
        msg = EmailMessage()
        msg['From'] = 'support@example.com'
        msg['To'] = 'team@example.com'
        msg['Subject'] = 'Customer Support Request'
        msg.set_content('Hello, I need help with my account. Please assist me as soon as possible. Thank you!')

        with smtplib.SMTP('mailhog', 1025, timeout=30) as smtp:
            smtp.send_message(msg)
        print(f"✓ Test email sent to MailHog (attempt {attempt + 1})")
        break
    except Exception as e:
        print(f"   Attempt {attempt + 1} failed: {e}")
        if attempt < max_retries - 1:
            time.sleep(3)
        else:
            print("ERROR: Failed to send email after all retries")
            sys.exit(1)

# Verify email was received
time.sleep(2)
try:
    req = urllib.request.Request('http://mailhog:8025/api/v2/messages')
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        if data.get('total', 0) >= 1:
            print(f"✓ Verified: MailHog has {data['total']} email(s)")
        else:
            print("WARNING: MailHog shows 0 emails after sending")
except Exception as e:
    print(f"WARNING: Could not verify email in MailHog: {e}")
EOF

# Plane entrypoint setup (optional)
# Add runtime setup code here if your task needs it

# Ensure PostgreSQL service stops when container stops
trap 'echo "Stopping PostgreSQL service..."; service postgresql stop || true' EXIT

# Create signal file to indicate setup is complete
touch /tmp/postgres_ready

echo "Integration task environment initialization completed!"
echo "Ready for integration testing..."

# Keep container running (similar to original sleep infinity)
exec "$@"
