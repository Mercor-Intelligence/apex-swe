## Issue 82
**Topic**: LocalStack IAM Simulation

## Problem Statement
Using boto3 IAM client, create IAM user named `test-user` in LocalStack. Create access key for user and write to file at `/app/iam_output.txt` with format: "Created user: test-user, Access Key: [key_id]".

**LocalStack**: http://localstack:4566

**Tools needed**: LocalStack (IAM)

## Prerequisites
- None (IAM user created by the task)
- LocalStack IAM is already running and accessible

## Solution

### Objective
Create IAM user and access key, write output to file.

### Solution Approach
1. **Script**
   - IAM Operations:
     - Create user: `test-user`
     - Create access key for user
   - Output: Write `"Created user: test-user, Access Key: {key_id}"` to `/app/iam_output.txt`

2. **Solution YAML**
   - command: `python /app/create_iam_user.py`

### Key Points
- LocalStack IAM endpoint: `http://localstack:4566`
- User name: `test-user`
- Write access key ID to file at `/app/iam_output.txt`

## Tests

### Test Objectives
Verify IAM user and access key creation.

### Test Functions
**Test 1**: `test_localstack_accessible()`
- **Purpose**: Prerequisite check
- **Steps**: Verify LocalStack is accessible
- **Why**: Tests environment

**Test 2**: `test_output_file_exists()`
- **Purpose**: Verify output file creation
- **Steps**: Check if `/app/iam_output.txt` exists
- **Why**: Tests file output

**Test 3**: `test_user_created()`
- **Purpose**: Verify user creation
- **Steps**: List IAM users via boto3, assert `test-user` exists
- **Why**: Tests user creation

**Test 4**: `test_access_key_created()`
- **Purpose**: Verify key generation
- **Steps**: List access keys for user, verify exists
- **Why**: Tests key creation

**Test 5**: `test_output_format()`
- **Purpose**: Verify output format
- **Steps**: Read file, verify format matches expected pattern
- **Why**: Tests correct output format

### Test Principles
- User creation: IAM user exists in LocalStack
- Access key: Key generated for user
- Output: File contains correct format

## Ticket JSON
```json
{
  "number": 45078,
  "title": "Simple IAM User and Access Key Creation Test",
  "body": "Using boto3 IAM client, create IAM user named test-user in LocalStack. Create access key for user and write to file at /app/iam_output.txt with format: Created user: test-user, Access Key: [key_id].\n\n**Environment:**\n- User name: test-user\n- Output access key ID to file\n\n**Prerequisites (already available):**\n- LocalStack IAM is already running and accessible at http://localstack:4566",
  "state": "open",
  "createdAt": "Oct 22, 2025, 12:00:00 PM",
  "closedAt": "",
  "labels": [
    {
      "name": "component:IAM/Security"
    },
    {
      "name": "type:Integration"
    },
    {
      "name": "tool:LocalStack"
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

## Implementation Notes
- Modified from print to file output for deterministic testing
- All paths use `/app` instead of `/app` for consistency
- IAM service enabled in LocalStack configuration
- Uses boto3 SDK for AWS operations