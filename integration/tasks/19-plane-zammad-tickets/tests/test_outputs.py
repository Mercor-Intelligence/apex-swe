import base64
import json
import time
import requests
import pytest
import re
import os
import subprocess


SCRIPT_PATH = "/app/sync_issue.py"
ALT_SCRIPT_PATH = "/app/solution.py"


def _get_script_path() -> str:
    return SCRIPT_PATH if os.path.exists(SCRIPT_PATH) else ALT_SCRIPT_PATH


@pytest.fixture(scope="module", autouse=True)
def _run_solution_once():
    """Run the user's script once so the downstream integration assertions are meaningful."""
    script_path = _get_script_path()
    assert os.path.exists(script_path), f"Required script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"

    result = subprocess.run(
        ["python3", script_path],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"
    return result


def test_script_exists():
    """Test that the required Python script exists."""
    assert os.path.exists(SCRIPT_PATH) or os.path.exists(ALT_SCRIPT_PATH), \
        f"Required script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"


def read_plane_api_key():
    """Read Plane API key from MCP config file"""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('export PLANE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        pytest.fail(f"Error reading Plane API key: {e}")

    pytest.fail("Plane API key not found in config")


def get_plane_project_id(api_key):
    """Get the Plane project UUID for TEST project"""
    url = "http://plane-api:8000/api/v1/workspaces/test-demo/projects/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    projects = response.json()
    for project in projects.get('results', []):
        if project.get('identifier') == 'TEST':
            return project.get('id')

    pytest.fail("TEST project not found")


def create_zammad_token():
    """Create a Zammad API token"""
    zammad_username = os.environ.get('ZAMMAD_USERNAME', 'admin@example.com')
    zammad_password = os.environ.get('ZAMMAD_PASSWORD', 'StrongPassw0rd@()')
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')

    url = f"{base_url}/api/v1/user_access_token"
    response = requests.post(
        url,
        auth=(zammad_username, zammad_password),
        headers={"Content-Type": "application/json"},
        json={
            "name": "test-token",
            "permission": ["ticket.agent"]
        },
        timeout=10
    )
    response.raise_for_status()

    token_data = response.json()
    return token_data.get('token')


def test_plane_issue_exists():
    """Test 1: Verify prerequisite issue exists in test-demo workspace"""
    # Step 1: Read Plane API key
    api_key = read_plane_api_key()
    assert api_key, "Plane API key should be available"

    # Step 2: Verify using test-demo workspace (as specified in requirements)
    workspace_slug = "test-demo"

    # Step 3: Get project UUID
    project_id = get_plane_project_id(api_key)
    assert project_id, "Project TEST should exist"

    # Step 4: Query Plane API for issues in test-demo workspace
    url = f"http://plane-api:8000/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json()

    # Step 5: Search for issue with title "Fix memory leak in user session management"
    target_title = "Fix memory leak in user session management"
    found_issue = None
    for issue in issues.get('results', []):
        if issue.get('name') == target_title:
            found_issue = issue
            break

    # Step 6: Assert issue exists and has title and description
    assert found_issue is not None, f"Issue with title '{target_title}' should exist in {workspace_slug} workspace"
    assert found_issue.get('name') == target_title
    assert 'description' in found_issue or 'description_html' in found_issue


def test_zammad_ticket_created():
    """Test 2: Verify ticket was created"""
    # Step 1: Create Zammad token
    token = create_zammad_token()

    # Step 2: Query Zammad for recent tickets
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    url = f"{base_url}/api/v1/tickets"
    headers = {"Authorization": f"Token token={token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    tickets = response.json()

    # Step 3: Search for ticket with title "Fix memory leak in user session management"
    target_title = "Fix memory leak in user session management"
    found_ticket = None
    for ticket in tickets:
        if ticket.get('title') == target_title:
            found_ticket = ticket
            break

    assert found_ticket is not None, f"Zammad ticket with title '{target_title}' should exist"


def test_ticket_title_matches():
    """Test 3: Verify title transferred correctly"""
    # Step 1: Get Plane issue title
    api_key = read_plane_api_key()
    project_id = get_plane_project_id(api_key)

    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json()
    target_title = "Fix memory leak in user session management"
    plane_issue = None
    for issue in issues.get('results', []):
        if issue.get('name') == target_title:
            plane_issue = issue
            break

    assert plane_issue is not None, "Plane issue should exist"
    plane_title = plane_issue.get('name')

    # Step 2: Get created Zammad ticket
    token = create_zammad_token()
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    url = f"{base_url}/api/v1/tickets"
    headers = {"Authorization": f"Token token={token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    tickets = response.json()
    zammad_ticket = None
    for ticket in tickets:
        if ticket.get('title') == target_title:
            zammad_ticket = ticket
            break

    assert zammad_ticket is not None, "Zammad ticket should exist"
    zammad_title = zammad_ticket.get('title')

    # Step 3: Assert titles match
    assert plane_title == zammad_title == target_title, \
        f"Titles should match: Plane='{plane_title}', Zammad='{zammad_title}'"


def test_ticket_has_correct_customer():
    """Test 4: Verify customer assignment"""
    # Step 1: Get created Zammad ticket
    token = create_zammad_token()
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')

    # Find the ticket
    url = f"{base_url}/api/v1/tickets"
    headers = {"Authorization": f"Token token={token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    tickets = response.json()
    target_title = "Fix memory leak in user session management"
    ticket = None
    for t in tickets:
        if t.get('title') == target_title:
            ticket = t
            break

    assert ticket is not None, "Ticket should exist"
    ticket_id = ticket.get('id')

    # Get full ticket details
    url = f"{base_url}/api/v1/tickets/{ticket_id}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    ticket_details = response.json()

    # Step 2: Extract customer_id from ticket
    customer_id = ticket_details.get('customer_id')
    assert customer_id is not None, "Ticket should have a customer_id"

    # Step 3: Verify customer ID corresponds to admin@example.com (the default admin user)
    url = f"{base_url}/api/v1/users/{customer_id}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    user = response.json()

    customer_email = user.get('email', '').lower()
    assert customer_email == 'admin@example.com', \
        f"Customer email should be admin@example.com, got '{customer_email}'"


def test_ticket_in_users_group():
    """Test 5: Verify group assignment"""
    # Step 1: Get created Zammad ticket
    token = create_zammad_token()
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')

    # Find the ticket
    url = f"{base_url}/api/v1/tickets"
    headers = {"Authorization": f"Token token={token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    tickets = response.json()
    target_title = "Fix memory leak in user session management"
    ticket = None
    for t in tickets:
        if t.get('title') == target_title:
            ticket = t
            break

    assert ticket is not None, "Ticket should exist"
    ticket_id = ticket.get('id')

    # Get full ticket details
    url = f"{base_url}/api/v1/tickets/{ticket_id}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    ticket_details = response.json()

    # Step 2: Extract group_id from ticket
    group_id = ticket_details.get('group_id')
    assert group_id is not None, "Ticket should have a group_id"

    # Step 3: Verify group ID corresponds to "Users" group
    url = f"{base_url}/api/v1/groups/{group_id}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    group = response.json()

    group_name = group.get('name')
    assert group_name == "Users", f"Group should be 'Users', got '{group_name}'"


def test_ticket_has_article():
    """Test 6: Verify article/body was created with correct description"""
    # Step 1: Get Plane issue description
    api_key = read_plane_api_key()
    project_id = get_plane_project_id(api_key)

    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    headers = {"X-API-Key": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    issues = response.json()
    target_title = "Fix memory leak in user session management"
    plane_issue = None
    for issue in issues.get('results', []):
        if issue.get('name') == target_title:
            plane_issue = issue
            break

    assert plane_issue is not None, "Plane issue should exist"
    plane_description = plane_issue.get('description_html', '') or plane_issue.get('description', '')

    # Step 2: Get created Zammad ticket ID
    token = create_zammad_token()
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')

    url = f"{base_url}/api/v1/tickets"
    headers = {"Authorization": f"Token token={token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    tickets = response.json()
    ticket = None
    for t in tickets:
        if t.get('title') == target_title:
            ticket = t
            break

    assert ticket is not None, "Ticket should exist"
    ticket_id = ticket.get('id')

    # Step 3: Fetch ticket articles
    url = f"{base_url}/api/v1/ticket_articles/by_ticket/{ticket_id}"
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    articles = response.json()

    # Step 4: Assert at least one article exists
    assert len(articles) > 0, "Ticket should have at least one article"

    # Step 5: Verify article body matches Plane issue description
    article = articles[0]
    article_body = article.get('body', '')

    # Handle case where description might be empty
    if plane_description:
        assert article_body == plane_description, \
            f"Article body should match Plane description. Expected: '{plane_description[:100]}...', Got: '{article_body[:100]}...'"
    else:
        # If Plane description is empty, Zammad article should say "No description"
        assert article_body == "No description", \
            f"Article body should be 'No description' when Plane issue has no description, got '{article_body}'"
