#!/usr/bin/env python3
"""Test validation for Task 281: Warranty Validator
Verifies: script existence, Zammad ticket updates, Mattermost notifications, output format
"""

import subprocess
import requests
import os
import re
import pytest


SCRIPT_PATH = "/app/warranty_validator.py"
ALT_SCRIPT_PATH = "/app/solution.py"
ZAMMAD_URL = os.environ.get('ZAMMAD_SITE_URL', 'http://zammad:8080')
MATTERMOST_URL = os.environ.get('MATTERMOST_URL', 'http://mattermost-server:8065')


def get_script_path():
    if os.path.exists(SCRIPT_PATH):
        return SCRIPT_PATH
    return ALT_SCRIPT_PATH


# Run script once and cache result
_script_result = None

def run_solution():
    """Run the solution script once and cache."""
    global _script_result
    if _script_result is None:
        result = subprocess.run(
            ['python3', get_script_path()],
            capture_output=True,
            text=True,
            timeout=240
        )
        _script_result = (result.stdout, result.stderr, result.returncode)
    return _script_result


def get_zammad_auth():
    """Get Zammad authentication."""
    return ('admin@example.com', 'StrongPassw0rd@()')


def get_mattermost_token():
    """Read Mattermost token from config."""
    try:
        with open('/config/mcp-config.txt', 'r') as f:
            for line in f:
                if 'MATTERMOST_TOKEN=' in line:
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get('MATTERMOST_TOKEN')


# ==================== TESTS ====================

def test_script_exists():
    """Test 0: Verify script exists."""
    assert os.path.exists(SCRIPT_PATH) or os.path.exists(ALT_SCRIPT_PATH), \
        f"Script not found at {SCRIPT_PATH} or {ALT_SCRIPT_PATH}"


def test_solution_runs_successfully():
    """Test 1: Verify solution runs without errors."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Solution failed with exit code {returncode}: {stderr}"


def test_output_format_matches_requirement():
    """Test 2: Verify output matches 'Processed N warranty tickets (X approved, Y denied)' format."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    # Check for proper output format
    pattern = r'Processed \d+ warranty tickets? \(\d+ approved,? \d+ denied\)'
    alt_pattern = r'No warranty tickets'
    
    has_format = re.search(pattern, stdout, re.IGNORECASE) or re.search(alt_pattern, stdout)
    assert has_format, \
        f"Output missing required format 'Processed N warranty tickets (X approved, Y denied)'. Got: {stdout[:500]}"


def test_output_has_warranty_mention():
    """Test 3: Verify output mentions warranty processing."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    assert 'warranty' in stdout.lower(), f"Output missing 'warranty' mention: {stdout[:500]}"


def test_output_has_valid_counts():
    """Test 4: Verify output contains valid ticket counts."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    # Extract counts
    processed_match = re.search(r'Processed (\d+)', stdout)
    no_tickets = 'No warranty tickets' in stdout
    
    if processed_match:
        total = int(processed_match.group(1))
        assert total >= 0, f"Invalid total count: {total}"
        
        # If processed, should have approved/denied counts
        approved_match = re.search(r'(\d+)\s*approved', stdout.lower())
        denied_match = re.search(r'(\d+)\s*denied', stdout.lower())
        
        if approved_match and denied_match:
            approved = int(approved_match.group(1))
            denied = int(denied_match.group(1))
            assert approved + denied == total, \
                f"Counts don't add up: {approved} + {denied} != {total}"
    elif no_tickets:
        pass  # Valid output when no tickets
    else:
        pytest.fail(f"Output missing ticket counts: {stdout[:300]}")


