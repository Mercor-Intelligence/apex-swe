# Issue 40
# Topic: Email → Ticket

## Problem Statement

Fetch the most recent email from MailHog API (`GET /api/v2/messages`, take first message) and create a Plane issue in project `test-demo/TEST` with title=email subject, description=email body (plain text), priority="medium". Print: "Created ticket [issue_id] from email: [subject]". MailHog: `http://mailhog:8025/api`, Plane: `http://plane-api:8000/api/v1`.
    
**Tools needed**: MailHog, Plane
    
**Prerequisites**: MailHog must have at least 1 email.

---

## Solution

## Objective
Fetch most recent email from MailHog and create Plane issue.

## Solution Approach

### 1. Create Python Script (`/app/email_to_ticket.py`)

**Imports:** `requests`, `sys`

**Step 1: Read Plane API Key**
- Read from `/config/mcp-config.txt`
- Parse line starting with `export PLANE_API_KEY=`
- Extract value after `=`

**Step 2: Get Plane Project UUID**
- **CRITICAL**: Plane API requires project UUID, not identifier
- GET `http://plane-api:8000/api/v1/workspaces/test-demo/projects/`
- Headers: `{"X-API-Key": api_key}`
- Find project where `identifier == "TEST"`
- Extract project `id` (UUID)

**Step 3: Fetch Latest Email from MailHog**
- GET `http://mailhog:8025/api/v2/messages?limit=1`
- Response structure:
```json
{
  "items": [
    {
      "Content": {
        "Headers": {
          "Subject": ["email subject here"]
        },
        "Body": "email body text here"
      }
    }
  ]
}
```
- Extract: `data['items'][0]['Content']['Headers']['Subject'][0]`
- Extract: `data['items'][0]['Content']['Body']`

**Step 4: Create Plane Issue**
- POST `http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_uuid}/issues/`
- Headers: 
```json
{
  "X-API-Key": "{api_key}",
  "Content-Type": "application/json"
}
```
- Payload:
```json
{
  "name": "{email subject}",
  "description_html": "<p>{email body}</p>",
  "priority": "medium"
}
```
- Note: Use `name` not `title`, and `description_html` not `description`

**Step 5: Print Output**
- Extract `id` from response JSON
- Print: `"Created ticket {issue_id} from email: {subject}"`

### 2. Solution YAML

```yaml
- command: |
    cat > /app/email_to_ticket.py << 'EOF'
    # Script code
    EOF
    chmod +x /app/email_to_ticket.py

- command: python /app/email_to_ticket.py
  min_timeout_sec: 30
```

## Key Points
- **Authentication**: API key stored in `/config/mcp-config.txt`, use `X-API-Key` header
- **Project UUID**: Must fetch TEST project UUID first, cannot use identifier "TEST" directly in POST URL
- **MailHog Structure**: Access via `items[0].Content.Headers.Subject[0]` and `items[0].Content.Body`
- **Plane Fields**: Use `name` (not "title") and `description_html` (not "description")
- **Fetch latest email only**: Use `?limit=1` query parameter
- **Default priority**: Always set to "medium"

---

## Tests

## Test Objectives
Verify email-to-ticket conversion and data accuracy.

## Test Functions

### Test 1: `test_plane_issue_created_from_email()`
**Purpose:** Verify issue created

**Steps:**
1. Get latest email from MailHog
2. Extract subject and body
3. Query Plane for issue with matching title
4. Assert issue exists

**Why:** Core functionality check

---

### Test 2: `test_issue_title_matches_email_subject()`
**Purpose:** Verify title transfer

**Steps:**
1. Get email subject from MailHog
2. Find Plane issue
3. Assert issue name equals email subject

**Why:** Title validation

---

### Test 3: `test_issue_description_matches_email_body()`
**Purpose:** Verify body transfer

**Steps:**
1. Get email body
2. Find Plane issue description
3. Assert contains email body text

**Why:** Description validation

---

### Test 4: `test_issue_has_medium_priority()`
**Purpose:** Verify default priority

**Steps:**
1. Find created Plane issue
2. Assert priority equals "medium"

**Why:** Priority validation

---

## Test Principles
- **Direct matching:** Title and description must match email
- **Latest email:** Only most recent email processed
- **API verification:** Check both MailHog and Plane

---

## Ticket

```json
{
    "number": 45036,
    "title": "Simple Email-to-Ticket Converter",
    "body": "Fetch the most recent email from MailHog API (`GET /api/v2/messages`, take first message) and create a Plane issue in project `test-demo/TEST` with title=email subject, description=email body (plain text), priority=\"medium\".\n\n**Environment:**\n- Fetch latest email only\n- Default priority: medium\n\n**Prerequisites (already available):**\n- MailHog available via MCP Tools or API\n- Plane available via MCP Tools or API\n- MailHog already has at least 1 email",
    "state": "open",
    "createdAt": "Oct 22, 2025, 12:00:00 PM",
    "closedAt": "",
    "labels": [
      {
        "name": "component:Email to Ticket"
      },
      {
        "name": "type:Integration"
      },
      {
        "name": "tool:MailHog"
      },
      {
        "name": "tool:Plane"
      }
    ],
    "assignees": [
      {
        "login": "Software Engineer"
      }
    ],
    "author": null,
    "url": "https://holder-url.com"
  }
```