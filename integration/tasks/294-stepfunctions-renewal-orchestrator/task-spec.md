# Issue 294
# Topic: Renewal Playbook via Step Functions & Lambda

## Problem Statement

Automate the renewal playbook by (1) orchestrating EspoCRM renewal opportunity checks through a LocalStack Step Functions state machine, (2) invoking Lambda functions to pull CRM data, update Plane tasks, and notify stakeholders, and (3) storing run results for audit. The workflow should sequence: fetch renewal details, evaluate health, branch on risk, update Plane, and send a Slack-style webhook notification.

**Tools needed**: EspoCRM, Plane, LocalStack (Step Functions, Lambda)

**Prerequisites**:
- EspoCRM API credentials with access to renewal-stage opportunities
- Plane project `CUSTOMER-SUCCESS` with renewal tasks
- LocalStack Step Functions & Lambda endpoints reachable
- Webhook URL for leadership notifications

---

## Solution

## Objective
Deliver a deterministic, repeatable renewal process orchestrated by Step Functions with Lambda tasks handling integration logic.

## Solution Approach

### 1. Build Step Functions State Machine (`/infra/renewal_state_machine.json`)

States:
- `FetchRenewal` (Lambda): pulls EspoCRM opportunity payload
- `AssessHealth` (Lambda): computes risk based on probability, ARR, blockers
- Choice state branches: `HighRisk`, `Healthy`
- `UpdatePlane` (Lambda): syncs status into Plane issue
- `NotifyLeadership` (Lambda): posts JSON payload to webhook with decision
- `RecordOutcome` (Lambda): writes summary to local file/log for auditing

Configure retries on API failures and overall timeout (120s).

### 2. Implement Lambda Handlers (`/app/lambdas/*.py`)

Shared utilities for EspoCRM & Plane auth. Each handler returns structured response for next state. Package with requirements + deployment zip for LocalStack Lambda.

### 3. Deployment Script (`/scripts/deploy_renewal_flow.sh`)

- Package Lambda code via `zip`
- Register functions with LocalStack Lambda
- Deploy Step Functions state machine using AWS CLI pointed at LocalStack
- Output ARN references for runtime.

### 4. Execution Runner (`/scripts/run_renewal_flow.py`)

- Accept opportunity ID input
- Start Step Functions execution with payload {"opportunityId": "..."}
- Poll status, print final summary (risk, actions taken)

**Output:**
- Print `Renewal flow {executionArn} finished with status {status} (risk={riskLevel})`

### 5. Solution YAML

```yaml
- command: bash /scripts/deploy_renewal_flow.sh
  min_timeout_sec: 90
- command: python /scripts/run_renewal_flow.py --opportunity $OPP_ID
  min_timeout_sec: 60
```

## Key Points
- Serverless orchestration dedicated to renewals
- Branching logic handled by Step Functions
- Each integration call isolated within Lambda
- Auditability via execution history

---

## Tests

## Test Objectives
Validate critical Lambda logic and Step Functions wiring.

### Test 1: `test_assess_health_lambda()`
**Purpose:** Ensure risk scoring matches rules

**Steps:**
1. Invoke lambda locally with sample payloads
2. Assert risk output for varying probability/ARR combos

**Why:** Prevents misrouting renewals

---

### Test 2: `test_state_machine_success_path()`
**Purpose:** Confirm Step Functions definition works end-to-end

**Steps:**
1. Mock EspoCRM/Plane APIs
2. Start execution with healthy scenario
3. Verify states transition `FetchRenewal -> AssessHealth -> UpdatePlane -> Notify -> Record`

**Why:** Ensures orchestration wiring is correct

---

## Test Principles
- **Deterministic branching:** Choice state mirrors risk tiers
- **Idempotent updates:** Lambdas upsert Plane data safely
- **Observability:** Execution history + logs available in LocalStack console

---

## Ticket

```json
{
  "number": 40294,
  "title": "Renewal Playbook via Step Functions & Lambda",
  "body": "Build a Step Functions state machine with Lambda tasks to orchestrate renewal health checks, Plane updates, and leadership notifications.",
  "state": "open",
  "createdAt": "Nov 20, 2025, 9:48:00 AM",
  "closedAt": "",
  "labels": [
    { "name": "type:Integration" },
    { "name": "component:Customer Success" },
    { "name": "tool:EspoCRM" },
    { "name": "tool:Plane" },
    { "name": "tool:LocalStack" },
    { "name": "service:StepFunctions" },
    { "name": "service:Lambda" },
    { "name": "difficulty:Medium" }
  ],
  "assignees": [
    { "login": "Renewals PM" }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```
