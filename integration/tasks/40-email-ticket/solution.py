#!/usr/bin/env python3

import requests
import sys
import os


def read_plane_api_key():
    """Read Plane API key from MCP config file"""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith('export PLANE_API_KEY='):
                    return line.split('=', 1)[1].strip()
    except Exception as e:
        print(f"Error reading Plane API key: {e}", file=sys.stderr)
        sys.exit(1)
    
    print("Plane API key not found in config", file=sys.stderr)
    sys.exit(1)


def fetch_latest_email():
    """Fetch the most recent email from MailHog"""
    try:
        response = requests.get("http://mailhog:8025/api/v2/messages?limit=1", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('items'):
            print("No emails found in MailHog", file=sys.stderr)
            sys.exit(1)
        
        email = data['items'][0]
        subject = email['Content']['Headers']['Subject'][0]
        body = email['Content']['Body']
        
        return subject, body
        
    except Exception as e:
        print(f"Error fetching email from MailHog: {e}", file=sys.stderr)
        sys.exit(1)


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
        
        print("TEST project not found", file=sys.stderr)
        sys.exit(1)
        
    except Exception as e:
        print(f"Error fetching project ID: {e}", file=sys.stderr)
        sys.exit(1)


def create_plane_issue(api_key, project_id, subject, body):
    """Create a Plane issue with the email subject and body"""
    url = f"http://plane-api:8000/api/v1/workspaces/test-demo/projects/{project_id}/issues/"
    
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "name": subject,
        "description_html": f"<p>{body}</p>",
        "priority": "medium"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        issue_data = response.json()
        issue_id = issue_data.get('id', 'unknown')
        
        return issue_id
        
    except Exception as e:
        print(f"Error creating Plane issue: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    # Step 1: Read Plane API credentials
    api_key = read_plane_api_key()
    
    # Step 2: Get Plane project ID
    project_id = get_plane_project_id(api_key)
    
    # Step 3: Fetch latest email from MailHog
    subject, body = fetch_latest_email()
    
    # Step 4: Create Plane issue
    issue_id = create_plane_issue(api_key, project_id, subject, body)
    
    # Step 5: Print success message
    print(f"Created ticket {issue_id} from email: {subject}")


if __name__ == "__main__":
    main()
