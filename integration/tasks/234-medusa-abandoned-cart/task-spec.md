# Issue 234
# Topic: Medusa Abandoned Cart Recovery

## Problem Statement

Query Medusa for all carts that were created more than 2 hours ago but not completed (no order), extract customer emails, and send recovery emails via MailHog. Email subject: "Complete your purchase!", body includes cart total. Print count of recovery emails sent.

**Tools needed**: Medusa, MailHog

**Prerequisites**: 
- Medusa running with cart data
- MailHog SMTP accessible

---

## Solution

## Objective
Recover abandoned shopping carts through email reminders.

## Solution Approach

### 1. Create Python Script (`/app/cart_recovery.py`)

**Imports:** `requests`, `smtplib`, `email.mime.text`, `datetime`

**Query Abandoned Carts:**
- Authenticate with Medusa
- GET all carts
- Filter: created_at > 2 hours ago
- Filter: completed_at is null (not converted to order)
- Extract email and total

**Send Recovery Emails:**
- For each cart:
  - Subject: "Complete your purchase!"
  - Body: f"You left ${total} in your cart. Complete your order now!"
  - Send via SMTP

### 2. Solution YAML

```yaml
- command: python /app/cart_recovery.py
  min_timeout_sec: 50
```

## Key Points
- Time-based filtering (> 2h)
- Cart completion status check
- E-commerce recovery automation
- Revenue optimization

---

## Tests

## Test Objectives
Verify abandoned cart recovery emails.

## Test Functions

### Test 1: `test_recovery_emails_sent()`
**Purpose:** Verify email delivery

**Steps:**
1. Query MailHog
2. Search for "Complete your purchase!"
3. Assert emails exist

**Why:** Confirms sending

---

### Test 2: `test_only_abandoned_carts_targeted()`
**Purpose:** Verify filtering

**Steps:**
1. Query Medusa for abandoned carts manually
2. Count carts
3. Count recovery emails
4. Assert counts match

**Why:** Validates filtering logic

---

## Test Principles
- **Time threshold:** > 2 hours old
- **Completion check:** No associated order
- **Email accuracy:** Correct totals and emails

---

## Ticket

```json
{
  "number": 40234,
  "title": "Abandoned Cart Recovery System",
  "body": "Create a Python script to identify abandoned shopping carts and send recovery emails to customers.\n\n**Requirements:**\n- Query Medusa for carts created > 2 hours ago\n- Filter for carts without completed orders\n- Send recovery email to each customer\n- Subject: Complete your purchase!\n- Body: Include cart total\n- Send via MailHog SMTP\n\n**Environment:**\n- Medusa backend via MEDUSA_BACKEND_URL\n- MailHog SMTP: mailhog:1025\n\n**Output:**\n- Print: 'Sent {count} cart recovery emails'\n\n**Prerequisites (already available):**\n- Medusa with cart data\n- MailHog SMTP accessible",
  "state": "open",
  "createdAt": "Nov 9, 2025, 2:30:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "type:Integration"
    },
    {
      "name": "component:E-commerce"
    },
    {
      "name": "tool:Medusa"
    },
    {
      "name": "tool:MailHog"
    },
    {
      "name": "difficulty:Medium"
    }
  ],
  "assignees": [
    {
      "login": "E-commerce Manager"
    }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```

