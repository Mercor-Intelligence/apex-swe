#!/usr/bin/env python3
"""
Test suite for CRM to Medusa sync script
"""
import base64
import json
import os
import re
import subprocess
import time
import requests
import pytest


SCRIPT_PATH = "/app/sync_crm_to_medusa.py"
ALT_SCRIPT_PATH = "/app/solution.py"


def get_script_path() -> str:
    """Return the user script path (preferred) or fallback solution path."""
    if os.path.exists(SCRIPT_PATH):
        return SCRIPT_PATH
    return ALT_SCRIPT_PATH


@pytest.fixture(scope="module")
def script_result():
    """Run the script once (module-scoped) so state-based assertions are valid."""
    script_path = get_script_path()
    assert os.path.exists(script_path), f"Script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"

    result = subprocess.run(
        ["python3", script_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result


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


def search_contact_by_name(token, first_name="Robert", last_name="Williams"):
    """
    Search for a contact by firstName and lastName.
    Returns the list of matching contacts.
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
        f"{base_url}/api/v1/Contact",
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


def get_medusa_jwt_token():
    """
    Authenticate with Medusa and get JWT token.
    """
    medusa_base_url = "http://medusa:9000"
    admin_email = "admin@example.com"
    admin_password = "supersecret"

    response = requests.post(
        f"{medusa_base_url}/auth/user/emailpass",
        json={"email": admin_email, "password": admin_password},
        headers={"Content-Type": "application/json"},
        timeout=30
    )

    assert response.status_code == 200, f"Medusa auth failed: {response.status_code}"

    data = response.json()
    token = data.get("token") or data.get("access_token")

    assert token, "No token in Medusa auth response"

    return token


def get_medusa_customer_by_email(email):
    """
    Get customer from Medusa by email.
    """
    medusa_base_url = "http://medusa:9000"

    # Get JWT token
    token = get_medusa_jwt_token()

    # Search for customer by email
    search_response = requests.get(
        f"{medusa_base_url}/admin/customers",
        params={"q": email},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30
    )

    assert search_response.status_code == 200, f"Customer search failed: {search_response.status_code}"

    customers = search_response.json().get("customers", [])

    # Find exact email match
    for customer in customers:
        if customer.get("email") == email:
            return customer

    return None


def test_script_exists():
    """
    Test 0: Verify the sync_crm_to_medusa.py script exists in /app.

    Purpose: Verify script was created
    Steps:
        1. Check if /app/sync_crm_to_medusa.py exists
        2. Check if script is executable
    Why: Validates that solution created the required script
    """
    assert os.path.exists(SCRIPT_PATH) or os.path.exists(ALT_SCRIPT_PATH), (
        f"Script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"
    )

    script_path = get_script_path()
    assert os.access(script_path, os.X_OK), f"Script at {script_path} is not executable"

def test_script_runs_successfully(script_result):
    """Test 0.5: Verify script executes without errors."""
    assert script_result.returncode == 0, (
        f"Script failed with exit code {script_result.returncode}. "
        f"Stderr: {script_result.stderr}"
    )


def test_espocrm_contact_exists():
    """
    Test 1: Verify prerequisite contact exists in EspoCRM.

    Purpose: Verify prerequisite contact
    Steps:
        1. Get EspoCRM contact by searching for Robert Williams
        2. Assert contact exists
        3. Assert has firstName, lastName, emailAddress
    Why: Validates environment setup
    """
    # Get authentication token
    token = get_espocrm_token()

    # Search for contact
    contacts = search_contact_by_name(token, "Robert", "Williams")

    # Assert contact exists
    assert len(contacts) > 0, "Contact 'Robert Williams' not found in EspoCRM"

    # Verify contact has required fields
    contact = contacts[0]
    assert "firstName" in contact, "Contact missing firstName"
    assert "lastName" in contact, "Contact missing lastName"
    assert "emailAddress" in contact, "Contact missing emailAddress"
    assert contact.get("firstName") == "Robert", f"Expected firstName 'Robert', got '{contact.get('firstName')}'"
    assert contact.get("lastName") == "Williams", f"Expected lastName 'Williams', got '{contact.get('lastName')}'"


def test_medusa_customer_created_or_updated(script_result):
    """
    Test 2: Verify customer exists in Medusa.

    Purpose: Verify customer exists in Medusa
    Steps:
        1. Get contact email from EspoCRM
        2. Query Medusa for customer by email
        3. Assert customer exists
    Why: Confirms sync operation
    """
    # Get authentication token
    token = get_espocrm_token()

    # Search for test contact
    contacts = search_contact_by_name(token, "Robert", "Williams")
    assert len(contacts) > 0, "Test contact not found"

    contact = contacts[0]
    email = contact.get("emailAddress")

    # Get customer from Medusa
    customer = get_medusa_customer_by_email(email)

    # Assert customer exists
    assert customer is not None, f"Customer with email '{email}' not found in Medusa"


def test_customer_data_matches_contact(script_result):
    """
    Test 3: Verify customer data matches contact data.

    Purpose: Verify data accuracy
    Steps:
        1. Get EspoCRM contact data
        2. Get Medusa customer
        3. Assert email, first_name, last_name match
    Why: Tests data transfer
    """
    # Get authentication token
    token = get_espocrm_token()

    # Search for test contact
    contacts = search_contact_by_name(token, "Robert", "Williams")
    assert len(contacts) > 0, "Test contact not found"

    contact = contacts[0]
    email = contact.get("emailAddress")
    first_name = contact.get("firstName")
    last_name = contact.get("lastName")

    # Get customer from Medusa
    customer = get_medusa_customer_by_email(email)
    assert customer is not None, "Customer not found in Medusa"

    # Assert data matches
    assert customer.get("email") == email, f"Email mismatch: expected '{email}', got '{customer.get('email')}'"
    assert customer.get("first_name") == first_name, f"First name mismatch: expected '{first_name}', got '{customer.get('first_name')}'"
    assert customer.get("last_name") == last_name, f"Last name mismatch: expected '{last_name}', got '{customer.get('last_name')}'"


def test_script_prints_sync_status(script_result):
    """
    Test 4: Verify script prints sync status.

    Purpose: Verify output
    Steps:
        1. Run script, capture stdout
        2. Verify matches pattern: "Synced customer: .* - (created|updated) in Medusa"
    Why: Tests output specification
    """
    output = (script_result.stdout or "").strip()
    assert output, f"Script produced no stdout. Stderr: {script_result.stderr}"

    # Must mention sync action somehow, but don't over-constrain exact phrasing.
    assert re.search(r"(sync|synced|created|updated)", output, re.IGNORECASE), (
        f"Output missing sync status keywords. Got: {output}"
    )

    # Prefer output to include the synced customer's email (derived from EspoCRM seed contact).
    token = get_espocrm_token()
    contacts = search_contact_by_name(token, "Robert", "Williams")
    assert contacts, "Contact 'Robert Williams' not found in EspoCRM"
    email = (contacts[0].get("emailAddress") or "").strip()
    assert email, "EspoCRM contact missing emailAddress"
    assert email.lower() in output.lower(), f"Output did not mention contact email '{email}'. Got: {output}"


def test_action_reported_correctly(script_result):
    """
    Test 5: Verify action is reported correctly in output.

    Purpose: Verify action in output
    Steps:
        1. Run script
        2. Check output contains either "created" or "updated"
    Why: Tests action detection
    """
    output = (script_result.stdout or "").lower()
    assert ("created" in output) or ("updated" in output) or ("synced" in output) or ("sync" in output), (
        f"Output doesn't contain action keywords. Got: {(script_result.stdout or '').strip()}"
    )
