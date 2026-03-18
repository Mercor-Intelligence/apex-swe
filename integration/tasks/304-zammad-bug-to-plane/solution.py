#!/usr/bin/env python3
"""
Sync bug tickets from Zammad to Plane with type:Bug label.
"""
import os
import sys
import requests
from typing import List, Dict, Optional


def read_plane_api_key():
    """Read Plane API key from MCP config file."""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('export PLANE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        print(f"Error reading Plane API key: {e}", file=sys.stderr)
        # Fallback to environment variable
        api_key = os.environ.get('PLANE_API_KEY')
        if api_key:
            return api_key
        sys.exit(1)
    
    print("Plane API key not found in config", file=sys.stderr)
    sys.exit(1)


def create_zammad_token():
    """Create a Zammad API token for authentication."""
    zammad_username = os.environ.get('ZAMMAD_USERNAME', 'admin@example.com')
    zammad_password = os.environ.get('ZAMMAD_PASSWORD', 'StrongPassw0rd@()')
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    try:
        url = f"{base_url}/api/v1/user_access_token"
        response = requests.post(
            url,
            auth=(zammad_username, zammad_password),
            headers={"Content-Type": "application/json"},
            json={
                "name": "bug-sync-token",
                "permission": ["ticket.agent"]
            },
            timeout=10
        )
        response.raise_for_status()
        
        token_data = response.json()
        return token_data.get('token')
        
    except Exception as e:
        print(f"Error creating Zammad token: {e}", file=sys.stderr)
        sys.exit(1)


def get_ticket_tags(ticket_id: int, zammad_token: str) -> List[str]:
    """Get tags for a specific ticket."""
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    headers = {
        "Authorization": f"Token token={zammad_token}",
        "Content-Type": "application/json"
    }
    
    try:
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
    except Exception as e:
        print(f"Warning: Could not fetch tags for ticket {ticket_id}: {e}")
        return []


def get_zammad_bug_tickets(zammad_token: str) -> List[Dict]:
    """Search Zammad for tickets with state='new' and tag='bug'."""
    base_url = os.environ.get('ZAMMAD_BASE_URL', 'http://zammad:8080')
    
    headers = {
        "Authorization": f"Token token={zammad_token}",
        "Content-Type": "application/json"
    }
    
    # Get all tickets
    print(f"Fetching tickets from Zammad...")
    response = requests.get(
        f'{base_url}/api/v1/tickets',
        headers=headers,
        timeout=30
    )
    response.raise_for_status()
    tickets = response.json()
    
    print(f"Received {len(tickets)} total tickets from Zammad")
    
    # Filter for state="new" and tag="bug"
    bug_tickets = []
    for ticket in tickets:
        ticket_id = ticket.get('id')
        ticket_number = ticket.get('number')
        ticket_title = ticket.get('title')
        ticket_state = ticket.get('state')
        ticket_state_id = ticket.get('state_id')
        
        print(f"  Ticket #{ticket_number} '{ticket_title}': state='{ticket_state}' (state_id={ticket_state_id})")
        
        # Check if state is "new" - state might be stored as ID
        # State ID 1 typically corresponds to "new"
        is_new_state = (ticket_state == "new") or (ticket_state_id == 1)
        
        if not is_new_state:
            print(f"    ✗ Skipping: state not 'new'")
            continue
        
        # Fetch tags for this ticket
        tags = get_ticket_tags(ticket_id, zammad_token)
        
        print(f"    Tags: {tags}")
        
        if 'bug' in tags:
            print(f"    ✓ Matched bug ticket!")
            bug_tickets.append(ticket)
        else:
            print(f"    ✗ Skipping: no 'bug' tag")
    
    print(f"Found {len(bug_tickets)} bug tickets")
    return bug_tickets


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


def get_or_create_label(api_key: str, workspace_slug: str, project_uuid: str, label_name: str) -> str:
    """Get or create a label in Plane and return its ID."""
    base_url = os.environ.get('PLANE_API_HOST_URL', 'http://plane-api:8000')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    # Try to get existing labels
    try:
        response = requests.get(
            f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_uuid}/labels/',
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            labels_data = response.json()
            labels = labels_data.get('results', [])
            for label in labels:
                if label.get('name') == label_name:
                    print(f"Found existing label: {label_name}")
                    return label.get('id')
    except Exception as e:
        print(f"Warning: Could not fetch existing labels: {e}", file=sys.stderr)
    
    # Create new label
    try:
        print(f"Creating label: {label_name}")
        response = requests.post(
            f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_uuid}/labels/',
            headers=headers,
            json={'name': label_name},
            timeout=30
        )
        if response.status_code in [200, 201]:
            return response.json().get('id')
    except Exception as e:
        print(f"Warning: Could not create label: {e}", file=sys.stderr)
    
    return None


