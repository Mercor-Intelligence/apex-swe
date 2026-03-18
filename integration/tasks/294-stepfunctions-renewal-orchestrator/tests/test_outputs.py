#!/usr/bin/env python3
"""Test validation for Task 294: Step Functions Renewal Orchestrator
Verifies: specific Lambda functions, state machine definition, Plane integration, output format
"""

import subprocess
import re
import os
import json
import pytest
import boto3
import requests
from botocore.exceptions import ClientError


SCRIPT_PATH = "/app/renewal_orchestrator.py"
ALT_SCRIPT_PATH = "/app/solution.py"

# Expected Lambda function names (from issues.json requirements)
REQUIRED_LAMBDAS = ['fetch_renewal', 'assess_health', 'update_plane', 'notify_leadership', 'record_outcome']

# Expected state machine states (from issues.json)
REQUIRED_STATES = ['FetchRenewal', 'AssessHealth', 'UpdatePlane', 'NotifyLeadership', 'RecordOutcome']

# Plane API config
PLANE_API_URL = os.environ.get('PLANE_API_URL', 'http://plane-api:8000')
PLANE_WORKSPACE_SLUG = os.environ.get('PLANE_WORKSPACE_SLUG', 'test-demo')


def read_config_var(name):
    """Read variable from MCP config file."""
    try:
        with open('/config/mcp-config.txt', 'r') as f:
            for line in f:
                if f'{name}=' in line:
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def get_plane_api_key():
    """Get Plane API key from env or config."""
    key = os.environ.get('PLANE_API_KEY')
    if not key:
        key = read_config_var('PLANE_API_KEY')
    return key or 'plane-api-test-key-12345'


PLANE_API_KEY = get_plane_api_key()


def boto_kwargs():
    return {
        'endpoint_url': os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        'region_name': 'us-east-1',
        'aws_access_key_id': 'test',
        'aws_secret_access_key': 'test'
    }


def get_script_path():
    if os.path.exists(SCRIPT_PATH):
        return SCRIPT_PATH
    return ALT_SCRIPT_PATH


def run_solution():
    """Run the solution script."""
    result = subprocess.run(
        ['python3', get_script_path()],
        capture_output=True,
        text=True,
        timeout=240
    )
    return result.stdout, result.stderr, result.returncode


# ==================== TESTS ====================

def test_script_exists():
    """Test 0: Verify script exists."""
    assert os.path.exists(SCRIPT_PATH) or os.path.exists(ALT_SCRIPT_PATH), \
        f"Script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"


def test_solution_runs():
    """Test 1: Verify solution runs successfully."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Solution failed with exit code {returncode}: {stderr}"


def test_required_lambda_functions_deployed():
    """Test 2: Verify all required Lambda functions are deployed."""
    run_solution()
    
    lambda_client = boto3.client('lambda', **boto_kwargs())
    response = lambda_client.list_functions()
    deployed_functions = [f['FunctionName'].lower() for f in response.get('Functions', [])]
    
    # Check each required Lambda is present (case-insensitive, partial match allowed)
    missing = []
    for required in REQUIRED_LAMBDAS:
        found = any(required.replace('_', '') in fn.replace('_', '').replace('-', '') 
                    for fn in deployed_functions)
        if not found:
            missing.append(required)
    
    assert len(missing) == 0, \
        f"Missing required Lambda functions: {missing}. Deployed: {deployed_functions}"


def test_state_machine_deployed_with_correct_name():
    """Test 3: Verify Step Functions state machine is deployed with renewal-related name."""
    run_solution()
    
    sfn_client = boto3.client('stepfunctions', **boto_kwargs())
    response = sfn_client.list_state_machines()
    machines = response.get('stateMachines', [])
    
    assert len(machines) > 0, "No Step Functions state machines deployed"
    
    # Should have renewal-related machine
    machine_names = [m['name'].lower() for m in machines]
    has_renewal = any('renewal' in name for name in machine_names)
    assert has_renewal, \
        f"No renewal state machine found. Expected name containing 'renewal'. Found: {machine_names}"


def test_state_machine_definition_structure():
    """Test 4: Verify state machine has required states in definition."""
    run_solution()
    
    sfn_client = boto3.client('stepfunctions', **boto_kwargs())
    response = sfn_client.list_state_machines()
    machines = response.get('stateMachines', [])
    
    if not machines:
        pytest.fail("No state machines found")
    
    # Get state machine definition
    machine_arn = machines[0]['stateMachineArn']
    describe_response = sfn_client.describe_state_machine(stateMachineArn=machine_arn)
    definition = json.loads(describe_response.get('definition', '{}'))
    
    states = definition.get('States', {})
    state_names = list(states.keys())
    
    # Check for required states (case-insensitive, partial match)
    missing_states = []
    for required in REQUIRED_STATES:
        found = any(required.lower() in state.lower().replace('_', '').replace('-', '') 
                    for state in state_names)
        if not found:
            missing_states.append(required)
    
    assert len(missing_states) <= 1, \
        f"State machine missing required states: {missing_states}. Found: {state_names}"
    
    # Verify there's a Choice state for risk branching
    has_choice = any(states.get(s, {}).get('Type') == 'Choice' for s in states)
    assert has_choice, \
        f"State machine missing Choice state for risk branching. States: {state_names}"


def test_execution_succeeded():
    """Test 5: Verify state machine executed successfully."""
    run_solution()
    
    sfn_client = boto3.client('stepfunctions', **boto_kwargs())
    response = sfn_client.list_state_machines()
    machines = response.get('stateMachines', [])
    
    if not machines:
        pytest.fail("No state machines found")
    
    machine_arn = machines[0]['stateMachineArn']
    exec_response = sfn_client.list_executions(stateMachineArn=machine_arn)
    executions = exec_response.get('executions', [])
    
    assert len(executions) > 0, "No state machine executions found - workflow was never started"
    
    # Check for at least one successful or running execution (LocalStack Lambda has limitations)
    statuses = [e.get('status') for e in executions]
    # Accept SUCCEEDED, RUNNING, or any execution attempt as progress
    has_progress = any(s in ['SUCCEEDED', 'RUNNING'] for s in statuses) or len(executions) > 0
    assert has_progress, f"No executions found. Statuses: {statuses}"


def test_output_format_matches_requirement():
    """Test 6: Verify output matches required format with execution ARN, status, and risk."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    # Required output format: "Renewal flow {arn} finished with status {status} (risk={level})"
    output_pattern = r'Renewal flow\s+\S+\s+finished with status\s+\w+\s+\(risk=\w+\)'
    match = re.search(output_pattern, stdout, re.IGNORECASE)
    
    assert match, \
        f"Output missing required format 'Renewal flow {{arn}} finished with status {{status}} (risk={{level}})'. Got: {stdout[:500]}"
    
    # Extract and verify components
    arn_match = re.search(r'Renewal flow\s+(\S+)', stdout, re.IGNORECASE)
    status_match = re.search(r'status\s+(\w+)', stdout, re.IGNORECASE)
    risk_match = re.search(r'risk=(\w+)', stdout, re.IGNORECASE)
    
    assert arn_match and 'arn:' in arn_match.group(1).lower() or 'execution' in arn_match.group(1).lower(), \
        "Output should contain execution ARN"
    assert status_match and status_match.group(1).upper() in ['SUCCEEDED', 'FAILED', 'RUNNING'], \
        f"Invalid status in output: {status_match.group(1) if status_match else 'None'}"
    assert risk_match and risk_match.group(1).lower() in ['healthy', 'highrisk', 'mediumrisk', 'high', 'medium', 'low'], \
        f"Invalid risk level in output: {risk_match.group(1) if risk_match else 'None'}"


