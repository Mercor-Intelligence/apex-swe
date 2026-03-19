#!/bin/bash
# Docker Entrypoint for Plane API in Lightweight Mode
# Runs Django migrations before starting the API server

set -e

echo "🚀 Starting Plane API in lightweight mode (embedded PostgreSQL)"

# Install PostgreSQL and Redis servers (Alpine)
echo "📦 Ensuring PostgreSQL and Redis are installed..."
apk update
apk add --no-cache postgresql postgresql-client redis su-exec

# Start Redis server in background
echo "🔄 Starting Redis server..."
redis-server --daemonize yes --port 6379 --bind 127.0.0.1 --ignore-warnings ARM64-COW-BUG
echo "✅ Redis server started on port 6379"

# Ensure postgres system user exists
if ! id postgres >/dev/null 2>&1; then
  adduser -S -D -H postgres || true
fi

# Setup PostgreSQL data directory in tmpfs
echo "🔄 Setting up in-memory PostgreSQL..."
export PGDATA="/tmp/postgres-data"
export POSTGRES_USER="${POSTGRES_USER:-plane}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-plane_password}"
export POSTGRES_DB="${POSTGRES_DB:-plane}"

# Fix ownership of PostgreSQL data directory
echo "🔄 Setting up PostgreSQL data directory permissions..."
mkdir -p "$PGDATA"
chown -R postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"
# Clean up any stale pid file
rm -f "$PGDATA/postmaster.pid"

# Initialize PostgreSQL database (idempotent)
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  su-exec postgres initdb -D "$PGDATA" --auth-local=trust --auth-host=md5
fi

# Configure PostgreSQL for dev (overwrite to avoid duplicate/conflicts)
cat > "$PGDATA/postgresql.conf" << 'EOF'
listen_addresses = '*'
port = 5432
unix_socket_directories = '/tmp'
# modest shared memory; safe defaults for containers
shared_buffers = 128MB
effective_cache_size = 512MB
max_connections = 200
fsync = off
synchronous_commit = off
checkpoint_completion_target = 0.9
wal_level = minimal
wal_buffers = 8MB
min_wal_size = 80MB
max_wal_size = 256MB
max_wal_senders = 0
default_statistics_target = 100
random_page_cost = 1.1
work_mem = 2MB
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql.log'
log_min_messages = info
EOF

# Configure authentication
cat > "$PGDATA/pg_hba.conf" << 'EOF'
# Allow local connections
local   all             all                                     trust
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
host    all             all             0.0.0.0/0               md5
EOF

echo "🔄 Starting embedded PostgreSQL server..."
su-exec postgres postgres -D "$PGDATA" -k /tmp -i > /tmp/postgres.log 2>&1 &
POSTGRES_PID=$!

# Wait for PostgreSQL to be ready
echo "🔄 Waiting for embedded PostgreSQL to be ready..."
for i in $(seq 1 120); do
  if su-exec postgres pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "✅ Embedded PostgreSQL is ready!"
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "ℹ️ postgres.log (last 40 lines):"
    tail -n 40 /tmp/postgres.log || true
  fi
  echo "   PostgreSQL not ready, waiting... ($i/120)"
  sleep 1
done

# If still not ready, show full log and exit
if ! su-exec postgres pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  echo "❌ PostgreSQL failed to become ready. Full log:"
  (sed -n '1,200p' /tmp/postgres.log || true)
  exit 1
fi

# Create database and user
echo "🔄 Creating database and user..."
# Use simple SQL commands to avoid variable syntax issues
su-exec postgres psql -h /tmp -U postgres -c "CREATE USER $POSTGRES_USER WITH CREATEDB LOGIN;" 2>/dev/null || echo "User may already exist"
su-exec postgres psql -h /tmp -U postgres -c "CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;" 2>/dev/null || echo "Database may already exist"
su-exec postgres psql -h /tmp -U postgres -c "ALTER USER $POSTGRES_USER PASSWORD '$POSTGRES_PASSWORD';"

# Point Django to local embedded Postgres
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