def create_plane_issue(
    api_key: str,
    workspace_slug: str,
    project_uuid: str,
    title: str,
    description: str,
    label_ids: List[str] = None
) -> Optional[str]:
    """Create an issue in Plane and return its ID."""
    base_url = os.environ.get('PLANE_API_HOST_URL', 'http://plane-api:8000')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    # Prepare issue payload
    issue_data = {
        'name': title,
        'description_html': f'<p>{description}</p>',
        'priority': 'medium'
    }
    
    # Add labels if provided
    if label_ids:
        issue_data['labels'] = label_ids
    
    response = requests.post(
        f'{base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_uuid}/issues/',
        headers=headers,
        json=issue_data,
        timeout=30
    )
    response.raise_for_status()
    
    issue = response.json()
    return issue.get('id')


def write_text_report(report_data: List[Dict], bugs_found: int, output_path: str):
    """Write sync report to text file."""
    with open(output_path, 'w') as f:
        f.write("Bug Ticket Sync Report\n")
        f.write("=====================\n")
        f.write(f"Zammad bugs found: {bugs_found}\n")
        f.write(f"Plane issues created: {len(report_data)}\n")
        f.write("\n")
        f.write("Synced tickets:\n")
        for row in report_data:
            f.write(f"- Ticket #{row['zammad_ticket_number']}: {row['title']} → Issue {row['plane_issue_id']}\n")


def main():
    """Main execution function."""
    workspace_slug = 'test-demo'
    project_identifier = 'TEST'
    output_path = '/app/bug_sync_report.txt'
    
    # Get credentials
    print("Initializing authentication...")
    plane_api_key = read_plane_api_key()
    zammad_token = create_zammad_token()
    print("Authentication successful")
    
    print("\nStep 1: Getting Plane project UUID...")
    project_uuid = get_plane_project_uuid(plane_api_key, workspace_slug, project_identifier)
    if not project_uuid:
        print(f"Error: Could not find project '{project_identifier}' in workspace '{workspace_slug}'")
        return
    print(f"Found project UUID: {project_uuid}")
    
    print("\nStep 2: Getting or creating 'type:Bug' label...")
    label_id = get_or_create_label(plane_api_key, workspace_slug, project_uuid, 'type:Bug')
    label_ids = [label_id] if label_id else []
    print(f"Label ID: {label_id}")
    
    print("\nStep 3: Fetching bug tickets from Zammad...")
    bug_tickets = get_zammad_bug_tickets(zammad_token)
    bugs_found = len(bug_tickets)
    print(f"Found {bugs_found} bug tickets")
    
    report_data = []
    
    print("\nStep 4: Syncing tickets to Plane...")
    for ticket in bug_tickets:
        ticket_id = ticket.get('id')
        ticket_number = ticket.get('number')
        title = ticket.get('title')
        
        print(f"\nProcessing ticket #{ticket_number}: {title}")
        
        # Get ticket articles for description
        try:
            articles = get_ticket_articles(ticket_id, zammad_token)
            # Use first article body as description
            description = ""
            if articles and len(articles) > 0:
                description = articles[0].get('body', '').replace('\n', ' ')[:500]  # Limit description length
        except Exception as e:
            print(f"Warning: Could not fetch articles for ticket {ticket_number}: {e}")
            description = title
        
        # Create Plane issue
        try:
            plane_issue_id = create_plane_issue(
                api_key=plane_api_key,
                workspace_slug=workspace_slug,
                project_uuid=project_uuid,
                title=title,
                description=description,
                label_ids=label_ids
            )
            
            print(f"  Created Plane issue: {plane_issue_id}")
            
            # Add to report
            report_data.append({
                'zammad_ticket_number': ticket_number,
                'title': title,
                'plane_issue_id': plane_issue_id
            })
        except Exception as e:
            print(f"  Error creating Plane issue: {e}")
    
    print(f"\nStep 5: Writing text report to {output_path}...")
    write_text_report(report_data, bugs_found, output_path)
    print(f"Report written successfully! Synced {len(report_data)} tickets.")
    
    print("\n=== Sync Complete ===")


if __name__ == "__main__":
    main()
