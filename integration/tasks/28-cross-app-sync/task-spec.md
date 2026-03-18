# Issue 28
## Topic Cross App Synchronization - Customer Ofboarding
**Problem Statement**
Fetch EspoCRM contact 'Robert Williams' by searching for firstName='Robert' and lastName='Williams'. Create or update customer in Medusa with first_name, last_name, email matching CRM values. Use email as unique identifier. Print: "Synced customer: [email] - [created/updated] in Medusa".

Tools needed: EspoCRM, Medusa

Prerequisites: EspoCRM contact 'Robert Williams' (firstName='Robert', lastName='Williams') must exist.

**Solution**
Objective
Search for EspoCRM contact by name and create/update customer in Medusa.

Solution Approach
1. Search EspoCRM for contact with firstName='Robert' and lastName='Williams'
2. Extract contact data (firstName, lastName, emailAddress)
3. Check if customer exists in Medusa by email
4. Create or update customer based on existence
5. Print output with action (created/updated)

**Tests**
Test Objectives
Verify contact search, customer creation/update, and data accuracy.

Key test functions:
- test_espocrm_contact_exists() - Verify prerequisite contact 'Robert Williams'
- test_medusa_customer_created_or_updated() - Verify customer exists in Medusa
- test_customer_data_matches_contact() - Verify data accuracy
- test_script_prints_sync_status() - Verify output format
- test_action_reported_correctly() - Verify action in output

**Ticket**
```json
{
  "number": 45024,
  "title": "Simple CRM-to-Medusa Customer Sync Script",
  "body": "Fetch EspoCRM contact 'Robert Williams' by searching for firstName='Robert' and lastName='Williams'. Create or update customer in Medusa with \`first_name\`, \`last_name\`, \`email\` matching CRM values. Use email as unique identifier. Print: \"Synced customer: [email] - [created/updated] in Medusa\".\n\n**Environment:**\n- Email as unique identifier for matching\n- Support both create and update operations\n- Search for contact by name to get contact ID (EspoCRM auto-generates IDs)\n\n**Prerequisites (already available):**\n- EspoCRM available via MCP Tools\n- Medusa available via MCP Tools\n- EspoCRM contact 'Robert Williams' (firstName='Robert', lastName='Williams') already exists",
  "state": "open",
  "createdAt": "Oct 22, 2025, 12:00:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:Cross-System Sync"
    },
    {
      "name": "type:Integration"
    },
    {
      "name": "tool:EspoCRM"
    },
    {
      "name": "tool:Medusa"
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