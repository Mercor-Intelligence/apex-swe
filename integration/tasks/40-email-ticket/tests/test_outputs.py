#!/usr/bin/env python3
"""Pytest tests for email to ticket converter task."""

import requests
import pytest


def read_plane_api_key():
    """Read Plane API key from MCP config file"""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('export PLANE_API_KEY='):
                    return line.split('=', 1)[1].strip()
    except Exception as e:
        pytest.fail(f"Error reading Plane API key: {e}")
    return None


def get_plane_project_id(api_key):
    """Get the Plane project UUID for TEST project"""
    try:
        url = "http://plane-api:8000/api/v1/workspaces/test-demo/projects/"
        headers = {"X-API-Key": api_key}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        projects = response.json()
        for project in projects.get('results', []):
            if project.get('identifier') == 'TEST':
                return project.get('id')
        return None
    except Exception as e:
        pytest.fail(f"Error fetching project ID: {e}")


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    import os
    script_path = "/app/email_to_ticket.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path} or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    import os
    import subprocess
    
    script_path = "/app/email_to_ticket.py"
    if not os.path.exists(script_path):
        script_path = "/app/solution.py"
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"


def test_plane_issue_created_from_email():
    """Test that a Plane issue was created from the email."""
    # Get latest email from MailHog
    response = requests.get("http://mailhog:8025/api/v2/messages?limit=1", timeout=10)
    response.raise_for_status()
    data = response.json()

    assert data.get('items'), "No emails found in MailHog"

    email_subject = data['items'][0]['Content']['Headers']['Subject'][0]

    # Get Plane API key
    api_key = read_plane_api_key()
    assert api_key, "Could not read Plane API key"

    # Get project ID
    project_id = get_plane_project_id(api_key)
    assert project_id, "Could not find TEST project"

    # Query Plane for issue with matching title
    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json().get('results', [])

    # Look for issue with matching subject
    found_issue = None
    for issue in issues:
        if issue.get('name') == email_subject:
            found_issue = issue
            break

    assert found_issue, f"No issue found with subject '{email_subject}'"


def test_issue_title_matches_email_subject():
    """Test that the issue title matches the email subject."""
    # Get email subject from MailHog
    response = requests.get("http://mailhog:8025/api/v2/messages?limit=1", timeout=10)
    response.raise_for_status()
    data = response.json()

    assert data.get('items'), "No emails found"

    expected_subject = data['items'][0]['Content']['Headers']['Subject'][0]

    # Get Plane API key and project ID
    api_key = read_plane_api_key()
    assert api_key, "Could not read Plane API key"

    project_id = get_plane_project_id(api_key)
    assert project_id, "Could not find TEST project"

    # Find Plane issue
    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json().get('results', [])

    # Look for issue with matching subject
    found_issue = None
    for issue in issues:
        if issue.get('name') == expected_subject:
            found_issue = issue
            break

    assert found_issue, "No issue found"

    actual_title = found_issue.get('name', '')

    assert actual_title == expected_subject, \
        f"Title mismatch - Expected: {expected_subject}, Got: {actual_title}"


def test_issue_description_matches_email_body():
    """Test that the issue description contains the email body."""
    # Get email body
    response = requests.get("http://mailhog:8025/api/v2/messages?limit=1", timeout=10)
    response.raise_for_status()
    data = response.json()

    assert data.get('items'), "No emails found"

    email_subject = data['items'][0]['Content']['Headers']['Subject'][0]
    expected_body = data['items'][0]['Content']['Body']

    # Get Plane API key and project ID
    api_key = read_plane_api_key()
    assert api_key, "Could not read Plane API key"

    project_id = get_plane_project_id(api_key)
    assert project_id, "Could not find TEST project"

    # Find Plane issue description
    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json().get('results', [])

    # Look for issue with matching subject
    found_issue = None
    for issue in issues:
        if issue.get('name') == email_subject:
            found_issue = issue
            break

    assert found_issue, "No issue found"

    description_html = found_issue.get('description_html', '')

    assert expected_body in description_html, \
        f"Description does not contain email body\nExpected: {expected_body[:100]}...\nGot: {description_html[:100]}..."


def test_issue_has_medium_priority():
    """Test that the issue has medium priority."""
    # Get email subject to find the issue
    response = requests.get("http://mailhog:8025/api/v2/messages?limit=1", timeout=10)
    response.raise_for_status()
    data = response.json()

    assert data.get('items'), "No emails found"

    email_subject = data['items'][0]['Content']['Headers']['Subject'][0]

    # Get Plane API key and project ID
    api_key = read_plane_api_key()
    assert api_key, "Could not read Plane API key"

    project_id = get_plane_project_id(api_key)
    assert project_id, "Could not find TEST project"

    # Find created Plane issue
    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json().get('results', [])

    # Look for issue with matching subject
    found_issue = None
    for issue in issues:
        if issue.get('name') == email_subject:
            found_issue = issue
            break

    assert found_issue, "No issue found"

    priority = found_issue.get('priority', '')

    assert priority == 'medium', f"Priority mismatch - Expected: medium, Got: {priority}"