# Run migrations (idempotent - safe to run multiple times)
echo "🔄 Running Django migrations..."
# Debug: Check current directory and contents
echo "📍 Current directory: $(pwd)"
echo "📂 Directory contents:"
ls -la
echo "📂 Checking common locations for manage.py:"
ls -la /code 2>/dev/null || echo "  /code not found"
ls -la /app 2>/dev/null || echo "  /app not found"
ls -la /api 2>/dev/null || echo "  /api not found"
find / -name "manage.py" -type f 2>/dev/null | head -5 || echo "  No manage.py found"

# The makeplane/plane-backend:preview image has the app at /code
cd /code 2>/dev/null || cd /app 2>/dev/null || cd /api 2>/dev/null || echo "⚠️  Could not find app directory"
echo "📍 Now in directory: $(pwd)"
python manage.py migrate --noinput || echo "⚠️  Migration failed"
echo "✅ Migrations completed!"

# Create admin user if it doesn't exist (for API access)
echo "🔄 Creating admin user and basic Plane tables..."
python manage.py shell << 'EOF'
import uuid
from django.contrib.auth import get_user_model
from django.db import connection, transaction

# Check what tables exist
cursor = connection.cursor()
# In lightweight schema creation, avoid relying on DB UUID extensions
cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
existing_tables = [row[0] for row in cursor.fetchall()]
print(f"Existing tables: {existing_tables}")

# Try to use Plane's User model if available, fallback to Django User
User = None
try:
    from plane.db.models import User as PlaneUser
    User = PlaneUser
    print("Using Plane User model")
except ImportError:
    User = get_user_model()
    print("Using Django User model")

