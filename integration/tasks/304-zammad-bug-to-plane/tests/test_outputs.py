import subprocess
import base64
import json
import time
import requests
import pytest
import re
import os
from typing import List, Dict, Optional


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/sync_bugs.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path} or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    script_path = "/app/sync_bugs.py"
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




# Helper Functions

def get_zammad_token() -> str:
    """Create a Zammad API token for authentication."""
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


def get_plane_api_key() -> str:
    """Read Plane API key from MCP config file."""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('export PLANE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    
    # Fallback to environment variable
    api_key = os.environ.get('PLANE_API_KEY')
    if api_key:
        return api_key
    
    raise Exception("Plane API key not found")


def get_ticket_tags(ticket_id: int, zammad_token: str) -> List[str]:
    """Get tags for a specific ticket."""
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    headers = {
        "Authorization": f"Token token={zammad_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f'{base_url}/api/v1/tags?object=Ticket&o_id={ticket_id}',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    tags_data = response.json()
    
    # The response is an object with 'tags' key containing list of tag names
    if isinstance(tags_data, dict) and 'tags' in tags_data:
        return tags_data['tags']
    elif isinstance(tags_data, list):
        return tags_data
    return []


def get_zammad_bug_tickets(zammad_token: str) -> List[Dict]:
    """Fetch bug tickets with state='new' and tag='bug'."""
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    headers = {
        "Authorization": f"Token token={zammad_token}",
        "Content-Type": "application/json"
    }
    
    # Get all tickets
    response = requests.get(
        f'{base_url}/api/v1/tickets',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    tickets = response.json()
    
    # Filter for state="new" and tag="bug"
    bug_tickets = []
    for ticket in tickets:
        ticket_state = ticket.get('state')
        ticket_state_id = ticket.get('state_id')
        
        # Check if state is "new" - state might be stored as ID
        # State ID 1 typically corresponds to "new"
        is_new_state = (ticket_state == "new") or (ticket_state_id == 1)
        
        if not is_new_state:
            continue
        
        # Fetch tags for this ticket
        ticket_id = ticket.get('id')
        tags = get_ticket_tags(ticket_id, zammad_token)
        
        if 'bug' in tags:
            bug_tickets.append(ticket)
    
    return bug_tickets


def get_plane_project_uuid(api_key: str, workspace_slug: str, project_identifier: str) -> Optional[str]:
    """Get Plane project UUID from workspace and project identifier."""
    base_url = os.environ.get('PLANE_API_HOST_URL', 'http://plane-api:8000')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    response = requests.get(
        f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    projects = response.json()
    
    # Find project with matching identifier
    for project in projects.get('results', projects):
        if project.get('identifier') == project_identifier:
            return project.get('id')
    
    return None


def get_plane_labels(api_key: str, workspace_slug: str, project_uuid: str) -> Dict[str, Dict]:
    """Fetch all labels from Plane project and return as dict keyed by label ID."""
    base_url = os.environ.get('PLANE_API_HOST_URL', 'http://plane-api:8000')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    response = requests.get(
        f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_uuid}/labels/',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    labels_data = response.json()
    
    # Handle both paginated and non-paginated responses
    labels_list = labels_data.get('results', labels_data) if isinstance(labels_data, dict) else labels_data
    
    # Return as dict keyed by ID for easy lookup
    return {label['id']: label for label in labels_list}


def get_plane_issues(api_key: str, workspace_slug: str, project_uuid: str) -> List[Dict]:
    """Fetch issues from Plane project."""
    base_url = os.environ.get('PLANE_API_HOST_URL', 'http://plane-api:8000')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    response = requests.get(
        f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_uuid}/issues/',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    issues_data = response.json()
    
    # Handle both paginated and non-paginated responses
    if isinstance(issues_data, dict) and 'results' in issues_data:
        return issues_data['results']
    return issues_data


def get_ticket_articles(ticket_id: int, zammad_token: str) -> List[Dict]:
    """Get articles (messages) for a ticket."""
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    headers = {
        "Authorization": f"Token token={zammad_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f'{base_url}/api/v1/ticket_articles/by_ticket/{ticket_id}',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    return response.json()


# Test Functions

def test_zammad_bug_tickets_exist():
    """
    Test 1: Verify prerequisite bug tickets exist.
    
    Steps:
    1. Authenticate with Zammad API
    2. Search for tickets with state="new" and tag="bug"
    3. Assert at least 2 tickets found
    4. Verify tickets have required fields (title, articles)
    """
    # Authenticate with Zammad
    zammad_token = get_zammad_token()
    assert zammad_token, "Failed to authenticate with Zammad"
    
    # Get bug tickets
    bug_tickets = get_zammad_bug_tickets(zammad_token)
    
    # Assert at least 2 bug tickets exist
    assert len(bug_tickets) >= 2, f"Expected at least 2 bug tickets, found {len(bug_tickets)}"
    
    # Verify each ticket has required fields
    for ticket in bug_tickets:
        assert ticket.get('id'), "Ticket missing id"
        assert ticket.get('title'), "Ticket missing title"
        assert ticket.get('number'), "Ticket missing number"
        
        # Check state is "new" (either as string or state_id=1)
        ticket_state = ticket.get('state')
        ticket_state_id = ticket.get('state_id')
        is_new = (ticket_state == 'new') or (ticket_state_id == 1)
        assert is_new, f"Ticket state is not 'new': state={ticket_state}, state_id={ticket_state_id}"
        
        # Verify we can fetch articles
        articles = get_ticket_articles(ticket['id'], zammad_token)
        assert len(articles) > 0, f"Ticket {ticket['number']} has no articles"


def test_plane_issues_created():
    """
    Test 2: Verify Plane issues were created for bugs.
    
    Steps:
    1. Authenticate with Plane API
    2. Fetch Plane project UUID for "TEST"
    3. GET issues from project
    4. Search for issues with label "type:Bug"
    5. Assert at least 2 bug issues exist
    """
    # Authenticate with Plane
    plane_api_key = get_plane_api_key()
    assert plane_api_key, "Failed to get Plane API key"
    
    # Get project UUID
    workspace_slug = 'test-demo'
    project_identifier = 'TEST'
    project_uuid = get_plane_project_uuid(plane_api_key, workspace_slug, project_identifier)
    assert project_uuid, f"Could not find project '{project_identifier}' in workspace '{workspace_slug}'"
    
    # Get all labels for lookup
    labels_dict = get_plane_labels(plane_api_key, workspace_slug, project_uuid)
    
    # Get all issues from the project
    issues = get_plane_issues(plane_api_key, workspace_slug, project_uuid)
    assert issues is not None, "Failed to fetch issues from Plane"
    
    # Filter for issues with "type:Bug" label
    bug_issues = []
    for issue in issues:
        label_ids = issue.get('label_ids', []) or issue.get('labels', [])
        
        # Check if any label is "type:Bug"
        for label_id in label_ids:
            # If it's a dict, check the name directly
            if isinstance(label_id, dict):
                if label_id.get('name') == 'type:Bug':
                    bug_issues.append(issue)
                    break
            # If it's a string ID, look it up
            elif isinstance(label_id, str) and label_id in labels_dict:
                if labels_dict[label_id].get('name') == 'type:Bug':
                    bug_issues.append(issue)
                    break
    
    # Assert at least 2 bug issues exist
    assert len(bug_issues) >= 2, f"Expected at least 2 bug issues in Plane, found {len(bug_issues)}"


def test_issue_titles_match_tickets():
    """
    Test 3: Verify issue names match ticket titles.
    
    Steps:
    1. Fetch Zammad bug tickets
    2. Get first bug ticket title
    3. Search Plane issues for matching name
    4. Assert Plane issue exists with same title
    """
    # Get Zammad bug tickets
    zammad_token = get_zammad_token()
    bug_tickets = get_zammad_bug_tickets(zammad_token)
    assert len(bug_tickets) > 0, "No bug tickets found in Zammad"
    
    # Get first bug ticket title
    first_ticket = bug_tickets[0]
    ticket_title = first_ticket.get('title')
    assert ticket_title, "First ticket has no title"
    
    # Get Plane issues
    plane_api_key = get_plane_api_key()
    workspace_slug = 'test-demo'
    project_identifier = 'TEST'
    project_uuid = get_plane_project_uuid(plane_api_key, workspace_slug, project_identifier)
    issues = get_plane_issues(plane_api_key, workspace_slug, project_uuid)
    
    # Search for matching issue name
    matching_issue = None
    for issue in issues:
        if issue.get('name') == ticket_title:
            matching_issue = issue
            break
    
    assert matching_issue is not None, f"No Plane issue found with title matching '{ticket_title}'"


def test_bug_label_applied():
    """
    Test 4: Verify correct label is set.
    
    Steps:
    1. Fetch created Plane issues
    2. For each issue created from Zammad bug
    3. Assert issue has label with name="type:Bug"
    4. Verify label format is correct
    """
    # Get Plane issues
    plane_api_key = get_plane_api_key()
    workspace_slug = 'test-demo'
    project_identifier = 'TEST'
    project_uuid = get_plane_project_uuid(plane_api_key, workspace_slug, project_identifier)
    
    # Get all labels for lookup
    labels_dict = get_plane_labels(plane_api_key, workspace_slug, project_uuid)
    
    issues = get_plane_issues(plane_api_key, workspace_slug, project_uuid)
    
    # Get Zammad bug tickets to know how many we expect
    zammad_token = get_zammad_token()
    bug_tickets = get_zammad_bug_tickets(zammad_token)
    bug_ticket_titles = [ticket.get('title') for ticket in bug_tickets]
    
    # Find issues that match bug ticket titles
    synced_issues = []
    for issue in issues:
        if issue.get('name') in bug_ticket_titles:
            synced_issues.append(issue)
    
    assert len(synced_issues) > 0, "No synced issues found"
    
    # Verify each synced issue has the "type:Bug" label
    issues_with_bug_label = 0
    for issue in synced_issues:
        label_ids = issue.get('label_ids', []) or issue.get('labels', [])
        has_bug_label = False
        
        for label_id in label_ids:
            # If it's a dict, check the name directly
            if isinstance(label_id, dict):
                label_name = label_id.get('name')
                if label_name == 'type:Bug':
                    has_bug_label = True
                    # Verify label format
                    assert 'id' in label_id or 'name' in label_id, "Label missing required fields"
                    break
            # If it's a string ID, look it up
            elif isinstance(label_id, str) and label_id in labels_dict:
                if labels_dict[label_id].get('name') == 'type:Bug':
                    has_bug_label = True
                    break
        
        if has_bug_label:
            issues_with_bug_label += 1
    
    assert issues_with_bug_label > 0, "No issues found with 'type:Bug' label"


def test_summary_report_accurate():
    """
    Test 5: Verify summary report exists and is accurate.
    
    Steps:
    1. Check file exists at `/app/bug_sync_report.txt`
    2. Read content
    3. Parse "Zammad bugs found:" count
    4. Parse "Plane issues created:" count
    5. Verify counts match actual tickets and issues
    """
    report_path = '/app/bug_sync_report.txt'
    
    # Check file exists
    assert os.path.exists(report_path), f"Report file not found at {report_path}"
    
    # Read content
    with open(report_path, 'r') as f:
        content = f.read()
    
    assert content, "Report file is empty"
    
    # Parse counts using regex
    bugs_found_match = re.search(r'Zammad bugs found:\s*(\d+)', content)
    assert bugs_found_match, "Could not find 'Zammad bugs found:' count in report"
    bugs_found = int(bugs_found_match.group(1))
    
    issues_created_match = re.search(r'Plane issues created:\s*(\d+)', content)
    assert issues_created_match, "Could not find 'Plane issues created:' count in report"
    issues_created = int(issues_created_match.group(1))
    
    # Fetch actual bug tickets from Zammad
    zammad_token = get_zammad_token()
    actual_bug_tickets = get_zammad_bug_tickets(zammad_token)
    actual_bugs_count = len(actual_bug_tickets)
    
    # Verify counts match
    assert bugs_found == actual_bugs_count, \
        f"Report shows {bugs_found} bugs found, but actual count is {actual_bugs_count}"
    
    assert issues_created <= bugs_found, \
        f"More issues created ({issues_created}) than bugs found ({bugs_found})"
    
    assert issues_created >= 2, \
        f"Expected at least 2 issues created, report shows {issues_created}"
    
    # Verify report contains synced tickets section
    assert 'Synced tickets:' in content, "Report missing 'Synced tickets:' section"
    
    # Verify report format contains ticket entries
    ticket_entries = re.findall(r'- Ticket #\d+:', content)
    assert len(ticket_entries) == issues_created, \
        f"Report has {len(ticket_entries)} ticket entries, expected {issues_created}"
