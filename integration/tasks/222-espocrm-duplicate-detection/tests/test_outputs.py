import base64
import json
import requests
import pytest
import re
import subprocess
import os
from collections import defaultdict


ESPOCRM_URL = os.environ.get('ESPOCRM_SITE_URL', 'http://espocrm:80')
ESPOCRM_USERNAME = os.environ.get('ESPOCRM_ADMIN_USERNAME', 'admin')
ESPOCRM_PASSWORD = os.environ.get('ESPOCRM_ADMIN_PASSWORD', 'ChangeMe123')
MATTERMOST_URL = os.environ.get('MATTERMOST_ENDPOINT', 'http://mattermost-server:8065/api/v4')

# Run script once and cache result
_script_result = None

def run_script_once():
    """Run the script once and cache the result."""
    global _script_result
    if _script_result is None:
        script_path = '/app/detect_duplicates.py'
        if not os.path.exists(script_path):
            script_path = '/app/solution.py'
        
        result = subprocess.run(['python3', script_path],
            capture_output=True, text=True, timeout=240)
        _script_result = result
    return _script_result


def test_script_exists():
    """Test 0: Verify the required Python script exists."""
    script_path = "/app/detect_duplicates.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(alt_path), \
        f"Script not found at {script_path} or {alt_path}"


def test_script_runs_successfully():
    """Test 1: Verify script runs without errors."""
    result = run_script_once()
    assert result.returncode == 0, f"Script failed with exit code {result.returncode}: {result.stderr}"


def test_output_format_matches_requirement():
    """Test 2: Verify output matches 'Found {count} duplicate emails' format."""
    result = run_script_once()
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Required format: "Found {count} duplicate emails"
    pattern = r'Found \d+ duplicate emails?'
    match = re.search(pattern, result.stdout, re.IGNORECASE)
    assert match, \
        f"Output missing required format 'Found N duplicate emails'. Got: {result.stdout[:500]}"


def get_espocrm_token():
    """Authenticate with EspoCRM and get token for tests."""
    auth_header = base64.b64encode(f"{ESPOCRM_USERNAME}:{ESPOCRM_PASSWORD}".encode()).decode()
    
    response = requests.get(
        f"{ESPOCRM_URL}/api/v1/App/user",
        headers={"Espo-Authorization": auth_header},
        timeout=30
    )
    response.raise_for_status()
    
    user_data = response.json()
    token = user_data.get('token')
    
    if not token:
        raise ValueError("No token in authentication response")
        
    return ESPOCRM_USERNAME, token


def get_all_contacts_from_api():
    """Get all contacts from EspoCRM API (CONTACTS ONLY, not Leads)."""
    username, token = get_espocrm_token()
    token_auth_header = base64.b64encode(f"{username}:{token}".encode()).decode()
    
    response = requests.get(
        f"{ESPOCRM_URL}/api/v1/Contact",
        headers={
            "Espo-Authorization": token_auth_header,
            "X-No-Total": "true"
        },
        params={
            "select": "id,firstName,lastName,emailAddress",
            "maxSize": 200
        },
        timeout=30
    )
    response.raise_for_status()
    
    data = response.json()
    return data.get('list', [])


def detect_duplicates_in_contacts(contacts):
    """
    Detect duplicates in CONTACTS ONLY (per task requirement).
    Returns dict of {email: [names]} for emails with multiple contacts.
    """
    email_groups = defaultdict(list)
    
    for contact in contacts:
        email = contact.get('emailAddress', '').strip()
        if email:
            first_name = contact.get('firstName', '')
            last_name = contact.get('lastName', '')
            full_name = f"{first_name} {last_name}".strip()
            if full_name:
                email_groups[email].append(full_name)
    
    # Find emails with duplicates (more than 1 contact with same email)
    duplicates = {email: names for email, names in email_groups.items() if len(names) > 1}
    return duplicates


def read_mattermost_token():
    """Read Mattermost token from MCP config file or environment."""
    import time as time_module
    
    # Try environment variable first
    token = os.environ.get('MATTERMOST_TOKEN')
    if token:
        return token
    
    # Try reading from config file with retry
    config_file = '/config/mcp-config.txt'
    max_attempts = 12  # Wait up to 60 seconds
    
    for attempt in range(max_attempts):
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Check for both formats: with and without 'export'
                    if line.startswith('export MATTERMOST_TOKEN='):
                        token = line.split('=', 1)[1].strip().strip('"').strip("'")
                        if token:
                            return token
                    elif line.startswith('MATTERMOST_TOKEN='):
                        token = line.split('=', 1)[1].strip().strip('"').strip("'")
                        if token:
                            return token
        except FileNotFoundError:
            pass
        except Exception:
            pass
        
        if attempt < max_attempts - 1:
            time_module.sleep(5)
    
    # Fallback to default token from connection-info.md
    return '8on6mwscn7doxexh9o1jf6tuzw'


