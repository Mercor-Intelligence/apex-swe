# Issue 281
# Topic: Medusa Warranty Validator for Zammad Tickets

## Problem Statement

Resolve warranty tickets faster by (1) scanning Zammad for tickets tagged `warranty` created within the last 24 hours, (2) verifying each request against Medusa orders to confirm eligibility (order id, purchase date, warranty term stored in metadata), (3) updating the Zammad ticket with a structured response indicating approval/denial plus required next steps, and (4) posting a short summary to Mattermost channel `customer-loyalty` so the concierge team knows which cases were cleared.

**Tools needed**: Zammad, Medusa, Mattermost

**Prerequisites**:
- Warranty term configuration stored per Medusa product (`metadata.warranty_months`)
- Zammad tickets include customer email/order id in custom fields
- Mattermost `customer-loyalty` channel + webhook exists

---

## Solution

## Objective
Automate warranty eligibility checks so customer tickets get an authoritative answer minutes after creation.

## Solution Approach

### 1. Create Python Script (`/app/solution.py`)

**Imports:** `requests`, `datetime`, `json`, `re`, `os`, `sys`

**Token Reading:**
- Read from MCP config file: /config/mcp-config.txt
- Parse format: `export SERVICE_TOKEN=value`
- Support for ZAMMAD_TOKEN/API_KEY and MATTERMOST_TOKEN

