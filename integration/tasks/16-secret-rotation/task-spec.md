# Issue 16
# Topic: Secret Rotation

## Problem Statement

Using boto3, fetch the secret named `api-token-secret` from AWS Secrets Manager and print the secret value to stdout. The secret contains a JSON string with keys: `{api_key, created_at}`. Parse and print only the `api_key` value. LocalStack endpoint: `http://localhost:4566`.
   
   **Tools needed**: LocalStack (Secrets Manager)
   
   **Prerequisites**: AWS Secrets Manager secret `api-token-secret` must exist with JSON value `{"api_key": "test-key-123", "created_at": "2025-01-01T00:00:00Z"}`.

---

## Solution

# Solution: Task 6 - Secret Rotation

## Objective
Fetch secret from AWS Secrets Manager and print the api_key value.

## Solution Approach

### 1. Boto3 Secrets Manager Client

**Setup:**
- Configure boto3 client with LocalStack endpoint
- `endpoint_url='http://localhost:4566'`
- Dummy credentials

### 2. Fetch Secret

**Get Secret Value:**
- Use `secretsmanager_client.get_secret_value(SecretId='api-token-secret')`
- Extract `SecretString` from response

### 3. Parse JSON

**Parse Secret:**
- Secret contains JSON string
- Parse: `json.loads(secret_string)`
- Extract keys: `api_key`, `created_at`

### 4. Print API Key

**Output:**
- Print only the `api_key` value
- Not the entire JSON, just the key value

### 5. Solution YAML Structure

```yaml
- command: |
    cat > /app/fetch_secret.py << 'EOF'
    #!/usr/bin/env python3
    import boto3
    import json
    
    # Client setup
    # Get secret value
    # Parse JSON
    # Print api_key
    EOF
    chmod +x /app/fetch_secret.py

- command: python /app/fetch_secret.py
  min_timeout_sec: 30
```

## Key Points
- Secret name: `api-token-secret`
- SecretString is JSON format
- Print only `api_key`, not whole JSON
- LocalStack endpoint required
- Secret must exist as prerequisite


---

## Tests

# Tests: Task 6 - Secret Rotation

## Test Objectives
Verify secret fetch, JSON parsing, and correct output.

## Test Functions

### Test 1: `test_secret_exists()`
**Purpose:** Verify prerequisite secret exists

**Steps:**
1. Create Secrets Manager client with LocalStack endpoint
2. Get secret: `get_secret_value(SecretId='api-token-secret')`
3. Assert no exception raised

**Why:** Validates environment setup

---

### Test 2: `test_secret_contains_json()`
**Purpose:** Verify secret has correct format

**Steps:**
1. Get secret value
2. Parse SecretString as JSON
3. Assert parse succeeds
4. Assert has keys: `api_key`, `created_at`

**Why:** Confirms secret structure

---

### Test 3: `test_script_prints_api_key()`
**Purpose:** Verify script outputs api_key

**Steps:**
1. Run script and capture stdout
2. Get expected api_key from secret
3. Assert script output contains api_key value
4. Assert output does NOT contain full JSON (not printing entire dict)

**Why:** Tests correct output

---

### Test 4: `test_output_is_only_api_key()`
**Purpose:** Verify output is just the key, not other fields

**Steps:**
1. Run script and capture stdout
2. Assert output does not contain `created_at` value
3. Assert output does not contain curly braces or JSON structure

**Why:** Tests precise output format

---

## Test Principles
- **Direct verification:** Fetch secret independently to compare
- **Output validation:** Check stdout contains only required value
- **JSON parsing:** Ensure script properly parses SecretString
- **Cleanup:** Secret should not be modified by script

---

## Ticket Header

**Project:** Security & Infrastructure  
**Issue Type:** Task  
**Priority:** Low  
**Component:** Secrets Management  
**Labels:** localstack, secrets-manager, security, easy  
**Sprint:** Current Sprint  
**Story Points:** 2  

**Summary:** Secret Retrieval Script for API Token Access

## Ticket Content

### Description

Create a basic script to retrieve API tokens from AWS Secrets Manager for secure credential management. This establishes the foundation for our secrets management strategy by demonstrating how applications can fetch credentials at runtime rather than storing them in code or configuration files. The script should authenticate with Secrets Manager, fetch the specified secret, parse the JSON structure, and output only the API key value for use by other systems or scripts.

### Technical Requirements

**Environment:**
- LocalStack Secrets Manager on `http://localhost:4566`
- Python 3.x with `boto3` library
- Secret `api-token-secret` must exist with JSON structure

### Dependencies

- Secret must be pre-created with JSON format: `{"api_key": "...", "created_at": "..."}`
- Script must handle JSON parsing of SecretString field
- Output should be clean (only API key) for pipeline integration

