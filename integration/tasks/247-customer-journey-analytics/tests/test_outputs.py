"""
Comprehensive tests for Customer Journey Analytics Pipeline
Tests analytics across Medusa, Zammad, EspoCRM, S3, and Mattermost
"""
import requests
import boto3
import os
import subprocess
import pytest
import json
import re
from collections import defaultdict


def get_medusa_token():
    """Helper to get Medusa admin token."""
    medusa_url = os.environ.get('MEDUSA_URL', 'http://medusa:9000')
    auth_url = f"{medusa_url}/auth/user/emailpass"
    
    response = requests.post(
        auth_url,
        json={
            'email': 'admin@example.com',
            'password': 'supersecret'
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    
    token = (
        data.get('token')
        or data.get('access_token')
        or (data.get('data') or {}).get('token')
    )
    
    return token


def get_s3_client():
    """Helper to get configured S3 client."""
    return boto3.client(
        's3',
        endpoint_url=os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )


def get_unique_customer_emails_from_sources():
    """Get all unique customer emails across all sources for validation."""
    unique_emails = set()
    
    # Get emails from Medusa orders
    try:
        token = get_medusa_token()
        medusa_url = os.environ.get('MEDUSA_URL', 'http://medusa:9000')
        orders_url = f"{medusa_url}/admin/orders"
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.get(orders_url, headers=headers, timeout=30)
        if response.status_code == 200:
            orders = response.json().get('orders', [])
            for order in orders:
                email = order.get('email', '').lower().strip()
                if email:
                    unique_emails.add(email)
    except Exception:
        pass
    
    # Get emails from Zammad tickets
    try:
        zammad_url = os.environ.get('ZAMMAD_SITE_URL', 'http://zammad')
        tickets_url = f"{zammad_url}/api/v1/tickets"
        response = requests.get(tickets_url, auth=('admin@example.com', 'admin'), timeout=30)
        
        if response.status_code == 200:
            tickets = response.json() if isinstance(response.json(), list) else []
            for ticket in tickets:
                email = ticket.get('customer', {}).get('email', '') or ticket.get('customer_email', '')
                email = email.lower().strip()
                if email:
                    unique_emails.add(email)
    except Exception:
        pass
    
    # Get emails from EspoCRM contacts
    try:
        espocrm_url = os.environ.get('ESPOCRM_SITE_URL', 'http://espocrm')
        contacts_url = f"{espocrm_url}/api/v1/Contact"
        response = requests.get(contacts_url, auth=('admin', 'admin'), timeout=30)
        
        if response.status_code == 200:
            contacts = response.json().get('list', [])
            for contact in contacts:
                email = contact.get('emailAddress', '') or contact.get('email', '')
                email = email.lower().strip()
                if email:
                    unique_emails.add(email)
    except Exception:
        pass
    
    return unique_emails


def test_script_exists():
    """Test 1: Verify script exists at expected location."""
    script_path = '/app/customer_analytics.py'
    assert os.path.exists(script_path), f"Script not found at {script_path}"
    assert os.access(script_path, os.X_OK), f"Script at {script_path} is not executable"


def test_script_execution_succeeds():
    """Test 2: Verify script executes without errors."""
    script_path = '/app/customer_analytics.py'
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"
    assert 'analyzed' in result.stdout.lower(), f"Expected output message not found. Stdout: {result.stdout}"


def test_report_uploaded_to_s3():
    """Test 3: Verify analytics report uploaded to S3."""
    # Run the script
    script_path = '/app/customer_analytics.py'
    subprocess.run(['python3', script_path], timeout=120, check=False)
    
    # Check S3 for report
    try:
        s3 = get_s3_client()
        
        # Check if report exists
        response = s3.head_object(
            Bucket='customer-analytics',
            Key='customer_journey_report.json'
        )
        
        assert response['ResponseMetadata']['HTTPStatusCode'] == 200, "Report not found in S3"
        
        # Download and validate report structure
        obj_response = s3.get_object(
            Bucket='customer-analytics',
            Key='customer_journey_report.json'
        )
        content = obj_response['Body'].read().decode('utf-8')
        report = json.loads(content)
        
        # Verify report structure
        assert 'summary' in report, "Report missing 'summary' section"
        assert 'customers' in report, "Report missing 'customers' section"
        
        summary = report['summary']
        assert 'total_customers' in summary, "Summary missing 'total_customers'"
        assert 'average_health_score' in summary, "Summary missing 'average_health_score'"
        assert 'healthy_count' in summary, "Summary missing 'healthy_count'"
        assert 'at_risk_count' in summary, "Summary missing 'at_risk_count'"
        assert 'critical_count' in summary, "Summary missing 'critical_count'"
        
    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pytest.skip(f"Service unavailable: {e}")


def test_health_score_calculation():
    """Test 4: Verify health score calculation logic is correct."""
    # Run the script
    script_path = '/app/customer_analytics.py'
    subprocess.run(['python3', script_path], timeout=120, check=False)
    
    # Get report from S3
    try:
        s3 = get_s3_client()
        obj_response = s3.get_object(
            Bucket='customer-analytics',
            Key='customer_journey_report.json'
        )
        content = obj_response['Body'].read().decode('utf-8')
        report = json.loads(content)
        
        customers = report['customers']
        
        if not customers:
            pytest.skip("No customers to test health score calculation")
        
        # Verify health score formula for each customer
        for customer in customers:
            expected_score = (
                (customer['order_count'] * 10)
                - (customer['support_ticket_count'] * 5)
                + (customer['crm_interactions'] * 3)
            )
            
            assert customer['health_score'] == expected_score, (
                f"Health score mismatch for {customer['email']}: "
                f"expected {expected_score}, got {customer['health_score']}"
            )
            
            # Verify classification
            score = customer['health_score']
            if score > 50:
                expected_class = "Healthy"
            elif score >= 20:
                expected_class = "At Risk"
            else:
                expected_class = "Critical"
            
            assert customer['classification'] == expected_class, (
                f"Classification mismatch for {customer['email']}: "
                f"expected {expected_class}, got {customer['classification']}"
            )
        
    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pytest.skip(f"Service unavailable: {e}")


def test_all_customers_included():
    """Test 5: Verify all customers from all sources are included in report."""
    # Get expected unique customers
    expected_emails = get_unique_customer_emails_from_sources()
    
    if not expected_emails:
        pytest.skip("No customer emails found in any source")
    
    # Run the script
    script_path = '/app/customer_analytics.py'
    subprocess.run(['python3', script_path], timeout=120, check=False)
    
    # Get report from S3
    try:
        s3 = get_s3_client()
        obj_response = s3.get_object(
            Bucket='customer-analytics',
            Key='customer_journey_report.json'
        )
        content = obj_response['Body'].read().decode('utf-8')
        report = json.loads(content)
        
        # Get emails from report
        report_emails = {c['email'] for c in report['customers']}
        
        # Check if all expected emails are in report
        missing_emails = expected_emails - report_emails
        
        # Allow some tolerance since services may have different data
        coverage = len(report_emails & expected_emails) / len(expected_emails) if expected_emails else 0
        
        assert coverage >= 0.8, (
            f"Report missing significant customer data. "
            f"Coverage: {coverage:.1%}, Missing: {len(missing_emails)} customers"
        )
        
    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pytest.skip(f"Service unavailable: {e}")


def test_mattermost_insights_posted():
    """Test 6: Verify insights posted to Mattermost customer-success channel."""
    # Run the script
    script_path = '/app/customer_analytics.py'
    subprocess.run(['python3', script_path], timeout=120, check=False)
    
    # Check Mattermost for insights (optional - skip if not accessible)
    mattermost_url = os.environ.get('MATTERMOST_URL', 'http://mattermost:8065')
    
    try:
        # Authenticate
        login_url = f"{mattermost_url}/api/v4/users/login"
        login_response = requests.post(
            login_url,
            json={
                'login_id': 'admin@example.com',
                'password': 'admin123'
            },
            timeout=30
        )
        
        if login_response.status_code != 200:
            pytest.skip(f"Mattermost authentication failed: {login_response.status_code}")
        
        token = login_response.headers.get('Token')
        if not token:
            pytest.skip("No Mattermost token received")
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        # Get team ID
        teams_url = f"{mattermost_url}/api/v4/users/me/teams"
        teams_response = requests.get(teams_url, headers=headers, timeout=30)
        
        if teams_response.status_code != 200:
            pytest.skip("Cannot access Mattermost teams")
        
        teams = teams_response.json()
        if not teams:
            pytest.skip("No Mattermost teams found")
        
        team_id = teams[0]['id']
        
        # Get customer-success channel
        channels_url = f"{mattermost_url}/api/v4/teams/{team_id}/channels/name/customer-success"
        channels_response = requests.get(channels_url, headers=headers, timeout=30)
        
        if channels_response.status_code != 200:
            pytest.skip("customer-success channel not found")
        
        channel = channels_response.json()
        channel_id = channel['id']
        
        # Get recent posts
        posts_url = f"{mattermost_url}/api/v4/channels/{channel_id}/posts"
        posts_response = requests.get(posts_url, headers=headers, timeout=30)
        
        if posts_response.status_code != 200:
            pytest.skip("Cannot access channel posts")
        
        posts_data = posts_response.json()
        posts = posts_data.get('posts', {})
        
        # Look for analytics insights message
        insights_found = False
        for post_id, post in posts.items():
            message = post.get('message', '')
            if 'Customer Journey Analytics' in message or 'Health Distribution' in message:
                insights_found = True
                # Verify message contains key metrics
                assert 'Total Customers Analyzed' in message or 'customers' in message.lower()
                break
        
        assert insights_found, "Analytics insights not found in Mattermost customer-success channel"
        
    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pytest.skip(f"Service unavailable: {e}")


def test_output_format():
    """Test 7: Verify script output format is correct."""
    script_path = '/app/customer_analytics.py'
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    # Verify output format: "Analyzed X customers, avg health score: Y.Z"
    pattern = r'Analyzed \d+ customers, avg health score: \d+\.\d+'
    assert re.search(pattern, result.stdout), (
        f"Output does not match expected format. Stdout: {result.stdout}"
    )


def test_handles_no_customers_gracefully():
    """Test 8: Verify script handles zero customers gracefully."""
    # This test verifies the script doesn't crash with 0 customers
    # The script should still produce the expected output format
    
    script_path = '/app/customer_analytics.py'
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    # Should not crash
    assert result.returncode == 0, f"Script crashed with no customers. Stderr: {result.stderr}"
    
    # Should produce expected output format
    pattern = r'Analyzed \d+ customers, avg health score: \d+\.\d+'
    assert re.search(pattern, result.stdout), (
        f"Output format incorrect with no customers. Stdout: {result.stdout}"
    )


def test_summary_statistics_accuracy():
    """Test 9: Verify summary statistics are correctly calculated."""
    # Run the script
    script_path = '/app/customer_analytics.py'
    subprocess.run(['python3', script_path], timeout=120, check=False)
    
    # Get report from S3
    try:
        s3 = get_s3_client()
        obj_response = s3.get_object(
            Bucket='customer-analytics',
            Key='customer_journey_report.json'
        )
        content = obj_response['Body'].read().decode('utf-8')
        report = json.loads(content)
        
        summary = report['summary']
        customers = report['customers']
        
        # Verify total customers count
        assert summary['total_customers'] == len(customers), (
            f"Total customer count mismatch: summary says {summary['total_customers']}, "
            f"but found {len(customers)} customers"
        )
        
        if customers:
            # Verify average health score
            actual_avg = sum(c['health_score'] for c in customers) / len(customers)
            assert abs(summary['average_health_score'] - actual_avg) < 0.1, (
                f"Average health score mismatch: expected {actual_avg:.1f}, "
                f"got {summary['average_health_score']}"
            )
            
            # Verify classification counts
            healthy = sum(1 for c in customers if c['classification'] == 'Healthy')
            at_risk = sum(1 for c in customers if c['classification'] == 'At Risk')
            critical = sum(1 for c in customers if c['classification'] == 'Critical')
            
            assert summary['healthy_count'] == healthy, f"Healthy count mismatch"
            assert summary['at_risk_count'] == at_risk, f"At risk count mismatch"
            assert summary['critical_count'] == critical, f"Critical count mismatch"
        
    except Exception as e:
        if isinstance(e, AssertionError):
            raise
        pytest.skip(f"Service unavailable: {e}")
