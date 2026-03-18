import subprocess
import base64
import json
import time
import requests
import pytest
import re
import boto3
import os
from decimal import Decimal


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/insert_order.py"
    legacy_path = "/app/intake.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(legacy_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path}, {legacy_path}, or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    script_path = "/app/insert_order.py"
    legacy_path = "/app/intake.py"
    if not os.path.exists(script_path):
        if os.path.exists(legacy_path):
            script_path = legacy_path
        else:
            script_path = "/app/solution.py"
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"




def test_order_exists_in_dynamodb():
    """
    Test that the hardcoded order exists in DynamoDB with all required fields
    """
    # Configure LocalStack endpoint
    localstack_url = os.environ.get('LOCALSTACK_URL', 'http://localstack:4566')
    aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

    # Create DynamoDB client
    dynamodb = boto3.resource(
        'dynamodb',
        endpoint_url=localstack_url,
        region_name=aws_region,
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID', 'test'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY', 'test')
    )

    # Get the orders table
    table = dynamodb.Table('orders')

    # Query for the specific order
    response = table.get_item(Key={'orderId': 'ORD-001'})

    # Assert the item exists
    assert 'Item' in response, "Order ORD-001 not found in DynamoDB"

    item = response['Item']

    # Validate all required fields
    assert item['orderId'] == 'ORD-001', "orderId mismatch"
    assert item['customerId'] == 'CUST-123', "customerId mismatch"
    assert item['currency'] == 'USD', "currency mismatch"
    assert item['status'] == 'pending', "status mismatch"
    assert item['createdAt'] == '2025-01-15T10:30:00Z', "createdAt mismatch"

    # Validate numeric fields (DynamoDB returns Decimal)
    assert item['total'] == Decimal('59.98'), f"total mismatch: expected 59.98, got {item['total']}"

    # Validate items array
    assert 'items' in item, "items field missing"
    assert isinstance(item['items'], list), "items should be a list"
    assert len(item['items']) == 1, "items should contain 1 item"

    # Validate first item in items array
    first_item = item['items'][0]
    assert first_item['productId'] == 'PROD-A', "productId mismatch"
    assert first_item['quantity'] == 2, "quantity mismatch"
    assert first_item['price'] == Decimal('29.99'), f"price mismatch: expected 29.99, got {first_item['price']}"

    print(f"✓ Order ORD-001 exists with all required fields")
    print(f"✓ Order details: {json.dumps(item, default=str)}")