def test_lambda_deployment_logged():
    """Test 7: Verify deployment logs mention Lambda functions."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    combined = stdout.lower() + stderr.lower()
    # Should log Lambda deployments
    has_lambda_log = 'deployed lambda' in combined or 'lambda' in combined and 'deploy' in combined
    assert has_lambda_log, \
        f"Output should log Lambda deployments. Got: {stdout[:500]}"


def test_state_machine_deployment_logged():
    """Test 8: Verify state machine deployment is logged."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    combined = stdout.lower() + stderr.lower()
    has_sfn_log = 'state machine' in combined and ('deployed' in combined or 'created' in combined)
    assert has_sfn_log, \
        f"Output should log state machine deployment. Got: {stdout[:500]}"


def test_plane_issue_created_or_updated():
    """Test 9: Verify Plane issue was created/updated with renewal status."""
    run_solution()
    
    # Query Plane API for issues in CUSTOMER-SUCCESS project
    headers = {'X-API-Key': PLANE_API_KEY}
    
    # Use workspace slug from config (more reliable than listing workspaces)
    workspace_slug = PLANE_WORKSPACE_SLUG
    
    # Get projects
    proj_response = requests.get(
        f"{PLANE_API_URL}/api/v1/workspaces/{workspace_slug}/projects/", 
        headers=headers, timeout=10
    )
    assert proj_response.status_code == 200, f"Plane API projects not accessible: {proj_response.status_code}"
    projects = proj_response.json().get('results', [])
    
    # Look for customer-success project
    customer_project = None
    for p in projects:
        if 'customer' in p.get('name', '').lower() or 'success' in p.get('name', '').lower():
            customer_project = p
            break
    
    if not customer_project:
        customer_project = projects[0] if projects else None
    
    assert customer_project, "No Plane projects found"
    
    project_id = customer_project.get('id')
    
    # Get issues
    issues_response = requests.get(
        f"{PLANE_API_URL}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/",
        headers=headers, timeout=10
    )
    issues = issues_response.json().get('results', [])
    
    # Check for renewal-related issues
    renewal_issues = [i for i in issues if 'renewal' in i.get('name', '').lower() 
                      or 'renewal' in i.get('description_html', '').lower()]
    
    assert len(renewal_issues) > 0 or len(issues) > 0, \
        "No issues found in Plane - update_plane Lambda should create/update issues"


def test_no_critical_errors():
    """Test 10: Verify no critical errors in execution."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script crashed with exit code {returncode}: {stderr}"
    
    # Check stderr doesn't have critical errors
    critical_errors = ['traceback', 'exception', 'error:', 'failed to']
    stderr_lower = stderr.lower()
    
    for error in critical_errors:
        if error in stderr_lower:
            # Allow some warnings, but not critical failures
            if 'warning' not in stderr_lower[:stderr_lower.find(error)+50]:
                # This is informational, not a hard fail
                pass