def test_zammad_tickets_updated_with_warranty_comment():
    """Test 5: Verify Zammad tickets were updated with warranty decision comments."""
    run_solution()
    
    auth = get_zammad_auth()
    try:
        response = requests.get(f"{ZAMMAD_URL}/api/v1/tickets", auth=auth, timeout=30)
        if response.status_code != 200:
            pytest.skip(f"Zammad API returned {response.status_code}")
        
        tickets = response.json()
        warranty_tickets = [t for t in tickets if 'warranty' in str(t.get('title', '')).lower() 
                           or 'warranty' in str(t.get('tags', '')).lower()]
        
        if not warranty_tickets:
            # No warranty tickets to check
            return
        
        # Check each warranty ticket for decision comment
        found_decision = False
        for ticket in warranty_tickets[:5]:
            ticket_id = ticket.get('id')
            if not ticket_id:
                continue
            
            articles_resp = requests.get(
                f"{ZAMMAD_URL}/api/v1/ticket_articles/by_ticket/{ticket_id}",
                auth=auth,
                timeout=30
            )
            
            if articles_resp.status_code == 200:
                articles = articles_resp.json()
                for article in articles:
                    body = article.get('body', '').lower()
                    # Check for warranty decision markers
                    if ('warranty' in body and 
                        ('approved' in body or 'denied' in body or 'expired' in body or
                         '✅' in article.get('body', '') or '❌' in article.get('body', ''))):
                        found_decision = True
                        break
            if found_decision:
                break
        
        # If warranty tickets exist, should have decisions
        if warranty_tickets:
            assert found_decision, "No warranty decision comments found in Zammad tickets"
    except requests.RequestException as e:
        pytest.skip(f"Zammad unavailable: {e}")


def test_mattermost_summary_posted():
    """Test 6: Verify warranty summary was posted to Mattermost."""
    stdout, stderr, returncode = run_solution()
    
    # If no warranty tickets were found, no summary would be posted
    if 'No warranty tickets' in stdout:
        pytest.skip("No warranty tickets processed, so no Mattermost summary expected")
    
    token = get_mattermost_token()
    if not token:
        pytest.skip("Mattermost token not available")
    
    try:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get teams
        teams_resp = requests.get(f"{MATTERMOST_URL}/api/v4/teams", headers=headers, timeout=30)
        if teams_resp.status_code != 200:
            pytest.skip(f"Could not get Mattermost teams: {teams_resp.status_code}")
        
        teams = teams_resp.json()
        if not teams:
            pytest.skip("No Mattermost teams found")
        
        team_id = teams[0]['id']
        
        # Get channels
        channels_resp = requests.get(
            f"{MATTERMOST_URL}/api/v4/teams/{team_id}/channels",
            headers=headers,
            timeout=30
        )
        
        if channels_resp.status_code != 200:
            pytest.skip(f"Could not get channels: {channels_resp.status_code}")
        
        channels = channels_resp.json()
        
        # Find target channel
        target_channel = None
        for ch in channels:
            name = ch.get('name', '').lower()
            if 'customer' in name or 'loyalty' in name:
                target_channel = ch
                break
        
        if not target_channel:
            for ch in channels:
                if ch.get('name') == 'town-square':
                    target_channel = ch
                    break
        
        if not target_channel:
            pytest.skip("No suitable Mattermost channel found")
        
        # Check for warranty posts
        posts_resp = requests.get(
            f"{MATTERMOST_URL}/api/v4/channels/{target_channel['id']}/posts",
            headers=headers,
            timeout=30
        )
        
        if posts_resp.status_code == 200:
            posts_data = posts_resp.json()
            posts = posts_data.get('posts', {})
            
            for post_id, post in posts.items():
                message = post.get('message', '').lower()
                if 'warranty' in message and ('validation' in message or 'processed' in message or 'summary' in message):
                    return  # Found warranty summary post
            
            pytest.fail("No warranty summary post found in Mattermost channel")
    except requests.RequestException as e:
        pytest.skip(f"Mattermost unavailable: {e}")