**Medusa Authentication:**
- POST to `/auth/user/emailpass` endpoint
- Credentials: email="admin@test.com", password="supersecret"
- Extract JWT token from response (check token, access_token, or data.token)
- Environment variable: MEDUSA_BACKEND_URL (default: http://medusa:9000)

**Fetch Warranty Tickets from Zammad:**
- GET request to `/api/v1/tickets`
- Use Bearer token authorization
- Environment variable: ZAMMAD_SITE_URL (default: http://zammad:8080)
- Filter tickets with:
  * Tag contains "warranty"
  * Created within last 24 hours
  * State is "new" or "open"
- Parse ISO timestamps with timezone handling

**Extract Order ID:**
- Parse ticket title for order_YYYYMMDD_N pattern
- Use regex: r'order_\d{8}_\d+'
- Return None if no match found

**Validate Warranty:**
- GET request to `/admin/orders/{order_id}` in Medusa
- Use Bearer token from authentication
- Check response:
  * 404 → "not_found"
  * Order status != "completed" → "not_found"
  * No items → "not_covered"
  * No warranty_months in product metadata → "not_covered"
- Calculate warranty end date: order_date + (warranty_months * 30 days)
- Compare with current date:
  * Within window → "approved" with expiry date
  * Past window → "expired" with expiry date

**Update Zammad Ticket:**
- POST to `/api/v1/ticket_articles`
- Create note (type="note", internal=False)
- Format comment based on decision:
  * approved: ✅ with RMA instructions
  * expired: ❌ with expiry date and alternatives
  * not_covered: ❌ with explanation
  * error: ⚠️ with reason
- Use Bearer token authorization

**Post to Mattermost:**
- Authenticate with Bearer token
- GET `/api/v4/teams/name/{team_name}` to get team ID
- GET `/api/v4/teams/{team_id}/channels` to list channels
- Find "customer-loyalty" channel (fallback to "town-square")
- POST `/api/v4/posts` with summary message
- Summary includes: total processed, approved count, denied count, list of approved ticket IDs
- Environment variables: MATTERMOST_URL (default: http://mattermost-server:8065), MATTERMOST_TEAM (default: test-demo)

**Console Output:**
- If no tickets: "No warranty tickets found"
- On success: `Processed {total} warranty tickets ({approved} approved, {denied} denied)`
- Errors to stderr

### 2. Solution YAML

```yaml
- command: python /app/solution.py
  min_timeout_sec: 60
```

## Key Points
- Automated eligibility logic
- Direct ticket updates
- Real-time concierge visibility
- Decision auditing through metadata

---

## Tests

## Test Objectives
Guarantee that warranty validation logic and notifications behave correctly.

## Test Functions

### Test 1: `test_warranty_window_calculation()`
**Purpose:** Ensure approval logic respects warranty duration

**Steps:**
1. Mock Medusa order with varying purchase dates and metadata months
2. Run validation helper
3. Assert decisions match expected outcomes

**Why:** Prevents false approvals/denials

---

### Test 2: `test_ticket_updates_and_notifications()`
**Purpose:** Confirm Zammad and Mattermost integrations fire

**Steps:**
1. Mock Zammad + Mattermost endpoints
2. Run script with sample tickets
3. Verify ticket state/comment payloads and channel message contents

**Why:** Ensures customers and concierge receive accurate info

---

## Test Principles
- **Data integrity:** Only tickets with verifiable orders processed
- **Traceability:** Every decision logged back to Zammad and console
- **Limited scope:** 24-hour sliding window prevents old tickets from repeating

---

## Ticket

```json
{
  "number": 40281,
  "title": "Medusa Warranty Validator for Zammad Tickets",
  "body": "Create an automated warranty validation system that processes support tickets, verifies warranty status against order data, and updates tickets with decisions.\n\n**Objective:**\nAutomate warranty eligibility checks to provide faster, consistent responses to customers and reduce manual verification work.\n\n**Requirements:**\n\n1. **Token Management**\n   - Read tokens from MCP config: /config/mcp-config.txt\n   - Parse format: `export SERVICE_TOKEN=\"value\"`\n   - Support ZAMMAD_TOKEN, ZAMMAD_API_KEY, MATTERMOST_TOKEN\n\n2. **Medusa Authentication**\n   - Endpoint: POST `/auth/user/emailpass`\n   - Credentials: {\"email\": \"admin@test.com\", \"password\": \"supersecret\"}\n   - Extract JWT token from response (check: token, access_token, data.token)\n   - Environment variable: MEDUSA_BACKEND_URL (default: http://medusa:9000)\n   - Handle authentication errors gracefully\n\n3. **Fetch Warranty Tickets from Zammad**\n   - Endpoint: GET `/api/v1/tickets`\n   - Authentication: Bearer token from MCP config\n   - Environment variable: ZAMMAD_SITE_URL (default: http://zammad:8080)\n   - Filter criteria:\n     * Tags contain \"warranty\"\n     * Created within last 24 hours (use datetime comparison)\n     * State is \"new\" or \"open\"\n   - Parse ISO timestamps, handle timezone conversions\n\n4. **Extract Order ID from Ticket**\n   - Parse ticket title for order ID pattern\n   - Regex: r'order_\\d{8}_\\d+'\n   - Example: \"order_20241115_1\"\n   - Return None if no match found\n\n5. **Validate Warranty Against Medusa**\n   - Endpoint: GET `/admin/orders/{order_id}`\n   - Authentication: Bearer token from Medusa auth\n   - Validation logic:\n     * Check if order exists (404 → \"not_found\")\n     * Verify order status is \"completed\"\n     * Extract order creation date\n     * Get first item's product metadata\n     * Check for warranty_months in product.metadata\n     * Calculate warranty end: order_date + (warranty_months * 30 days)\n     * Compare with current date\n   - Return decision and reason:\n     * \"approved\": Within warranty window\n     * \"expired\": Past warranty end date\n     * \"not_found\": Order doesn't exist or not completed\n     * \"not_covered\": No warranty metadata\n     * \"error\": Exception occurred\n\n6. **Update Zammad Ticket**\n   - Endpoint: POST `/api/v1/ticket_articles`\n   - Authentication: Bearer token\n   - Article data:\n     * ticket_id: ticket ID\n     * body: Formatted comment based on decision\n     * type: \"note\"\n     * internal: false\n   - Comment formats:\n     * Approved: ✅ WARRANTY APPROVED + RMA instructions\n     * Expired: ❌ WARRANTY EXPIRED + expiry date + alternatives\n     * Not Covered: ❌ NOT COVERED + explanation\n     * Error: ⚠️ UNABLE TO VALIDATE + reason\n\n7. **Post Summary to Mattermost**\n   - Base URL: MATTERMOST_URL (default: http://mattermost-server:8065)\n   - Team: MATTERMOST_TEAM (default: test-demo)\n   - Authentication: Bearer token from MCP config\n   - Steps:\n     * GET `/api/v4/teams/name/{team_name}` → team_id\n     * GET `/api/v4/teams/{team_id}/channels` → channel list\n     * Find \"customer-loyalty\" channel (fallback to \"town-square\")\n     * POST `/api/v4/posts` with summary\n   - Summary format:\n     ```\n     ## 🛡️ Warranty Validation Summary\n     \n     **Total Processed**: {count}\n     **Approved**: {approved_count}\n     **Denied**: {denied_count}\n     \n     **Approved Tickets**: {ticket_ids}\n     ```\n\n8. **Output Requirements**\n   - If no tickets: \"No warranty tickets found\"\n   - On success: `Processed {total} warranty tickets ({approved} approved, {denied} denied)`\n   - Example: \"Processed 3 warranty tickets (2 approved, 1 denied)\"\n   - Errors to stderr\n   - Exit code 0\n\n**Technical Details:**\n- Script location: /app/solution.py\n- Language: Python 3\n- Required imports: requests, datetime, json, re, os, sys\n- Timeout for API calls: 30 seconds (Zammad), 10 seconds (Mattermost)\n- Denied count = total - approved\n\n**Environment Variables:**\n- MEDUSA_BACKEND_URL: Medusa URL (default: http://medusa:9000)\n- ZAMMAD_SITE_URL: Zammad URL (default: http://zammad:8080)\n- MATTERMOST_URL: Mattermost URL (default: http://mattermost-server:8065)\n- MATTERMOST_TEAM: Team name (default: test-demo)\n\n**Prerequisites (already available):**\n- Zammad with warranty-tagged tickets\n- Medusa with orders and warranty metadata in products\n- Mattermost with team and channels configured\n- MCP config with tokens\n- Python 3 with requests library\n\n**Success Criteria:**\n- Script executes without errors\n- Only warranty-tagged tickets from last 24 hours are processed\n- Warranty validation logic is accurate\n- Tickets are updated with appropriate comments\n- Summary is posted to Mattermost\n- Output format matches specification",
  "state": "open",
  "createdAt": "Nov 20, 2025, 9:20:00 AM",
  "closedAt": "",
  "labels": [
    { "name": "type:Integration" },
    { "name": "component:Customer Experience" },
    { "name": "tool:Medusa" },
    { "name": "tool:Zammad" },
    { "name": "tool:Mattermost" },
    { "name": "difficulty:Medium" }
  ],
  "assignees": [
    { "login": "Warranty Lead" }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```
