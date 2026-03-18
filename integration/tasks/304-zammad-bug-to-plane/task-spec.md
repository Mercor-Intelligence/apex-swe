# Issue 304
# Topic: Support & Project Management Integration

## Problem Statement

Search Zammad for all tickets with state="new" and tag="bug", then create corresponding Plane issues in workspace "test-demo", project "TEST". Set Plane issue name to Zammad ticket title, description to first article body, and add label "type:Bug". Write summary to `/app/bug_sync_report.txt` with count of bugs synced.

**Tools needed**: Zammad, Plane

**Prerequisites**: 
1) Zammad must have at least 2 tickets with state="new" and tag="bug" *(Seed data includes 3 bug tickets)*
2) Plane workspace "test-demo" and project "TEST" must exist *(Created automatically)*

---

## Solution

# Solution: Task 116 - Zammad Bug Tickets to Plane Issues

## Objective
Sync new bug tickets from Zammad support system to Plane project management.

## Solution Approach

### 1. Fetch Bug Tickets from Zammad

**Zammad Authentication:**
- Use HTTP Basic Auth or Token authentication
- Headers: `Authorization: Token token={ZAMMAD_API_TOKEN}`

**Search for Bug Tickets:**
- GET `http://zammad:8080/api/v1/tickets/search?query=state:new AND tags:bug`
- Alternative: GET `/api/v1/tickets` and filter locally
- Extract for each ticket:
  - id, number, title, state
  - Verify state="new" or state_id=1
  - Verify "bug" in tags array

**Fetch Ticket Articles:**
- For each ticket: GET `/api/v1/ticket_articles/by_ticket/{ticket_id}`
- Extract first article body for issue description

### 2. Get Plane Project UUID

**Plane Authentication:**
- Read API key from `/config/mcp-config.txt` or environment
- Headers: `X-API-Key: {PLANE_API_KEY}`

**Fetch Project UUID:**
- GET `http://plane-api:8000/api/v1/workspaces/test-demo/projects/`
- Find project where identifier="TEST"
- Extract project id (UUID needed for issue creation)

### 3. Create Plane Issues

**For Each Bug Ticket:**
- POST `http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_uuid}/issues/`
- Headers: `X-API-Key`, `Content-Type: application/json`
- Payload:
```json
{
  "name": "[Zammad ticket title]",
  "description_html": "<p>[first article body]</p>",
  "labels": [{"name": "type:Bug"}],
  "priority": "medium"
}
```

**Track Created Issues:**
- Count successful creations
- Store mapping of Zammad ticket → Plane issue

### 4. Write Summary Report

**Summary File:** `/app/bug_sync_report.txt`

**Format:**
```
Bug Ticket Sync Report
=====================
Zammad bugs found: [X]
Plane issues created: [Y]

Synced tickets:
- Ticket #[number]: [title] → Issue [plane_id]
```

### 5. Solution YAML Structure

```yaml
- command: |
    cat > /app/sync_bugs_to_plane.py << 'EOF'
    #!/usr/bin/env python3
    import requests
    import os
    import json
    
    # Fetch Zammad bug tickets
    # Get Plane project UUID
    # Create Plane issues for each bug
    # Write summary report
    EOF
    chmod +x /app/sync_bugs_to_plane.py

- command: python /app/sync_bugs_to_plane.py
  min_timeout_sec: 60
```

## Key Points
- Search Zammad for state="new" AND tag="bug"
- Plane requires project UUID (not identifier) for issue creation
- Use "name" field in Plane (not "title")
- Set label "type:Bug" (case-sensitive)
- Include first article body as description
- Write summary to `/app/bug_sync_report.txt`

---

## Tests

# Tests: Task 116 - Zammad Bug Tickets to Plane Issues

## Test Objectives
Verify bug tickets are correctly identified in Zammad and created as issues in Plane.

## Test Functions

### Test 1: `test_zammad_bug_tickets_exist()`
**Purpose:** Verify prerequisite bug tickets exist

**Steps:**
1. Authenticate with Zammad API
2. Search for tickets with state="new" and tag="bug"
3. Assert at least 2 tickets found
4. Verify tickets have required fields (title, articles)

**Why:** Validates seed data is present

---

### Test 2: `test_plane_issues_created()`
**Purpose:** Verify Plane issues were created for bugs

