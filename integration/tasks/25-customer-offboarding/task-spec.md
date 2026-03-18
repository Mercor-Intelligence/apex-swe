# Issue 25
# Topic: Lead Offboarding

## Problem Statement

Using EspoCRM API, find and update lead with firstName "John" and lastName "Doe" (existing lead with fields: `firstName`, `lastName`, `emailAddress`, `accountId`, `status`) to set `status="Dead"`.
   
   **Tools needed**: EspoCRM
   
   **Prerequisites**: EspoCRM lead with firstName "John" and lastName "Doe" must exist.

---

## Solution

## Objective
Update EspoCRM lead status to Dead.

## Solution Approach

### 1. Find Lead by First and Last Name

**Search Request:**
- GET `/api/v1/Lead?where[0][type]=equals&where[0][attribute]=firstName&where[0][value]=John&where[1][type]=equals&where[1][attribute]=lastName&where[1][value]=Doe`
- Filter by firstName "John" and lastName "Doe"
- Extract lead ID from response

### 2. Update Lead Status

**Update Request:**
- PUT `/api/v1/Lead/{leadId}`
- Body:
```python
{
    "status": "Dead"
}
```

### 3. Handle Not Found

**Error Handling:**
- If lead not found, exit gracefully or raise error
- If multiple leads found, use first match

### 4. Solution YAML Structure

```yaml
- command: |
    cat > /app/offboard_lead.py << 'EOF'
    #!/usr/bin/env python3
    import requests
    import os
    
    # Search for lead by firstName "John" and lastName "Doe"
    # Extract lead ID
    # Update status
    EOF
    chmod +x /app/offboard_lead.py

- command: python /app/offboard_lead.py
  min_timeout_sec: 30
```

## Key Points
- Lead firstName: "John", lastName: "Doe"
- First search for lead by firstName and lastName to get ID
- Update single field: `status`
- Use EspoCRM API key authentication
- Handle case where lead doesn't exist or multiple matches found


---

## Tests

## Test Objectives
Verify lead status update.

## Test Functions

### Test 1: `test_lead_exists()`
**Purpose:** Verify prerequisite lead exists

**Steps:**
1. Search EspoCRM for lead with firstName "John" and lastName "Doe"
2. Assert lead exists in results

**Why:** Validates environment setup

---

### Test 2: `test_lead_status_updated()`
**Purpose:** Verify status changed to Dead

**Steps:**
1. Search for lead with firstName "John" and lastName "Doe" after script runs
2. Assert `status` == "Dead"

**Why:** Tests update operation

---

## Test Principles
- **Status verification:** Check actual field in EspoCRM
- **Simple operation:** Single field update

---

## Ticket

```json
{
  "number": 45021,
  "title": "Simple Lead Status Update Script for Lead Offboarding",
  "body": "Using EspoCRM API, find and update lead with firstName \"John\" and lastName \"Doe\" (existing lead with fields: `firstName`, `lastName`, `emailAddress`, `accountId`, `status`) to set `status=\"Dead\"`. First search for the lead by firstName and lastName to get its ID, then update the status field.\n\n**Prerequisites (already available):**\n- EspoCRM available via MCP Tools\n- EspoCRM lead with firstName \"John\" and lastName \"Doe\" already exists",
  "state": "open",
  "createdAt": "Oct 22, 2025, 12:00:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:Lead Lifecycle Management"
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
}
```
