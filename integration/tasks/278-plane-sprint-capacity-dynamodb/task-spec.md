# Issue 278
# Topic: Plane Sprint Capacity to DynamoDB

## Problem Statement

Develop a planner utility that (1) pulls upcoming sprint issues from Plane project `ENG`, (2) aggregates estimated effort per assignee and compares against each engineer's capacity target stored in a local YAML file, and (3) writes the capacity status for each assignee into DynamoDB table `sprint-capacity` including load percentage and risk flag.

**Tools needed**: Plane, LocalStack (DynamoDB)

**Prerequisites**: 
- Plane workspace configured with project `ENG`
- Local capacity YAML available (e.g., `/data/capacity.yml`)
- LocalStack DynamoDB table `sprint-capacity` exists

---

## Solution

## Objective
Provide an at-a-glance capacity ledger for the next sprint.

## Solution Approach

### 1. Create Python Script (`/app/sprint_capacity.py`)

**Imports:** `requests`, `boto3`, `yaml`, `os`, `sys`, `json`, `shutil`, `datetime`, `collections`, `pathlib`

**Configuration Management:**
- Read MCP config from `/config/mcp-config.txt`
- Parse `export VAR=value` format
- Fall back to environment variables and defaults
- Support for PLANE_API_HOST_URL, PLANE_API_KEY, PLANE_WORKSPACE_SLUG

**Fetch Projects from Plane:**
- GET request to `/api/v1/workspaces/{workspace}/projects/`
- Use x-api-key header for authentication
- Handle {"results": [...]} response format
- Look for "ENG" project (case-insensitive)
- Fall back to first available project if ENG not found

**Fetch Sprint Issues:**
- GET request to `/api/v1/workspaces/{workspace}/projects/{project_id}/issues/`
- Extract {"results": [...]} format
- Filter out completed issues (state not in: done, completed, closed)
- Use all open issues as "sprint" issues

**Load Capacity Targets:**
- Read `/data/capacity.yml` using yaml.safe_load
- Format: `{ "email@example.com": hours_available }`
- Handle file read errors gracefully

**Compute Utilization:**
- Aggregate estimate_point per assignee
- Generate demo data if no real assignees (using capacity targets with random 60-95% utilization)
- Calculate utilization_pct = (hours_allocated / capacity) * 100
- Determine risk level:
  * 'high' if > 100%
  * 'medium' if 80-100%
  * 'low' if < 80%