**Steps:**
1. Authenticate with Plane API
2. Fetch Plane project UUID for "TEST"
3. GET `/api/v1/workspaces/test-demo/projects/{uuid}/issues/`
4. Search for issues with label "type:Bug"
5. Assert at least 2 bug issues exist

**Why:** Confirms issue creation succeeded

---

### Test 3: `test_issue_titles_match_tickets()`
**Purpose:** Verify issue names match ticket titles

**Steps:**
1. Fetch Zammad bug tickets
2. Get first bug ticket title
3. Search Plane issues for matching name
4. Assert Plane issue exists with same title

**Why:** Tests title transfer accuracy

---

### Test 4: `test_bug_label_applied()`
**Purpose:** Verify correct label is set

**Steps:**
1. Fetch created Plane issues
2. For each issue created from Zammad bug
3. Assert issue has label with name="type:Bug"
4. Verify label format is correct

**Why:** Validates label assignment

---

### Test 5: `test_summary_report_accurate()`
**Purpose:** Verify summary report exists and is accurate

**Steps:**
1. Check file exists at `/app/bug_sync_report.txt`
2. Read content
3. Parse "Zammad bugs found:" count
4. Parse "Plane issues created:" count
5. Verify counts match actual tickets and issues

**Why:** Tests reporting accuracy

---

## Test Principles
- **Tag filtering:** Only tickets with "bug" tag processed
- **State filtering:** Only "new" state tickets included
- **Label mapping:** type:Bug label correctly applied
- **Title preservation:** Ticket titles transfer accurately
- **Complete sync:** All matching tickets create issues

---

## Implementation Notes

### Actual Seed Data
The task includes 3 bug tickets in `data/zammad-data.json`:

1. **Ticket #10004**: "Data export feature crashes with large datasets"
   - State: new, Priority: 3 high
   - Tags: ["bug", "export", "crash"]
   - Article describes export failure with >10k records

2. **Ticket #10005**: "Email notifications not being sent"
   - State: new, Priority: 3 high
   - Tags: ["bug", "email", "notifications"]
   - Article describes notification system failure

3. **Ticket #10006**: "Mobile app login fails on iOS 17"
   - State: new, Priority: 2 normal
   - Tags: ["bug", "mobile", "ios", "authentication"]
   - Article describes iOS 17 compatibility issue

### Implementation Details

**State Handling:**
- Solution checks both `state="new"` (string) and `state_id=1` (integer)
- Zammad API may return state as null with state_id set
- Filter: `(ticket_state == "new") or (ticket_state_id == 1)`

**Label Handling:**
- Solution creates or retrieves "type:Bug" label via Plane labels API
- Label ID is passed when creating issues
- Tests fetch labels separately and map IDs to names for validation

**Report Format:**
```
Bug Ticket Sync Report
=====================
Zammad bugs found: 3
Plane issues created: 3

Synced tickets:
- Ticket #10004: Data export feature crashes with large datasets → Issue [uuid]
- Ticket #10005: Email notifications not being sent → Issue [uuid]
- Ticket #10006: Mobile app login fails on iOS 17 → Issue [uuid]
```

**Solution Structure:**
- `solution.py`: 362 lines, fully implemented sync logic
- `tests/test_outputs.py`: 451 lines, 5 comprehensive test functions
- All tests validate actual API responses and data integrity

**Key Implementation Decisions:**

1. **Robust State Checking**: The solution handles Zammad's dual state representation (string and state_id) to ensure compatibility across different API responses.

2. **Tag Fetching**: Tags are not included in the tickets endpoint response, so the solution makes separate API calls to `/api/v1/tags?object=Ticket&o_id={ticket_id}` for each ticket.

3. **Label Management**: The solution uses `get_or_create_label()` to ensure the "type:Bug" label exists before creating issues, preventing label creation errors.

4. **Text Report Format**: Unlike the reference task which uses CSV, this generates a human-readable text report matching the spec requirements.

5. **Error Handling**: The solution includes comprehensive error handling and logging to aid in debugging, with detailed output for each step of the sync process.

**Validation Results:**
- ✅ All 5 tests pass
- ✅ 3 bug tickets successfully synced to Plane
- ✅ Report generated with correct counts
- ✅ Labels properly applied to all synced issues

---

