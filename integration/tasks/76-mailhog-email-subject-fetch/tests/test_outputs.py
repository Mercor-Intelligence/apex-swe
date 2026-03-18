#!/usr/bin/env python3
"""Pytest tests for MailHog email subject fetcher task."""

import requests
import os
import pytest


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/fetch_email_subject.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path} or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    import subprocess
    
    script_path = "/app/fetch_email_subject.py"
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


def test_mailhog_has_email():
    """Test that MailHog has at least one email (prerequisite check)."""
    mailhog_url = "http://mailhog:8025/api/v2/messages"

    response = requests.get(mailhog_url, timeout=10)
    response.raise_for_status()
    data = response.json()

    total = data.get('total', 0)
    assert total > 0, "MailHog has no emails"


def test_output_file_exists():
    """Test that the output file was created."""
    output_file = "/app/email_subject.txt"
    assert os.path.exists(output_file), f"Output file not found at {output_file}"


def test_subject_matches_latest_email():
    """Test that the subject in the file matches the latest email in MailHog."""
    output_file = "/app/email_subject.txt"
    mailhog_url = "http://mailhog:8025/api/v2/messages"

    # Fetch latest email from MailHog API
    response = requests.get(f"{mailhog_url}?limit=1", timeout=10)
    response.raise_for_status()
    data = response.json()

    assert data.get('items') and len(data['items']) > 0, "No emails found in MailHog"

    # Get expected subject
    expected_subject = data['items'][0]['Content']['Headers']['Subject'][0]

    # Read the subject from the output file
    with open(output_file, 'r') as f:
        actual_subject = f.read().strip()

    assert actual_subject == expected_subject, \
        f"Subject mismatch - Expected: '{expected_subject}', Got: '{actual_subject}'"