**Write to DynamoDB:**
- Connect to LocalStack endpoint (http://localstack:4566)
- Use PutItem API with full DynamoDB format
- Item structure: assignee (S), sprint_id (S), capacity (N), hours_allocated (N), utilization_pct (N), risk (S), timestamp (S)
- Table name: 'sprint-capacity'
- Handle write errors gracefully

**Console Output:**
- Progress messages to stderr
- Final output to stdout:
  * Header: "Sprint capacity: {N} assignees"
  * Per assignee: "{email}: {utilization}% ({risk})"
  * Sorted by utilization descending

### 2. Solution YAML

```yaml
- command: python /app/sprint_capacity.py
  min_timeout_sec: 60
```

## Key Points
- Sprint readiness
- Capacity vs demand
- DynamoDB tracking
- Risk signaling

---

## Tests

## Test Objectives
Validate capacity calculations and persistence.

## Test Functions

### Test 1: `test_script_exists()`
**Purpose:** Verify script file exists

**Steps:**
1. Check if `/app/sprint_capacity.py` exists

**Why:** Ensures basic setup

---

### Test 2: `test_capacity_file_exists()`
**Purpose:** Verify capacity YAML exists

**Steps:**
1. Check if `/data/capacity.yml` exists

**Why:** Required input file

---

### Test 3: `test_execution_succeeds()`
**Purpose:** Verify script runs without errors

**Steps:**
1. Execute `/app/sprint_capacity.py`
2. Assert exit code is 0

**Why:** Basic functionality check

---

### Test 4: `test_output_format_exact()`
**Purpose:** Verify exact output format

**Steps:**
1. Run script and capture output
2. Check for "Sprint capacity: {N} assignees" header
3. Verify assignee lines match pattern: "email: X.X% (risk)"
4. Assert count matches header

**Why:** Output format validation

---

### Test 5: `test_plane_issue_fetching()`
**Purpose:** Verify Plane integration

**Steps:**
1. Check if Plane API is reachable
2. Run script
3. Verify script attempted to fetch projects

**Why:** Service integration test

---

### Test 6: `test_dynamodb_records_comprehensive()`
**Purpose:** Verify DynamoDB writes

**Steps:**
1. Run script
2. Query DynamoDB sprint-capacity table
3. Assert record count matches output
4. Verify table is active

**Why:** Persistence validation

---

### Test 7: `test_utilization_calculation_logic()`
**Purpose:** Verify utilization math

**Steps:**
1. Run script
2. Extract utilization percentages
3. Assert all values are valid (0-500%)

**Why:** Calculation accuracy

---

### Test 8: `test_risk_flag_accuracy()`
**Purpose:** Verify risk thresholds

**Steps:**
1. Run script
2. Extract utilization-risk pairs
3. Assert:
   * > 100% = high
   * 80-100% = medium
   * < 80% = low

**Why:** Risk categorization correctness

---

### Test 9: `test_dynamodb_record_structure()`
**Purpose:** Verify DynamoDB schema

**Steps:**
1. Run script
2. Scan DynamoDB table
3. Verify required fields: assignee, sprint_id, capacity, hours_allocated, utilization_pct, risk, timestamp

**Why:** Data structure validation

---

### Test 10: `test_cross_service_consistency()`
**Purpose:** Verify output matches DB

**Steps:**
1. Run script
2. Extract assignees from output
3. Extract assignees from DynamoDB
4. Assert sets match

**Why:** End-to-end consistency

---

## Test Principles
- **Reliable data:** Unclosed issues only
- **Capacity parity:** Respect YAML targets
- **Idempotent writes:** Use consistent sprint_id key

---

## Ticket

```json
{
  "number": 40278,
  "title": "Sprint Capacity Analysis Tool - Plane to DynamoDB",
  "body": "Create a sprint capacity analysis tool that fetches issues from Plane, compares workload against engineer capacity targets, and logs utilization metrics to DynamoDB.\n\n**Objective:**\nProvide visibility into team capacity utilization for the current sprint to identify over/under-allocated engineers and risks.\n\n**Requirements:**\n\n1. **Configuration Management**\n   - Read MCP config from `/config/mcp-config.txt`\n   - Parse format: `export VAR=\"value\"`\n   - Environment variables:\n     * PLANE_API_HOST_URL (default: http://plane-api:8000)\n     * PLANE_API_KEY\n     * PLANE_WORKSPACE_SLUG (default: test-demo)\n   - Fall back to defaults if not set\n\n2. **Fetch Projects from Plane**\n   - Endpoint: GET `/api/v1/workspaces/{workspace}/projects/`\n   - Header: `x-api-key: {api_key}`\n   - Response format: `{\"results\": [...]}`\n   - Find project with name 'ENG' (case-insensitive)\n   - Fall back to first available project if ENG not found\n\n3. **Fetch Sprint Issues**\n   - Endpoint: GET `/api/v1/workspaces/{workspace}/projects/{project_id}/issues/`\n   - Header: `x-api-key: {api_key}`\n   - Response format: `{\"results\": [...]}`\n   - Filter criteria: Exclude issues with state in ['done', 'completed', 'closed']\n   - Use all remaining open issues as sprint issues\n\n4. **Load Capacity Targets**\n   - Read `/data/capacity.yml` using yaml.safe_load\n   - Format: `{ \"email@example.com\": hours_available }`\n   - Example:\n     ```yaml\n     alice@example.com: 40\n     bob@example.com: 30\n     ```\n   - Handle file read errors gracefully\n\n5. **Compute Utilization**\n   - Extract `estimate_point` field from each issue (default to 8 if missing)\n   - Aggregate total hours per assignee from issue assignments\n   - If no real assignees exist, generate demo data:\n     * Use capacity targets as base\n     * Generate random utilization between 60-95% (deterministic by email)\n   - Calculate: `utilization_pct = (hours_allocated / capacity) * 100`\n   - Determine risk level:\n     * 'high' if utilization > 100%\n     * 'medium' if 80% <= utilization <= 100%\n     * 'low' if utilization < 80%\n\n6. **Write to DynamoDB**\n   - Endpoint: http://localstack:4566 (env: LOCALSTACK_URL)\n   - Region: us-east-1\n   - Credentials: aws_access_key_id='test', aws_secret_access_key='test'\n   - Table: 'sprint-capacity'\n   - Use PutItem with DynamoDB format:\n     ```python\n     {\n       'assignee': {'S': email},\n       'sprint_id': {'S': 'current'},\n       'capacity': {'N': str(capacity)},\n       'hours_allocated': {'N': str(hours)},\n       'utilization_pct': {'N': str(round(pct, 2))},\n       'risk': {'S': risk_level},\n       'timestamp': {'S': iso_timestamp}\n     }\n     ```\n   - Write one record per assignee\n\n7. **Output Requirements**\n   - Progress to stderr:\n     * \"Starting sprint capacity analysis...\"\n     * \"Fetching Plane projects...\"\n     * \"Using project: {name}\"\n     * \"Fetching sprint issues...\"\n     * \"Loading capacity targets...\"\n     * \"Computing utilization...\"\n     * \"Writing to DynamoDB...\"\n   - Final output to stdout:\n     * Header: \"Sprint capacity: {N} assignees\"\n     * Per assignee (sorted by utilization descending): \"{email}: {utilization}% ({risk})\"\n     * Example:\n       ```\n       Sprint capacity: 3 assignees\n       alice@example.com: 95.5% (medium)\n       bob@example.com: 87.3% (medium)\n       charlie@example.com: 65.0% (low)\n       ```\n\n**Technical Details:**\n- Script location: /app/sprint_capacity.py\n- Language: Python 3\n- Required imports: boto3, requests, yaml, os, sys, json, shutil, datetime, collections, pathlib\n- Timeout for API calls: 30 seconds\n- Exit code: 0 (always succeed, handle failures gracefully)\n\n**Prerequisites (already available):**\n- Plane workspace and project configured\n- LocalStack running with DynamoDB\n- Table 'sprint-capacity' exists\n- capacity.yml file at /data/capacity.yml\n- Python 3 with boto3, requests, pyyaml libraries\n\n**Success Criteria:**\n- Script executes without errors\n- Fetches projects and issues from Plane\n- Loads capacity from YAML file\n- Calculates utilization correctly\n- Writes records to DynamoDB\n- Output format matches specification\n- Risk flags are accurate based on thresholds",
  "state": "open",
  "createdAt": "Nov 20, 2025, 9:12:00 AM",
  "closedAt": "",
  "labels": [
    { "name": "type:Integration" },
    { "name": "component:Sprint Planning" },
    { "name": "tool:Plane" },
    { "name": "tool:LocalStack" },
    { "name": "difficulty:Medium" }
  ],
  "assignees": [
    { "login": "Scrum Master" }
  ],
  "author": null,
  "url": "https://holder-url.com"
}
```
