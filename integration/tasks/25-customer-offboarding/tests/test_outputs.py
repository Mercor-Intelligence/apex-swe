import base64
import json
import time
import requests
import pytest
import re
import os
import subprocess


SCRIPT_PATH = "/app/update_lead.py"
ALT_SCRIPT_PATH = "/app/solution.py"

_script_result = None

def run_script_once():
    """Run the script once and cache result."""
    global _script_result
    if _script_result is None:
        script_path = SCRIPT_PATH if os.path.exists(SCRIPT_PATH) else ALT_SCRIPT_PATH
        result = subprocess.run(['python3', script_path], capture_output=True, text=True, timeout=120)
        _script_result = result
    return _script_result


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    assert os.path.exists(SCRIPT_PATH) or os.path.exists(ALT_SCRIPT_PATH), \
        f"Required script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"


def test_script_runs_successfully():
    """Test 1: Verify script executes without errors."""
    result = run_script_once()
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"


def test_output_format_matches_requirement():
    """Test 2: Verify output matches 'Updated lead {id}: status set to Dead' format."""
    import re
    result = run_script_once()
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    pattern = r'Updated lead \S+:? status set to Dead'
    match = re.search(pattern, result.stdout, re.IGNORECASE)
    assert match, f"Output missing required format. Got: {result.stdout[:500]}"


def get_espocrm_token():
    """
    Authenticate with EspoCRM and return the token.
    """
    base_url = "http://espocrm"
    username = "admin"
    password = "ChangeMe123"

    auth_header = base64.b64encode(f"{username}:{password}".encode()).decode()

    response = requests.get(
        f"{base_url}/api/v1/App/user",
        headers={"Espo-Authorization": auth_header},
        timeout=30,
    )

    assert response.status_code == 200, f"Authentication failed: {response.status_code}"

    user_data = response.json()
    assert "token" in user_data, "No token in response"

    return user_data["token"]


def search_lead_by_name(token, first_name="John", last_name="Doe"):
    """
    Search for a lead by firstName and lastName.
    Returns the list of matching leads.
    """
    base_url = "http://espocrm"
    username = "admin"

    token_auth_header = base64.b64encode(f"{username}:{token}".encode()).decode()

    search_params = {
        "where[0][type]": "equals",
        "where[0][attribute]": "firstName",
        "where[0][value]": first_name,
        "where[1][type]": "equals",
        "where[1][attribute]": "lastName",
        "where[1][value]": last_name,
    }

    response = requests.get(
        f"{base_url}/api/v1/Lead",
        headers={
            "Espo-Authorization": token_auth_header,
            "X-No-Total": "true"
        },
        params=search_params,
        timeout=30,
    )

    assert response.status_code == 200, f"Search failed: {response.status_code}"

    search_data = response.json()
    return search_data.get("list", [])


def test_lead_exists():
    """
    Test 1: Verify prerequisite lead exists.

    Purpose: Verify prerequisite lead exists
    Steps:
        1. Search EspoCRM for lead with firstName "John" and lastName "Doe"
        2. Assert lead exists in results
    Why: Validates environment setup
    """
    # Get authentication token
    token = get_espocrm_token()

    # Search for lead with firstName "John" and lastName "Doe"
    leads = search_lead_by_name(token, "John", "Doe")

    # Assert lead exists in results
    assert len(leads) > 0, "Lead with firstName 'John' and lastName 'Doe' not found"

    # Verify the lead has expected fields
    lead = leads[0]
    assert "id" in lead, "Lead missing 'id' field"
    assert lead.get("firstName") == "John", "Lead firstName doesn't match"
    assert lead.get("lastName") == "Doe", "Lead lastName doesn't match"


def test_lead_status_updated():
    """
    Test 2: Verify status changed to Dead.

    Purpose: Verify status changed to Dead
    Steps:
        1. Search for lead with firstName "John" and lastName "Doe" after script runs
        2. Assert `status` == "Dead"
    Why: Tests update operation
    """
    # Get authentication token
    token = get_espocrm_token()

    # Search for lead with firstName "John" and lastName "Doe"
    leads = search_lead_by_name(token, "John", "Doe")

    # Assert lead exists
    assert len(leads) > 0, "Lead with firstName 'John' and lastName 'Doe' not found"

    # Get the first matching lead
    lead = leads[0]

    # Assert status is "Dead"
    assert "status" in lead, "Lead missing 'status' field"
    assert lead.get("status") == "Dead", f"Expected status 'Dead', but got '{lead.get('status')}'"