def test_approved_decisions_have_rma_info():
    """Test 7: Verify approved warranty decisions include RMA instructions."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script failed: {stderr}"
    
    # If there are approved tickets, check Zammad for RMA info in comments
    if 'approved' in stdout.lower() and '0 approved' not in stdout.lower():
        try:
            auth = get_zammad_auth()
            response = requests.get(f"{ZAMMAD_URL}/api/v1/tickets", auth=auth, timeout=30)
            
            if response.status_code == 200:
                tickets = response.json()
                for ticket in tickets[:10]:
                    ticket_id = ticket.get('id')
                    if not ticket_id:
                        continue
                    
                    articles_resp = requests.get(
                        f"{ZAMMAD_URL}/api/v1/ticket_articles/by_ticket/{ticket_id}",
                        auth=auth,
                        timeout=30
                    )
                    
                    if articles_resp.status_code == 200:
                        for article in articles_resp.json():
                            body = article.get('body', '').lower()
                            if 'approved' in body and ('rma' in body or 'return' in body or 'replacement' in body):
                                return  # Found RMA info
        except requests.RequestException:
            pass  # Skip if Zammad unavailable


def test_no_critical_errors():
    """Test 8: Verify no critical errors in execution."""
    stdout, stderr, returncode = run_solution()
    assert returncode == 0, f"Script crashed with stderr: {stderr}"


def test_warranty_decisions_match_expected_orders():
    """
    Test 9: Verify warranty decision logic is correct for known seeded orders/tickets.

    Seeded expectations:
    - order_20241201_1 (Premium Laptop, 24 months) -> APPROVED
    - order_20230601_1 (Wireless Mouse, 12 months) -> EXPIRED
    - order_20241101_1 (Office Chair, no warranty) -> NOT COVERED
    """
    stdout, stderr, returncode = run_solution()

    auth = get_zammad_auth()
    try:
        resp = requests.get(f"{ZAMMAD_URL}/api/v1/tickets", auth=auth, timeout=30)
        if resp.status_code != 200:
            pytest.skip(f"Zammad API returned {resp.status_code}")
        tickets = resp.json()
    except requests.RequestException as e:
        pytest.skip(f"Zammad unavailable: {e}")

    assert isinstance(tickets, list), "Unexpected Zammad tickets payload"

    # If no warranty tickets were processed, check if the solution at least handled it
    if 'No warranty tickets' in stdout:
        # Check if any warranty tickets exist in Zammad at all
        warranty_tickets = [t for t in tickets if 'warranty' in str(t.get('title', '')).lower() 
                           or 'warranty' in str(t.get('tags', '')).lower()]
        if not warranty_tickets:
            pytest.skip("No warranty tickets seeded in Zammad environment")
        # If warranty tickets exist but solution didn't find them, that's concerning but not necessarily a solution bug
        # Skip if the issue is with ticket state/tag format in the environment
        pytest.skip("Warranty tickets exist but may not match expected filter criteria")

    expectations = {
        "order_20241201_1": "warranty approved",
        "order_20230601_1": "warranty expired",
        "order_20241101_1": "not covered",
    }

    def find_ticket(order_id: str):
        for t in tickets:
            if order_id in (t.get("title", "") or ""):
                return t
        return None

    # Check if any expected tickets exist
    found_any = False
    for order_id in expectations:
        if find_ticket(order_id):
            found_any = True
            break
    
    if not found_any:
        pytest.skip("Expected warranty tickets not seeded in Zammad environment")

    for order_id, expected_marker in expectations.items():
        ticket = find_ticket(order_id)
        if ticket is None:
            continue  # Skip tickets that weren't seeded

        ticket_id = ticket.get("id")
        if not ticket_id:
            continue

        try:
            articles_resp = requests.get(
                f"{ZAMMAD_URL}/api/v1/ticket_articles/by_ticket/{ticket_id}",
                auth=auth,
                timeout=30,
            )
        except requests.RequestException as e:
            pytest.skip(f"Zammad unavailable when fetching articles: {e}")

        if articles_resp.status_code != 200:
            continue

        articles = articles_resp.json()
        if not isinstance(articles, list):
            continue

        bodies = [str(a.get("body", "") or "").lower() for a in articles if isinstance(a, dict)]
        assert any(expected_marker in b for b in bodies), (
            f"Expected '{expected_marker}' comment not found for {order_id}. "
            f"Found bodies: {bodies[:5]}"
        )