# Check if 'users' table exists (expected by upload script)
if 'users' not in existing_tables:
    print("Creating minimal Plane-compatible tables for lightweight mode...")
    # Users table with columns used by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username VARCHAR(150) UNIQUE NOT NULL,
            email VARCHAR(254) UNIQUE NOT NULL,
            first_name VARCHAR(150) DEFAULT '',
            last_name VARCHAR(150) DEFAULT '',
            avatar TEXT DEFAULT '',
            password VARCHAR(255) NOT NULL,
            date_joined TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_location VARCHAR(50) DEFAULT '',
            created_location VARCHAR(50) DEFAULT '',
            is_superuser BOOLEAN DEFAULT FALSE,
            is_managed BOOLEAN DEFAULT FALSE,
            is_password_expired BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            is_staff BOOLEAN DEFAULT FALSE,
            is_email_verified BOOLEAN DEFAULT TRUE,
            is_password_autoset BOOLEAN DEFAULT FALSE,
            token VARCHAR(255) DEFAULT '',
            user_timezone VARCHAR(64) DEFAULT 'UTC',
            last_login_ip VARCHAR(64) DEFAULT '',
            last_logout_ip VARCHAR(64) DEFAULT '',
            last_login_medium VARCHAR(32) DEFAULT 'web',
            last_login_uagent TEXT DEFAULT '',
            is_bot BOOLEAN DEFAULT FALSE,
            display_name VARCHAR(255) DEFAULT '',
            is_email_valid BOOLEAN DEFAULT TRUE
        );
    """)

    # Workspaces table with fields referenced by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(100) UNIQUE NOT NULL,
            created_by_id UUID REFERENCES users(id),
            owner_id UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            timezone VARCHAR(64) DEFAULT 'UTC',
            background_color VARCHAR(16) DEFAULT '#ffffff'
        );
    """)

    # Workspace members table used by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID REFERENCES workspaces(id),
            member_id UUID REFERENCES users(id),
            role INTEGER DEFAULT 20,
            view_props JSONB DEFAULT '{}'::jsonb,
            default_props JSONB DEFAULT '{}'::jsonb,
            issue_props JSONB DEFAULT '{}'::jsonb,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            deleted_at TIMESTAMP WITH TIME ZONE
        );
    """)

    # Projects table with fields referenced by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            identifier VARCHAR(10) NOT NULL,
            created_by_id UUID REFERENCES users(id),
            workspace_id UUID REFERENCES workspaces(id),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            network INTEGER DEFAULT 0,
            cycle_view BOOLEAN DEFAULT TRUE,
            module_view BOOLEAN DEFAULT TRUE,
            issue_views_view BOOLEAN DEFAULT TRUE,
            page_view BOOLEAN DEFAULT TRUE,
            intake_view BOOLEAN DEFAULT TRUE,
            inbox_view BOOLEAN DEFAULT TRUE,
            archive_in INTEGER DEFAULT 0,
            close_in INTEGER DEFAULT 0,
            logo_props JSONB DEFAULT '{}'::jsonb,
            is_time_tracking_enabled BOOLEAN DEFAULT FALSE,
            is_issue_type_enabled BOOLEAN DEFAULT TRUE,
            guest_view_all_features BOOLEAN DEFAULT TRUE,
            timezone VARCHAR(64) DEFAULT 'UTC'
        );
    """)

    # Project members table used by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID REFERENCES projects(id),
            member_id UUID REFERENCES users(id),
            workspace_id UUID REFERENCES workspaces(id),
            role INTEGER DEFAULT 20,
            view_props JSONB DEFAULT '{}'::jsonb,
            default_props JSONB DEFAULT '{}'::jsonb,
            sort_order DOUBLE PRECISION DEFAULT 0,
            preferences JSONB DEFAULT '{}'::jsonb,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            deleted_at TIMESTAMP WITH TIME ZONE
        );
    """)

    # States table used by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            color VARCHAR(16) DEFAULT '#3B82F6',
            slug VARCHAR(100) NOT NULL,
            created_by_id UUID REFERENCES users(id),
            project_id UUID REFERENCES projects(id),
            workspace_id UUID REFERENCES workspaces(id),
            sequence DOUBLE PRECISION DEFAULT 0,
            "group" VARCHAR(32) DEFAULT 'backlog',
            "default" BOOLEAN DEFAULT FALSE,
            is_triage BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # Issues table used by upload script
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            description JSONB DEFAULT '{}'::jsonb,
            priority VARCHAR(32) DEFAULT 'none',
            sequence_id INTEGER DEFAULT 0,
            created_by_id UUID REFERENCES users(id),
            project_id UUID REFERENCES projects(id),
            workspace_id UUID REFERENCES workspaces(id),
            description_html TEXT DEFAULT '',
            description_stripped TEXT DEFAULT '',
            sort_order DOUBLE PRECISION DEFAULT 0,
            is_draft BOOLEAN DEFAULT FALSE,
            external_id VARCHAR(64),
            external_source VARCHAR(64),
            state_id UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # Labels table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            color VARCHAR(16) DEFAULT '#3B82F6',
            sort_order DOUBLE PRECISION DEFAULT 0,
            created_by_id UUID REFERENCES users(id),
            project_id UUID REFERENCES projects(id),
            workspace_id UUID REFERENCES workspaces(id),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # Issue labels mapping table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS issue_labels (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            issue_id UUID REFERENCES issues(id),
            label_id UUID REFERENCES labels(id),
            project_id UUID REFERENCES projects(id),
            workspace_id UUID REFERENCES workspaces(id),
            created_by_id UUID REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # API tokens table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token VARCHAR(255) UNIQUE NOT NULL,
            label VARCHAR(255),
            user_type INTEGER DEFAULT 0,
            created_by_id UUID REFERENCES users(id),
            user_id UUID REFERENCES users(id),
            workspace_id UUID REFERENCES workspaces(id),
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            is_service BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    print("✅ Essential tables created for lightweight mode")

# Create admin user in the 'users' table (for upload script compatibility)
cursor.execute("SELECT COUNT(*) FROM users WHERE email = %s", ['admin@demo.local'])
if cursor.fetchone()[0] == 0:
    try:
        import hashlib, base64, secrets

        # Generate proper Django password hash (same as upload script)
        def make_django_password(password, iterations=260000):
            salt = secrets.token_hex(12)
            dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
            hash_b64 = base64.b64encode(dk).decode('ascii').strip()
            return f"pbkdf2_sha256${iterations}${salt}${hash_b64}"

        admin_user_id = str(uuid.uuid4())
        hashed_password = make_django_password("AdminUser123!")

        # Create user with all required schema fields (same as regular upload script)
        cursor.execute("""
            INSERT INTO users (id, username, email, first_name, last_name, avatar, password,
                             date_joined, created_at, updated_at, last_location, created_location,
                             is_superuser, is_managed, is_password_expired, is_active, is_staff,
                             is_email_verified, is_password_autoset, token, user_timezone,
                             last_login_ip, last_logout_ip, last_login_medium, last_login_uagent,
                             is_bot, display_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW(),
                   'web', 'web', false, false, false, true, false,
                   true, false, %s, 'UTC',
                   '', '', 'web', '', false, %s)
        """, (admin_user_id, "admin", "admin@demo.local", "Admin", "User", "", hashed_password,
              str(uuid.uuid4()), "Admin User"))
        print("✅ Admin user created in users table")
    except Exception as e:
        print(f"⚠️ Failed to create admin user in users table: {e}")
else:
    print("✅ Admin user already exists in users table")

# Also try to create in Django auth system if it exists
try:
    if not User.objects.filter(email='admin@demo.local').exists():
        user = User.objects.create_superuser(
            username='admin',
            email='admin@demo.local',
            password='AdminUser123!'
        )
        print("✅ Admin user created in Django auth system")
    else:
        print("✅ Admin user already exists in Django auth system")
except Exception as e:
    print(f"⚠️ Django user creation failed: {e}")

# Upload GitHub issues if data files are available
import os

# Check organized folder structure first, then legacy paths (backwards compatibility)
github_issues_path = '/data/plane/issues.json' if os.path.exists('/data/plane/issues.json') else '/data/issues.json'
github_prs_path = '/data/plane/pull_requests.json' if os.path.exists('/data/plane/pull_requests.json') else '/data/pull_requests.json'

if os.path.exists(github_issues_path) and os.path.exists(github_prs_path):
    print("📤 Setting up Plane workspace and uploading GitHub issues...")
    print(f"ℹ️ Using GitHub data from: {os.path.dirname(github_issues_path) or '/data'}")

    import json
    from uuid import uuid4
    from datetime import datetime

    # Load GitHub issues
    print("🔄 Loading GitHub issues...")
    with open(github_issues_path, 'r') as f:
        issues = json.load(f)
    print(f"📊 Found {len(issues)} issues to upload")

    # Filter issues based on git commit timestamp to prevent future data leakage
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
            print(f"⏳ Waiting for git commit timestamp file... ({wait_time}s/{max_wait}s)")
            time.sleep(2)
            wait_time += 2

        if os.path.exists(timestamp_file):
            try:
                with open(timestamp_file, 'r') as f:
                    commit_timestamp_str = f.read().strip()
                commit_dt = datetime.fromisoformat(commit_timestamp_str.replace('Z', '+00:00'))
                print(f"🕐 Using pre-computed git commit timestamp: {commit_timestamp_str}")
                return commit_dt
            except Exception as e:
                print(f"⚠️ Error reading pre-computed timestamp: {e}")

        # Fallback: Try multiple possible repo locations (for direct access)
        possible_paths = ['/repo', '/testbed', '/workspace', '/app', '/opt/django', '/django']
        repo_path = None

        for path in possible_paths:
            if os.path.exists(path) and os.path.exists(os.path.join(path, '.git')):
                repo_path = path
                print(f"📍 Found git repo at: {repo_path}")
                break

        if not repo_path:
            print("⚠️ No git repo found and no pre-computed timestamp available")
            print(f"   Searched repo locations: {', '.join(possible_paths)}")
            print(f"   Searched timestamp file: {timestamp_file}")
            print("ℹ️ To enable filtering, create git_commit_timestamp.txt in /data with commit timestamp")
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
                print(f"🕐 Git commit timestamp: {commit_timestamp_str}")
                return commit_dt
            else:
                print(f"⚠️ Failed to get git commit timestamp: {result.stderr}")
                return None
        except Exception as e:
            print(f"⚠️ Error getting git commit timestamp: {e}")
            return None

    def filter_issues_by_timestamp(issues, cutoff_timestamp):
        """Filter issues to only include those created before the cutoff timestamp"""
        if cutoff_timestamp is None:
            return issues

        from datetime import datetime, timezone

        # Ensure cutoff_timestamp is timezone-aware
        if cutoff_timestamp.tzinfo is None:
            cutoff_timestamp = cutoff_timestamp.replace(tzinfo=timezone.utc)

        filtered_issues = []
        for issue in issues:
            try:
                # Parse GitHub issue creation timestamp
                created_at_str = issue.get('createdAt', '')
                if not created_at_str:
                    continue

                # Handle different timestamp formats from GitHub
                if 'T' in created_at_str:
                    # ISO format: 2023-11-11T16:56:56.231000+00:00
                    issue_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                else:
                    # GitHub web format: "Jul 13, 2005, 2:03:27 PM"
                    issue_dt = datetime.strptime(created_at_str, "%b %d, %Y, %I:%M:%S %p")
                    # Make timezone-aware (assume UTC for naive timestamps)
                    issue_dt = issue_dt.replace(tzinfo=timezone.utc)

                # Ensure issue_dt is timezone-aware
                if issue_dt.tzinfo is None:
                    issue_dt = issue_dt.replace(tzinfo=timezone.utc)

                # Only include issues created before the git commit timestamp
                if issue_dt <= cutoff_timestamp:
                    filtered_issues.append(issue)

            except Exception as e:
                print(f"⚠️ Error parsing timestamp for issue {issue.get('number', 'unknown')}: {e}")
                # Include issue if we can't parse timestamp (fail-safe)
                filtered_issues.append(issue)

        return filtered_issues

    # Apply timestamp filtering
    git_timestamp = get_git_commit_timestamp()
    if git_timestamp:
        original_count = len(issues)
        issues = filter_issues_by_timestamp(issues, git_timestamp)
        filtered_count = len(issues)
        print(f"🔍 Filtered issues: {original_count} → {filtered_count} (removed {original_count - filtered_count} future issues)")
    else:
        print("ℹ️ Skipping timestamp filtering - using all issues")

    # Get admin user (already created above)
    cursor.execute("SELECT id FROM users WHERE email = 'admin@demo.local'")
    admin_user = cursor.fetchone()
    admin_user_id = admin_user[0]

    # Create workspace if not exists
    cursor.execute("SELECT id FROM workspaces WHERE slug = 'test-demo'")
    workspace = cursor.fetchone()
    if not workspace:
        workspace_id = str(uuid4())

        # Check if timezone column exists (varies by Plane version)
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'workspaces' AND column_name = 'timezone'
        """)
        has_timezone = cursor.fetchone() is not None

        if has_timezone:
            cursor.execute("""
                INSERT INTO workspaces (id, name, slug, created_by_id, owner_id, created_at, updated_at, timezone, background_color)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), %s, %s)
            """, [workspace_id, "TEST Demo", "test-demo", admin_user_id, admin_user_id, 'UTC', '#ffffff'])
        else:
            # Older Plane schema without timezone/background_color
            cursor.execute("""
                INSERT INTO workspaces (id, name, slug, created_by_id, owner_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, [workspace_id, "TEST Demo", "test-demo", admin_user_id, admin_user_id])
        print("✅ Workspace created")
    else:
        workspace_id = workspace[0]
        print("✅ Workspace exists")

    # Create project if not exists - use bulletproof dynamic approach
    cursor.execute("SELECT id FROM projects WHERE identifier = 'TEST' AND workspace_id = %s", [workspace_id])
    project = cursor.fetchone()
    if not project:
        project_id = str(uuid4())

        # Get ALL columns that exist in projects table and their nullability
        cursor.execute("""
            SELECT column_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'projects'
            ORDER BY column_name
        """)
        all_columns = {row[0]: {'nullable': row[1] == 'YES', 'default': row[2]} for row in cursor.fetchall()}

        # Define our base required columns and values
        base_columns = {
            'id': project_id,
            'name': "test",
            'description': "test GitHub Issues",
            'identifier': "TEST",
            'created_by_id': admin_user_id,
            'workspace_id': workspace_id
        }

        # Define default values for optional columns that might exist
        optional_defaults = {
            'network': 0,
            'cycle_view': True,
            'module_view': True,
            'issue_views_view': True,
            'page_view': True,
            'intake_view': False,
            'inbox_view': True,
            'archive_in': 0,
            'close_in': 0,
            'logo_props': '{}',
            'is_time_tracking_enabled': False,
            'is_issue_type_enabled': True,
            'guest_view_all_features': True,
            'timezone': 'UTC'
        }

        # Build the INSERT statement dynamically
        insert_columns = []
        insert_values = []

        # Add base columns
        for col, val in base_columns.items():
            if col in all_columns:
                insert_columns.append(col)
                insert_values.append(val)

        # Add optional columns that exist - ensure we include all columns that have NOT NULL constraints
        for col, default_val in optional_defaults.items():
            if col in all_columns:
                insert_columns.append(col)
                insert_values.append(default_val)

        # Debug: Print what columns we're inserting
        print(f"🔍 Inserting project with columns: {insert_columns}")
        print(f"🔍 Available columns: {list(all_columns.keys())}")

        # Add timestamp columns
        insert_columns.extend(['created_at', 'updated_at'])

        # Build the SQL
        columns_str = ', '.join(insert_columns)
        placeholders = ', '.join(['%s'] * len(insert_values)) + ', NOW(), NOW()'

        print(f"🔍 SQL: INSERT INTO projects ({columns_str}) VALUES ({placeholders})")

        cursor.execute(f"""
            INSERT INTO projects ({columns_str})
            VALUES ({placeholders})
        """, insert_values)
        print("✅ Project created with dynamic schema detection")
    else:
        project_id = project[0]
        print("✅ Project exists")

    # Ensure admin is a workspace member (exact same logic as working script)
    cursor.execute("SELECT 1 FROM workspace_members WHERE workspace_id=%s AND member_id=%s", [workspace_id, admin_user_id])
    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO workspace_members (
                id, workspace_id, member_id, role, view_props, default_props, issue_props,
                is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW(), NOW())
        """, [str(uuid4()), workspace_id, admin_user_id, 20, '{}', '{}', '{}', True])
        print("✅ Added admin to workspace members")

    # Ensure admin is a project member (exact same logic as working script)
    cursor.execute("SELECT 1 FROM project_members WHERE project_id=%s AND member_id=%s", [project_id, admin_user_id])
    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO project_members (
                id, project_id, member_id, workspace_id, role, view_props, default_props,
                sort_order, preferences, is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, NOW(), NOW())
        """, [str(uuid4()), project_id, admin_user_id, workspace_id, 20, '{}', '{}', 0.0, '{}', True])
        print("✅ Added admin to project members")

    # Ensure default states exist for the project (exact same logic as working script)
    cursor.execute("SELECT COUNT(*) FROM states WHERE project_id=%s", [project_id])
    num_states = cursor.fetchone()[0]
    if not num_states:
        print("🔄 Creating default issue states...")
        default_states = [
            ("Backlog", "backlog", 0, "backlog", True, False),
            ("Todo", "todo", 1, "unstarted", False, False),
            ("In Progress", "in_progress", 2, "started", False, False),
            ("Done", "done", 3, "completed", False, False)
        ]
        for name, slug, seq, group_name, is_default, is_triage in default_states:
            sid = str(uuid4())
            cursor.execute("""
                INSERT INTO states (
                    id, name, description, color, slug, created_by_id, project_id, workspace_id,
                    sequence, "group", "default", is_triage, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """, [sid, name, '', "#3B82F6", slug, admin_user_id, project_id, workspace_id,
                  float(seq), group_name, is_default, is_triage])
        print("✅ Created default states for project")
    else:
        print("✅ States already exist")

    # Get default state ID
    cursor.execute("SELECT id FROM states WHERE project_id = %s AND slug = 'backlog'", [project_id])
    default_state = cursor.fetchone()
    default_state_id = default_state[0] if default_state else None

    # Upload issues efficiently
    print("🔄 Uploading GitHub issues...")
    uploaded = 0
    for i, issue in enumerate(issues):
        try:
            issue_id = str(uuid4())
            title = issue.get('title', 'Untitled Issue')[:255]
            body_text = issue.get('body', '') or ''
            github_number = issue.get('number', i+1)

            # Simple description
            description = json.dumps({
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": body_text[:1000]}]}]
            })

            # Create HTML and stripped descriptions (same as working script)
            description_html = f"<p>{body_text[:500]}</p>" if body_text else "<p></p>"
            description_stripped = body_text[:500] if body_text else ""

            # Use exact same columns as working script
            cursor.execute("""
                INSERT INTO issues (id, name, description, priority, sequence_id, created_by_id, project_id,
                                  workspace_id, description_html, description_stripped, sort_order, is_draft,
                                  external_id, external_source, state_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """, [issue_id, title, description, "none", github_number, admin_user_id, project_id,
                  workspace_id, description_html, description_stripped, 0.0, False,
                  str(github_number), "github", default_state_id])
            uploaded += 1

        except Exception as e:
            print(f"⚠️ Failed to upload issue {issue.get('number', '?')}: {e}")

    print(f"✅ Uploaded {uploaded}/{len(issues)} issues to Plane")
else:
    print("ℹ️ No GitHub data files found, skipping issue upload")
    print(f"   Checked: /data/plane/issues.json, /data/issues.json")

transaction.commit()
EOF

# Generate API token and MCP config
echo "🔄 Generating API token and MCP configuration..."
API_TOKEN_OUTPUT=$(python manage.py shell << 'EOF'
import os
import json
from uuid import uuid4
from django.db import connection

cursor = connection.cursor()

# Get admin user and workspace info
cursor.execute("SELECT id FROM users WHERE email = 'admin@demo.local'")
admin_user = cursor.fetchone()
admin_user_id = admin_user[0]

cursor.execute("SELECT id FROM workspaces WHERE slug = 'test-demo'")
workspace = cursor.fetchone()
workspace_id = workspace[0]

cursor.execute("SELECT id FROM projects WHERE identifier = 'TEST' AND workspace_id = %s", [workspace_id])
project = cursor.fetchone()
project_id = project[0] if project else None

# Generate API token
token_id = str(uuid4())
token_value = f"plane_{uuid4().hex[:32]}"

cursor.execute("""
    INSERT INTO api_tokens (id, token, label, user_type, created_by_id, user_id, workspace_id,
                          description, is_active, is_service, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
""", [token_id, token_value, "MCP Integration Token", 0, admin_user_id, admin_user_id, workspace_id,
      "API token for MCP server integration", True, False])

print(f"API_TOKEN:{token_value}")
print(f"WORKSPACE_ID:{workspace_id}")
print(f"PROJECT_ID:{project_id}")

connection.commit()
EOF
)

# Extract values from output
API_TOKEN=$(echo "$API_TOKEN_OUTPUT" | grep "API_TOKEN:" | cut -d: -f2)
WORKSPACE_ID=$(echo "$API_TOKEN_OUTPUT" | grep "WORKSPACE_ID:" | cut -d: -f2)
PROJECT_ID=$(echo "$API_TOKEN_OUTPUT" | grep "PROJECT_ID:" | cut -d: -f2)

echo "✅ API token created: $API_TOKEN"

# Add Plane config to MCP config file
if [ -d "/config" ]; then
    echo "🔄 Adding Plane configuration to MCP config..."

    # Simply append Plane config to the file
    echo "export PLANE_API_HOST_URL=http://plane-api:8000" >> /config/mcp-config.txt
    echo "export PLANE_API_KEY=$API_TOKEN" >> /config/mcp-config.txt
    echo "export PLANE_WORKSPACE_SLUG=test-demo" >> /config/mcp-config.txt

    echo "✅ Plane config added to MCP config"
    echo "ℹ️ Plane API Key: $API_TOKEN"
    echo "ℹ️ Plane Workspace: test-demo"
else
    echo "ℹ️ No /config directory found, skipping MCP config update"
    echo "ℹ️ Generated API token: $API_TOKEN"
fi

# Ensure postgres stops when container stops
trap 'echo "🔻 Stopping embedded PostgreSQL..."; kill -TERM $POSTGRES_PID 2>/dev/null || true; wait $POSTGRES_PID 2>/dev/null || true' EXIT

# Create signal file to indicate migrations are complete
touch /tmp/migrations_complete

echo "🎉 Plane API initialization completed!"

echo "🚀 Starting API server..."

# Start the API server
# The makeplane/plane-backend:preview image uses gunicorn
exec gunicorn -w 4 -b 0.0.0.0:8000 plane.asgi:application -k uvicorn.workers.UvicornWorker --timeout 120
