import subprocess
#!/usr/bin/env python3
"""Pytest tests for LocalStack IAM user creation task."""

import boto3
import os
import re
import pytest


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/create_iam_user.py"
    legacy_path = "/app/iam_user.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(legacy_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path}, {legacy_path}, or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    script_path = "/app/create_iam_user.py"
    legacy_path = "/app/iam_user.py"
    if not os.path.exists(script_path):
        if os.path.exists(legacy_path):
            script_path = legacy_path
        else:
            script_path = "/app/solution.py"
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"




def test_localstack_accessible():
    """Test that LocalStack is accessible (prerequisite check)."""
    localstack_endpoint = "http://localstack:4566"

    # Try to create IAM client and list users
    iam_client = boto3.client(
        'iam',
        endpoint_url=localstack_endpoint,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )

    iam_client.list_users()


def test_output_file_exists():
    """Test that the output file was created."""
    output_file = "/app/iam_output.txt"
    assert os.path.exists(output_file), f"Output file not found at {output_file}"


def test_user_created():
    """Test that the IAM user 'test-user' was created in LocalStack."""
    user_name = "test-user"
    localstack_endpoint = "http://localstack:4566"

    # Create IAM client
    iam_client = boto3.client(
        'iam',
        endpoint_url=localstack_endpoint,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )

    # List users
    response = iam_client.list_users()
    users = [user['UserName'] for user in response['Users']]

    assert user_name in users, f"User '{user_name}' not found in LocalStack"


def test_access_key_created():
    """Test that an access key was created for the user."""
    user_name = "test-user"
    localstack_endpoint = "http://localstack:4566"

    # Create IAM client
    iam_client = boto3.client(
        'iam',
        endpoint_url=localstack_endpoint,
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )

    # List access keys for the user
    response = iam_client.list_access_keys(UserName=user_name)
    access_keys = response['AccessKeyMetadata']

    assert len(access_keys) > 0, f"No access keys found for user '{user_name}'"


def test_output_format():
    """Test that the output file contains the correct format."""
    output_file = "/app/iam_output.txt"
    expected_pattern = r"^Created user: test-user, Access Key: [A-Z0-9]+$"

    with open(output_file, 'r') as f:
        content = f.read().strip()

    assert re.match(expected_pattern, content), \
        f"Output format doesn't match expected pattern: {expected_pattern}\nGot: '{content}'"
