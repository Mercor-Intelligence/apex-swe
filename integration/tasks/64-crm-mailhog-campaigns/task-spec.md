# Issue 64
# Topic: CRM ↔ MailHog Campaigns

## Problem Statement

Fetch all contacts from EspoCRM API (`GET /api/v1/Contact`), extract first 10 contacts that have `emailAddress` field populated. Create a CSV file at `/app/contacts.csv` with columns `name` and `email`. EspoCRM: `http://localhost:8082/api/v1`.
    
**Tools needed**: EspoCRM
    
**Prerequisites**: EspoCRM must have at least 10 contacts with email addresses.

---

## Solution

## Objective
Fetch contacts from EspoCRM and create CSV file with first 10 contacts that have email addresses.

## Solution Approach

### 1. Create Python Script (`/app/export_contacts_to_csv.py`)

**Imports:** `requests`, `base64`, `csv`

**EspoCRM Authentication:**
- Get token using Basic auth
- Username/password from env

**Fetch Contacts:**
- GET `/api/v1/Contact?maxSize=500`
- Filter for contacts with `emailAddress` not null

**Extract First 10:**
- Filter contacts with populated `emailAddress`
- Take first 10

**Write CSV Output:**
- Create `/app/contacts.csv`
- Columns: `name`, `email`
- Write contact data to CSV file

### 2. Solution YAML

```yaml
- command: |
    cat > /app/export_contacts_to_csv.py << 'EOF'
    # Script code
    EOF
    chmod +x /app/export_contacts_to_csv.py

- command: python /app/export_contacts_to_csv.py
  min_timeout_sec: 20
```

## Key Points
- Filter for emailAddress not null
- First 10 contacts only
- Output: CSV file at `/app/contacts.csv`
- Columns: name, email


---

## Tests

## Test Objectives
Verify contact fetching, filtering, and CSV file creation.

## Test Functions

### Test 1: `test_csv_file_exists()`
**Purpose:** Verify file creation

**Steps:**
1. Check `/app/contacts.csv` exists
2. Assert file is present

**Why:** Tests file output

---

### Test 2: `test_csv_has_10_contacts()`
**Purpose:** Verify count

**Steps:**
1. Read CSV file
2. Count rows (excluding header)
3. Assert has 10 entries

**Why:** Tests limit

---

### Test 3: `test_csv_has_correct_columns()`
**Purpose:** Verify structure

**Steps:**
1. Read CSV header
2. Check for `name` and `email` columns
3. Assert columns match

**Why:** Tests CSV format

---

### Test 4: `test_all_have_email_addresses()`
**Purpose:** Verify filtering

**Steps:**
1. Parse CSV file
2. For each row, check email column has valid email
3. Assert all contain "@"

**Why:** Tests email filter

---

### Test 5: `test_contacts_match_crm()`
**Purpose:** Verify accuracy

**Steps:**
1. Get first 10 contacts with email from CRM
2. Compare with CSV data
3. Assert matches

**Why:** Tests data accuracy

---

## Test Principles
- **File creation:** CSV file exists at correct path
- **Count validation:** Exactly 10 rows
- **Column structure:** Correct headers (name, email)
- **Email presence:** All have valid emails
- **Accuracy:** Matches CRM data

---

## Ticket

```json
  {
    "number": 45060,
    "title": "CRM Contact Export to CSV",
    "body": "Fetch all contacts from EspoCRM API (`GET /api/v1/Contact`), extract first 10 contacts that have `emailAddress` field populated. Create a CSV file at `/app/contacts.csv` with columns `name` and `email`.\n\n**Environment:**\n- Filter: emailAddress not null\n- Limit: first 10 contacts\n- Output: CSV file at `/app/contacts.csv`\n- Columns: name, email\n\n**Prerequisites (already available):**\n- EspoCRM available via MCP Tools\n- EspoCRM already has at least 10 contacts with email addresses",
    "state": "open",
    "createdAt": "Oct 22, 2025, 12:00:00 PM",
    "closedAt": "",
    "labels": [
      {
        "name": "component:Email Campaigns"
      },
      {
        "name": "type:Integration"
      },
      {
        "name": "tool:EspoCRM"
      }
    ],
    "assignees": [
      {
        "login": "Software Engineer"
      }
    ],
    "author": null,
    "url": "https://holder-url.com"
  },
```
