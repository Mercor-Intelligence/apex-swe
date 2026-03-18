import json
import os
import re
import subprocess
import requests
import pytest
from requests.auth import HTTPBasicAuth


# Helper function to get API authentication
def get_api_auth():
    """Get authentication credentials for Zammad API"""
    username = os.environ.get('ZAMMAD_USERNAME')
    password = os.environ.get('ZAMMAD_PASSWORD')

    if not username or not password:
        pytest.skip("ZAMMAD_USERNAME or ZAMMAD_PASSWORD not set in environment")

    return HTTPBasicAuth(username, password)


# Helper function to fetch ticket from API
def fetch_ticket_from_api(ticket_id):
    """Fetch ticket directly from Zammad API"""
    url = f'http://zammad:8080/api/v1/tickets/{ticket_id}'
    auth = get_api_auth()
    response = requests.get(url, auth=auth)
    return response


def test_zammad_api_accessible():
    """
    Test 1: Verify Zammad API is running
    Purpose: Validates environment setup
    """
    url = 'http://zammad:8080/api/v1/tickets'

    try:
        response = requests.get(url, timeout=5)
        # API should respond with 200 (authenticated), 401 (needs auth), or 403 (forbidden - needs auth)
        assert response.status_code in [200, 401, 403], \
            f"Zammad API not accessible. Status code: {response.status_code}"
    except requests.exceptions.RequestException as e:
        pytest.fail(f"Cannot reach Zammad API: {e}")


def test_ticket_5_exists():
    """
    Test 2: Verify prerequisite ticket exists
    Purpose: Confirms test data setup
    """
    response = fetch_ticket_from_api(5)

    assert response.status_code == 200, \
        f"Ticket 5 not found. Status code: {response.status_code}"

    ticket_data = response.json()
    assert ticket_data is not None, "Response contains no ticket data"
    assert 'title' in ticket_data, "Ticket data missing 'title' field"


def test_script_executes_successfully():
    """
    Test 3: Verify script runs without errors
    Purpose: Tests basic execution
    """
    result = subprocess.run(
        ['python', '/app/solution.py'],
        capture_output=True,
        text=True,
        timeout=10
    )

    assert result.returncode == 0, \
        f"Script failed with return code {result.returncode}. Error: {result.stderr}"


def test_output_format_correct():
    """
    Test 4: Verify output matches specification
    Purpose: Tests output formatting
    """
    result = subprocess.run(
        ['python', '/app/solution.py'],
        capture_output=True,
        text=True,
        timeout=10
    )

    output = result.stdout.strip()

    # Check output matches pattern: "Title: .+, State: .+"
    pattern = r'^Title: .+, State: .+$'
    assert re.match(pattern, output), \
        f"Output format incorrect. Expected 'Title: <title>, State: <state>', got: '{output}'"

    # Verify comma and space between fields
    assert ', State: ' in output, \
        "Output missing ', State: ' separator"


def test_title_matches_ticket():
    """
    Test 5: Verify correct title is printed
    Purpose: Validates title extraction
    """
    # Fetch expected title from API
    response = fetch_ticket_from_api(5)
    assert response.status_code == 200, "Failed to fetch ticket from API"

    ticket_data = response.json()
    expected_title = ticket_data.get('title', '')

    # Run script and capture output
    result = subprocess.run(
        ['python', '/app/solution.py'],
        capture_output=True,
        text=True,
        timeout=10
    )

    output = result.stdout.strip()

    # Extract title from output using regex
    match = re.match(r'^Title: (.+), State: .+$', output)
    assert match, f"Could not parse title from output: '{output}'"

    actual_title = match.group(1)
    assert actual_title == expected_title, \
        f"Title mismatch. Expected: '{expected_title}', Got: '{actual_title}'"


def test_state_matches_ticket():
    """
    Test 6: Verify correct state is printed
    Purpose: Validates state extraction
    """
    # Fetch expected state from API
    response = fetch_ticket_from_api(5)
    assert response.status_code == 200, "Failed to fetch ticket from API"

    ticket_data = response.json()

    # Zammad returns state_id, map it to state name
    state_id = ticket_data.get('state_id')
    state_map = {
        1: 'new',
        2: 'open',
        3: 'pending reminder',
        4: 'closed',
        5: 'merged'
    }
    expected_state = state_map.get(state_id, '')

    # Run script and capture output
    result = subprocess.run(
        ['python', '/app/solution.py'],
        capture_output=True,
        text=True,
        timeout=10
    )

    output = result.stdout.strip()

    # Extract state from output using regex
    match = re.match(r'^Title: .+, State: (.+)$', output)
    assert match, f"Could not parse state from output: '{output}'"

    actual_state = match.group(1)
    assert actual_state == expected_state, \
        f"State mismatch. Expected: '{expected_state}', Got: '{actual_state}'"


def test_uses_environment_credentials():
    """
    Test 7: Verify script uses env variables for auth
    Purpose: Tests proper authentication setup
    """
    # Check that ZAMMAD_USERNAME is set
    username = os.environ.get('ZAMMAD_USERNAME')
    assert username is not None, \
        "ZAMMAD_USERNAME environment variable not set"
    assert username.strip() != '', \
        "ZAMMAD_USERNAME environment variable is empty"

    # Check that ZAMMAD_PASSWORD is set
    password = os.environ.get('ZAMMAD_PASSWORD')
    assert password is not None, \
        "ZAMMAD_PASSWORD environment variable not set"
    assert password.strip() != '', \
        "ZAMMAD_PASSWORD environment variable is empty"
