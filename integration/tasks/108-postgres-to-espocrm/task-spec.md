# Issue 108
# Topic: PostgreSQL to EspoCRM User Sync

## Problem Statement

Create a Python script that syncs new user sign-ups from PostgreSQL database to EspoCRM. Query users created in the last hour from the database and add them as new Contacts in the CRM application. The script must be created at `/app/sync_users_to_crm.py`.

**Tools needed**: PostgreSQL, EspoCRM

**Prerequisites**: 
- PostgreSQL database running with users table
- EspoCRM accessible and configured
- Connection details available in connection-info.md

---

## Solution

## Objective
Create Python script to query recent users from PostgreSQL and sync them as Contacts in EspoCRM.

## Solution Approach

### 1. Create Python Script (`/app/sync_users_to_crm.py`)

**Imports:** `psycopg2`, `requests`, `base64`, `typing`

**Database Connection:**
- Connect to PostgreSQL using DATABASE_URL from environment
- Default: `postgresql://testuser:testpass@127.0.0.1:5432/testdb`

**Query Recent Users:**
- SELECT from users table where `created_at >= NOW() - INTERVAL '1 hour'`
- Order by created_at DESC
- Fetch: id, first_name, last_name, email, created_at

**EspoCRM Authentication:**
- GET `/api/v1/App/user` with Basic auth header
- Extract token from response
- Use token for subsequent API calls

**Create Contacts:**
- POST to `/api/v1/Contact` with token auth
- Payload: firstName, lastName, emailAddress
- Handle 409 (duplicate) responses - skip duplicates
- Handle other errors with proper logging

**Verification:**
- Fetch recent contacts from EspoCRM
- Display created contacts with details

### 2. Solution YAML

```yaml
- command: |
    cat > /app/sync_users_to_crm.py << 'EOF'
    # Python script code
    EOF
    chmod +x /app/sync_users_to_crm.py

- command: python /app/sync_users_to_crm.py
  min_timeout_sec: 30
```

## Key Points
- Query users from last hour using created_at field
- Authenticate with EspoCRM using Basic auth → token flow
- Create Contact records with proper field mapping
- Handle duplicate contacts (HTTP 409)
- Output: Script at `/app/sync_users_to_crm.py`

---

## Tests

## Test Objectives
Verify script executes successfully, syncs recent users accurately, and maintains data integrity between PostgreSQL and EspoCRM with correct field mapping.

## Test Functions

### Test 1: `test_python_script_exists()`
**Purpose:** Verify script file creation and basic validity

**Steps:**
1. Check that `/app/sync_users_to_crm.py` file exists
2. Verify file has executable permissions using `os.access()`
3. Check file contains valid Python syntax by compiling it

**Why:** Validates script was created at correct location with proper permissions and syntax

---

### Test 2: `test_script_execution_succeeds()`
**Purpose:** Verify script executes without errors

**Steps:**
1. Execute `/app/sync_users_to_crm.py` using `subprocess.run()`
2. Capture stdout and stderr output
3. Assert script exits with return code 0
4. Verify no error messages in stderr
5. Verify success messages appear in output (e.g., "contact")

**Why:** Tests that the script can actually run and complete successfully

---

### Test 3: `test_recent_users_synced_to_crm()`
**Purpose:** Verify recent users are synced with correct field mapping

**Steps:**
1. Query PostgreSQL for users where `created_at >= NOW() - INTERVAL '1 hour'`
2. Execute the sync script using subprocess
3. Authenticate with EspoCRM API and get token
4. Query EspoCRM API for all contacts (with pagination)
5. For each recent database user, verify corresponding CRM contact exists
6. Verify field mapping accuracy for each user:
   - `first_name` → `firstName`
   - `last_name` → `lastName`
   - `email` → `emailAddress`