## Ticket Header

**Project:** Support & Engineering Integration  
**Issue Type:** Task  
**Priority:** Medium  
**Component:** Bug Tracking  
**Labels:** zammad, plane, sync, automation, medium  
**Sprint:** Current Sprint  
**Story Points:** 4  

**Summary:** Automated Bug Ticket to Engineering Issue Sync

## Ticket Content

### Description

Create an automated workflow that bridges the gap between customer support and engineering by syncing bug reports from Zammad ticketing system to Plane project management. When support agents tag tickets as bugs, this integration automatically creates corresponding engineering issues for investigation and resolution.

The integration searches for new bug tickets in Zammad, extracts the ticket title and initial problem description, and creates properly labeled issues in the engineering team's Plane project. This ensures bugs are quickly escalated to the development team without manual data entry.

A summary report tracks all synchronized bugs, providing visibility into the bug escalation process and helping teams monitor the flow of issues from support to engineering.

### Technical Requirements

**Environment:**
- Zammad API: `http://zammad:8080/api/v1`
- Plane API: `http://plane-api:8000/api/v1`
- Workspace: "test-demo"
- Project identifier: "TEST"
- Output: `/app/bug_sync_report.txt`
- Issue label: "type:Bug"

### Dependencies

- Zammad tickets must have state and tags fields
- Tag "bug" must exist in Zammad seed data
- Plane project "TEST" must exist in workspace "test-demo"
- Plane API requires project UUID (fetch via projects endpoint)
- Issue creation requires X-API-Key authentication

## JSON Ticket Format

```json
{
  "number": 304,
  "title": "Automated Bug Ticket to Engineering Issue Sync",
  "body": "Search Zammad for all tickets with state=\"new\" and tag=\"bug\", then create corresponding Plane issues in workspace \"test-demo\", project \"TEST\". Set Plane issue name to Zammad ticket title, description to first article body, and add label \"type:Bug\". Write summary to `/app/bug_sync_report.txt` with count of bugs synced.\n\n**Environment:**\n- Zammad API: `http://zammad:8080/api/v1`\n- Plane API: `http://plane-api:8000/api/v1`\n- Workspace: \"test-demo\"\n- Project identifier: \"TEST\"\n- Output: `/app/bug_sync_report.txt`\n- Issue label: \"type:Bug\"\n\n**Seed Data Available:**\nThe environment contains 3 bug tickets in Zammad:\n1. \"Data export feature crashes with large datasets\" (state=new, tags=[bug, export, crash])\n2. \"Email notifications not being sent\" (state=new, tags=[bug, email, notifications])\n3. \"Mobile app login fails on iOS 17\" (state=new, tags=[bug, mobile, ios, authentication])\n\n**Critical Implementation Details:**\n- State filtering: Check both `state=\"new\"` OR `state_id=1` (Zammad may return state as null with state_id set)\n- Tag fetching: Tags are NOT in tickets endpoint - use separate call: GET `/api/v1/tags?object=Ticket&o_id={ticket_id}`\n- Label handling: Use GET/POST `/api/v1/workspaces/{workspace}/projects/{uuid}/labels/` to get or create \"type:Bug\" label\n- Project UUID: Must fetch project UUID from identifier \"TEST\" via projects list endpoint\n- Article retrieval: GET `/api/v1/ticket_articles/by_ticket/{ticket_id}` for description content\n\n**Report Format (text file):**\n```\nBug Ticket Sync Report\n=====================\nZammad bugs found: X\nPlane issues created: Y\n\nSynced tickets:\n- Ticket #[number]: [title] → Issue [uuid]\n```\n\n**Test Requirements:**\n- Tests verify at least 2 bug tickets exist in Zammad\n- Tests check Plane issues have \"type:Bug\" label (requires label ID lookup)\n- Tests validate report file exists with correct counts\n- Tests confirm issue titles match ticket titles exactly\n\n**Authentication:**\n- Zammad: Create access token via POST `/api/v1/user_access_token` with basic auth\n- Plane: Read API key from `/config/mcp-config.txt` (format: export PLANE_API_KEY=...)",
  "state": "open",
  "createdAt": "Oct 22, 2025, 12:00:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:Bug Tracking"
    },
    {
      "name": "type:Integration"
    },
    {
      "name": "tool:Zammad"
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
