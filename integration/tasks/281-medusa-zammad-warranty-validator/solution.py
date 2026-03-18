#!/usr/bin/env python3
"""
Task 281: Medusa Warranty Validator for Zammad Tickets
Automates warranty eligibility checks for customer support tickets.
"""

import os
import sys
import json
import requests
import re
import socket
import time
from datetime import datetime, timedelta


def wait_for_service_dns(hostname, timeout=60):
    """Wait for DNS to resolve service hostname."""
    print(f"Waiting for DNS resolution of {hostname}...", file=sys.stderr)
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            socket.gethostbyname(hostname)
            print(f"✓ DNS resolved: {hostname}", file=sys.stderr)
            return True
        except socket.gaierror:
            time.sleep(2)
    print(f"⚠️  DNS timeout for {hostname}", file=sys.stderr)
    return False


def read_token(service_name):
    """Read service token from MCP config."""
    config_file = "/config/mcp-config.txt"
    try:
        with open(config_file, 'r') as f:
            for line in f:
                if line.startswith(f'export {service_name.upper()}_TOKEN=') or line.startswith(f'export {service_name.upper()}_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except:
        pass
    return None


def get_medusa_jwt_token():
    """Authenticate with Medusa and get JWT token."""
    base_url = os.environ.get("MEDUSA_BACKEND_URL", "http://medusa:9000")
    
    try:
        response = requests.post(
            f"{base_url}/auth/user/emailpass",
            json={"email": "admin@test.com", "password": "supersecret"},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        
        data = response.json()
        token = (data.get("token") or 
                data.get("access_token") or 
                (data.get("data") or {}).get("token"))
        
        return base_url, token
    except Exception as e:
        print(f"Error authenticating with Medusa: {e}", file=sys.stderr)
        return None, None


def fetch_warranty_tickets():
    """Fetch warranty-tagged tickets from Zammad that are new or open."""
    base_url = os.environ.get("ZAMMAD_SITE_URL", "http://zammad:8080")
    token = read_token("ZAMMAD")
    
    if not token:
        print("No Zammad token found", file=sys.stderr)
        return base_url, token, []
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Fetch all tickets
        response = requests.get(
            f"{base_url}/api/v1/tickets",
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        
        all_tickets = response.json()
        warranty_tickets = []
        
        for ticket in all_tickets:
            # Check if ticket has warranty tag - handle both list and string formats
            tags = ticket.get("tags", [])
            if isinstance(tags, str):
                has_warranty = "warranty" in tags.lower()
            elif isinstance(tags, list):
                has_warranty = any("warranty" in str(t).lower() for t in tags)
            else:
                has_warranty = False
            
            # Also check title for warranty keyword as fallback
            title = ticket.get("title", "").lower()
            if not has_warranty and "warranty" not in title:
                continue
            
            # Check if ticket is new or open
            state = ticket.get("state", "")
            state_id = ticket.get("state_id")
            # State can be string name or ID (1=new, 2=open typically)
            if state not in ["new", "open"] and state_id not in [1, 2]:
                continue
            
            warranty_tickets.append(ticket)
        
        print(f"Found {len(warranty_tickets)} warranty tickets", file=sys.stderr)
        return base_url, token, warranty_tickets
    except Exception as e:
        print(f"Error fetching Zammad tickets: {e}", file=sys.stderr)
        return base_url, token, []


def extract_order_id(ticket, zammad_url, zammad_token):
    """Extract order ID from ticket title or article body."""
    title = ticket.get("title", "")
    
    # First try ticket title
    match = re.search(r'order_\d{8}_\d+', title)
    if match:
        return match.group(0)
    
    # Then try to fetch articles and search their bodies
    ticket_id = ticket.get("id")
    if ticket_id and zammad_token:
        try:
            headers = {
                "Authorization": f"Bearer {zammad_token}",
                "Content-Type": "application/json"
            }
            articles_resp = requests.get(
                f"{zammad_url}/api/v1/ticket_articles/by_ticket/{ticket_id}",
                headers=headers,
                timeout=30
            )
            if articles_resp.status_code == 200:
                articles = articles_resp.json()
                for article in articles:
                    body = article.get("body", "")
                    match = re.search(r'order_\d{8}_\d+', body)
                    if match:
                        return match.group(0)
        except Exception as e:
            print(f"Error fetching articles for ticket {ticket_id}: {e}", file=sys.stderr)
    
    return None


def validate_warranty(order_id, medusa_base_url, medusa_token):
    """Validate warranty status for an order."""
    headers = {
        "Authorization": f"Bearer {medusa_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Fetch order details
        response = requests.get(
            f"{medusa_base_url}/admin/orders/{order_id}",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 404:
            return "not_found", "Order not found"
        
        response.raise_for_status()
        order = response.json().get("order", {})
        
        # Check order status
        if order.get("status") != "completed":
            return "not_found", f"Order status is {order.get('status')}, not completed"
        
        # Get order creation date
        created_at_str = order.get("created_at", "")
        if not created_at_str:
            return "not_found", "Order has no creation date"
        
        order_date = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
        
        # Check products for warranty
        items = order.get("items", [])
        if not items:
            return "not_covered", "Order has no items"
        
        # Check first product's warranty
        first_item = items[0]
        variant = first_item.get("variant", {})
        product = variant.get("product", {})
        metadata = product.get("metadata", {})
        
        warranty_months_str = metadata.get("warranty_months")
        if not warranty_months_str:
            return "not_covered", "Product has no warranty coverage"
        
        try:
            warranty_months = int(warranty_months_str)
        except:
            return "not_covered", "Invalid warranty term"
        
        # Calculate warranty expiration
        warranty_end = order_date + timedelta(days=warranty_months * 30)
        
        if datetime.now() <= warranty_end:
            return "approved", f"Warranty valid until {warranty_end.strftime('%Y-%m-%d')}"
        else:
            return "expired", f"Warranty expired on {warranty_end.strftime('%Y-%m-%d')}"
        
    except Exception as e:
        print(f"Error validating warranty for {order_id}: {e}", file=sys.stderr)
        return "error", str(e)


def update_zammad_ticket(ticket_id, decision, reason):
    """Update Zammad ticket with warranty decision."""
    base_url = os.environ.get("ZAMMAD_SITE_URL", "http://zammad:8080")
    token = read_token("ZAMMAD")
    
    if not token:
        return False
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Create comment based on decision
    if decision == "approved":
        comment = f"✅ WARRANTY APPROVED\n\n{reason}\n\nNext steps: An RMA label will be sent to your email within 1 business day. Please package the item securely and ship it back using the provided label."
    elif decision == "expired":
        comment = f"❌ WARRANTY EXPIRED\n\n{reason}\n\nUnfortunately, this order is no longer covered under warranty. You may still be able to purchase repair services. Please contact our sales team for options."
    elif decision == "not_covered":
        comment = f"❌ NOT COVERED\n\n{reason}\n\nThis product does not include warranty coverage. For repair options, please contact our sales team."
    else:
        comment = f"⚠️ UNABLE TO VALIDATE\n\n{reason}\n\nPlease verify your order ID and contact support if you believe this is an error."
    
    try:
        # Post article/comment
        article_data = {
            "ticket_id": ticket_id,
            "body": comment,
            "type": "note",
            "internal": False
        }
        
        response = requests.post(
            f"{base_url}/api/v1/ticket_articles",
            headers=headers,
            json=article_data,
            timeout=30
        )
        response.raise_for_status()
        
        return True
    except Exception as e:
        print(f"Error updating ticket {ticket_id}: {e}", file=sys.stderr)
        return False


def post_to_mattermost(summary_message):
    """Post summary to Mattermost."""
    base_url = os.environ.get("MATTERMOST_URL", "http://mattermost-server:8065")
    token = read_token("MATTERMOST")
    team_name = os.environ.get("MATTERMOST_TEAM", "test-demo")
    
    if not token:
        return False
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Get team ID
        team_resp = requests.get(f"{base_url}/api/v4/teams/name/{team_name}", headers=headers, timeout=10)
        team_resp.raise_for_status()
        team_id = team_resp.json().get("id")
        
        # Get channels
        channels_resp = requests.get(f"{base_url}/api/v4/teams/{team_id}/channels", headers=headers, timeout=10)
        channels = channels_resp.json()
        
        # Try customer-loyalty, fallback to town-square
        channel_id = None
        for ch in channels:
            if ch.get("name") == "customer-loyalty":
                channel_id = ch.get("id")
                break
        
        if not channel_id:
            for ch in channels:
                if ch.get("name") == "town-square":
                    channel_id = ch.get("id")
                    break
        
        if channel_id:
            post_data = {"channel_id": channel_id, "message": summary_message}
            requests.post(f"{base_url}/api/v4/posts", headers=headers, json=post_data, timeout=10)
            return True
        
        return False
    except Exception as e:
        print(f"Error posting to Mattermost: {e}", file=sys.stderr)
        return False


def main():
    # Wait for DNS to be ready
    wait_for_service_dns('medusa')
    wait_for_service_dns('zammad')
    
    # Authenticate with Medusa
    medusa_base_url, medusa_token = get_medusa_jwt_token()
    if not medusa_token:
        print("Failed to authenticate with Medusa", file=sys.stderr)
        print("No warranty tickets found")
        return
    
    # Fetch warranty tickets
    zammad_url, zammad_token, tickets = fetch_warranty_tickets()
    
    if not tickets:
        print("No warranty tickets found")
        return
    
    # Process each ticket
    results = {"approved": [], "expired": [], "not_covered": [], "not_found": [], "error": []}
    
    for ticket in tickets:
        ticket_id = ticket.get("id")
        order_id = extract_order_id(ticket, zammad_url, zammad_token)
        
        if not order_id:
            decision = "error"
            reason = "Could not extract order ID from ticket"
        else:
            decision, reason = validate_warranty(order_id, medusa_base_url, medusa_token)
        
        # Update ticket
        update_zammad_ticket(ticket_id, decision, reason)
        
        # Track result
        if decision in results:
            results[decision].append(str(ticket_id))
    
    # Calculate totals
    total_processed = len(tickets)
    approved_count = len(results["approved"])
    denied_count = total_processed - approved_count
    
    # Post to Mattermost
    summary = f"## 🛡️ Warranty Validation Summary\n\n"
    summary += f"**Total Processed**: {total_processed}\n"
    summary += f"**Approved**: {approved_count}\n"
    summary += f"**Denied**: {denied_count}\n\n"
    
    if results["approved"]:
        summary += f"**Approved Tickets**: {', '.join(results['approved'])}\n"
    
    post_to_mattermost(summary)
    
    # Print summary to stdout
    print(f"Processed {total_processed} warranty tickets ({approved_count} approved, {denied_count} denied)")


if __name__ == "__main__":
    main()
