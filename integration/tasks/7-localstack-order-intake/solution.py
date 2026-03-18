#!/usr/bin/env python3
"""
Oracle solution: Insert a hardcoded order into DynamoDB table 'orders'
"""

import boto3
import os
from decimal import Decimal


def insert_order():
    """
    Insert a hardcoded order into DynamoDB table 'orders'
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
    
    # Define the hardcoded order (convert float to Decimal for DynamoDB)
    order = {
        "orderId": "ORD-001",
        "customerId": "CUST-123",
        "items": [
            {
                "productId": "PROD-A",
                "quantity": 2,
                "price": Decimal("29.99")
            }
        ],
        "total": Decimal("59.98"),
        "currency": "USD",
        "status": "pending",
        "createdAt": "2025-01-15T10:30:00Z"
    }
    
    # Insert the order into DynamoDB
    response = table.put_item(Item=order)
    
    print(f"Successfully inserted order {order['orderId']} into DynamoDB")
    print(f"Response: {response['ResponseMetadata']['HTTPStatusCode']}")
    
    # Verify the item exists
    get_response = table.get_item(Key={'orderId': 'ORD-001'})
    if 'Item' in get_response:
        print(f"Verification: Order {get_response['Item']['orderId']} exists in DynamoDB")
        return True
    else:
        print("Warning: Order not found after insertion")
        return False


if __name__ == "__main__":
    success = insert_order()
    exit(0 if success else 1)