7. Verify all 11 expected users are present:
   - John Doe (john.doe@example.com)
   - Jane Smith (jane.smith@example.com)
   - Bob Johnson (bob.johnson@example.com)
   - Alice Williams (alice.williams@example.com)
   - Charlie Brown (charlie.brown@example.com)
   - David Miller (david.miller@example.com)
   - Emma Davis (emma.davis@example.com)
   - Michael Wilson (michael.wilson@example.com)
   - Sarah Moore (sarah.moore@example.com)
   - James Taylor (james.taylor@example.com)
   - Lisa Anderson (lisa.anderson@example.com)

**Why:** Validates database-to-CRM sync relationship and field mapping through actual execution

---

## Test Principles
- **Script execution validation:** Tests actually run the script and verify it works
- **Database→CRM relationship:** Verify sync relationship through PostgreSQL and EspoCRM queries
- **Field mapping:** Verify correct field transformations (first_name→firstName, etc.)
- **Data accuracy:** All 11 expected users must be present with correct data
- **Return code validation:** Script must exit with code 0 on success
- **Executable permissions:** Script must be executable
- **Syntax validation:** Script must have valid Python syntax

---

## Ticket

```json
{
  "number": 40000,
  "title": "Sync new user sign-ups to CRM",
  "body": "Sync new user sign-ups to CRM\n\nThe environment has a PostgreSQL database with a `users` table that contains user information. The database is already set up and running in this environment. Along with that, there is also an EspoCRM application that is live and accessible.\n\n**Your Task:**\nCreate a Python script called `sync_users_to_crm.py` in the `/app` directory that finds new users created in the last hour in the database and adds them as new Contacts in EspoCRM.\n\n**Database Details:**\n- Connection string available via `DATABASE_URL` environment variable\n- Default: `postgresql://testuser:testpass@127.0.0.1:5432/testdb`\n- Table: `users`\n- Schema: `id`, `first_name`, `last_name`, `email`, `created_at`, `updated_at`\n- Query requirement: Find users where `created_at >= NOW() - INTERVAL '1 hour'`\n\n**EspoCRM Integration:**\n- EspoCRM URL available via `ESPOCRM_SITE_URL` environment variable\n- Default: `http://espocrm:80`\n- Authentication: Use Basic auth to get token from `GET /api/v1/App/user`\n  - Username: `ESPOCRM_ADMIN_USERNAME` (default: `admin`)\n  - Password: `ESPOCRM_ADMIN_PASSWORD` (default: `ChangeMe123`)\n  - Header: `Espo-Authorization: Base64(username:password)`\n  - Response contains `token` field\n- Create contacts: `POST /api/v1/Contact`\n  - Use token authentication: `Espo-Authorization: Base64(username:token)`\n  - Payload: `{\"firstName\": \"...\", \"lastName\": \"...\", \"emailAddress\": \"...\"}`\n  - Handle HTTP 409 (duplicate) responses by skipping\n\n**Field Mapping:**\n- `first_name` → `firstName`\n- `last_name` → `lastName`\n- `email` → `emailAddress`\n\n**Requirements:**\n- Script location: `/app/sync_users_to_crm.py`\n- Make script executable\n- Use `psycopg2` for PostgreSQL connection\n- Use `requests` for EspoCRM API calls\n- Handle duplicate contacts gracefully (HTTP 409)\n- Print progress/status messages\n- Do not delete the script after execution\n\n**Prerequisites (already available):**\n- PostgreSQL database is running with test data\n- EspoCRM is accessible and configured\n- Connection details in environment variables\n- API documentation available in `/data/tool_code_api_docs/espocrm_api_doc.md`\n\nYou can confirm your script works by executing it and then fetching contacts from EspoCRM to verify the sync.",
  "state": "open",
  "createdAt": "Sept 17, 2025, 3:07:17 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:CRON Script"
    },
    {
      "name": "type:Request"
    },
    {
      "name": "tool:PostgreSQL"
    },
    {
      "name": "tool:EspoCRM"
    }
  ],
  "assignees": [
    {
      "login": "Adam Johnson"
    }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```