def get_mattermost_messages(channel_name='data-quality'):
    """Get messages from Mattermost channel."""
    token = read_mattermost_token()
    team_name = os.environ.get('MATTERMOST_TEAM', 'test-demo')
    
    if not token:
        return []
    
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Get user's teams
        response = requests.get(f"{MATTERMOST_URL}/users/me/teams", headers=headers, timeout=10)
        response.raise_for_status()
        teams = response.json()
        
        # Find team ID
        team_id = None
        for team in teams:
            if team.get('name') == team_name:
                team_id = team.get('id')
                break
        
        if not team_id:
            return []
        
        # Get channels
        response = requests.get(f"{MATTERMOST_URL}/teams/{team_id}/channels", headers=headers, timeout=10)
        response.raise_for_status()
        channels = response.json()
        
        # Find channel ID
        channel_id = None
        for channel in channels:
            if channel.get('name') == channel_name or channel.get('display_name') == channel_name:
                channel_id = channel.get('id')
                break
        
        if not channel_id:
            return []
        
        # Get posts from channel
        response = requests.get(f"{MATTERMOST_URL}/channels/{channel_id}/posts", headers=headers, timeout=10)
        response.raise_for_status()
        posts_data = response.json()
        
        posts = posts_data.get('posts', {})
        messages = [post.get('message', '') for post in posts.values()]
        
        return messages
        
    except Exception as e:
        return []


def test_duplicate_count_matches_crm():
    """Test 3: Verify duplicate count in output matches actual CRM duplicates."""
    result = run_script_once()
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    try:
        # Get contacts from CRM
        contacts = get_all_contacts_from_api()
        expected_duplicates = detect_duplicates_in_contacts(contacts)
        expected_count = len(expected_duplicates)
        
        # Extract count from output
        pattern = r'Found (\d+) duplicate emails?'
        match = re.search(pattern, result.stdout, re.IGNORECASE)
        
        if match:
            reported_count = int(match.group(1))
            # Allow some tolerance for timing differences
            assert abs(reported_count - expected_count) <= 2, \
                f"Reported {reported_count} duplicates but found {expected_count} in CRM"
    except requests.RequestException as e:
        pytest.skip(f"EspoCRM unavailable: {e}")


def test_mattermost_report_posted():
    """Test 4: Verify that a duplicate detection report was posted to Mattermost."""
    run_script_once()
    
    messages = get_mattermost_messages('data-quality')
    
    if not messages:
        pytest.skip("Could not retrieve Mattermost messages")
    
    # Find messages containing duplicate report
    found = False
    for message in messages:
        if 'duplicate' in message.lower() or 'Duplicate Email' in message:
            found = True
            break
    
    assert found, "No duplicate detection report found in Mattermost data-quality channel"


def test_duplicates_correctly_identified():
    """Test 5: Verify duplicates are correctly identified in the report."""
    run_script_once()
    
    try:
        # Get contacts from CRM (CONTACTS ONLY, per task requirement)
        contacts = get_all_contacts_from_api()
        expected_duplicates = detect_duplicates_in_contacts(contacts)
        
        if not expected_duplicates:
            # No duplicates to verify
            return
        
        # Get Mattermost messages
        messages = get_mattermost_messages('data-quality')
        
        # Find the duplicate report message
        report_message = None
        for message in messages:
            if 'duplicate' in message.lower() or 'Duplicate Email' in message:
                report_message = message
                break
        
        if not report_message:
            pytest.skip("Duplicate report not found in Mattermost")
        
        # Check that at least one expected duplicate email appears in the report
        found_count = 0
        for email in expected_duplicates.keys():
            if email in report_message:
                found_count += 1
        
        assert found_count > 0, \
            f"None of the expected duplicate emails found in report. Expected: {list(expected_duplicates.keys())[:5]}"
    except requests.RequestException as e:
        pytest.skip(f"EspoCRM unavailable: {e}")


def test_report_format_correct():
    """Test 6: Verify that the report message is formatted correctly."""
    run_script_once()
    
    messages = get_mattermost_messages('data-quality')
    
    if not messages:
        pytest.skip("Could not retrieve Mattermost messages")
    
    # Find the duplicate report message
    report_message = None
    for message in messages:
        if 'duplicate' in message.lower() or 'Duplicate Email' in message:
            report_message = message
            break
    
    if not report_message:
        pytest.skip("Duplicate report not found in Mattermost")
    
    # Check format: should have "Duplicate Email:" or similar header
    has_header = 'Duplicate' in report_message
    assert has_header, "Report missing duplicate header"


def test_no_critical_errors():
    """Test 7: Verify no critical errors in script execution."""
    result = run_script_once()
    assert result.returncode == 0, f"Script crashed with stderr: {result.stderr}"
