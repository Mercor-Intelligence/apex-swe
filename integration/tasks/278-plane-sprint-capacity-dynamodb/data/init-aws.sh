#!/bin/bash
set -e

echo "Initializing LocalStack services..."

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
for i in {1..30}; do
    if aws --endpoint-url=http://localstack:4566 dynamodb list-tables --region us-east-1 2>/dev/null; then
        echo "LocalStack is ready!"
        break
    fi
    echo "Waiting for LocalStack... (attempt $i/30)"
    sleep 2
done

# Create DynamoDB table for sprint capacity
echo "Creating DynamoDB table: sprint-capacity"
aws dynamodb create-table \
    --endpoint-url http://localstack:4566 \
    --region us-east-1 \
    --table-name sprint-capacity \
    --attribute-definitions \
        AttributeName=assignee,AttributeType=S \
        AttributeName=sprint_id,AttributeType=S \
    --key-schema \
        AttributeName=assignee,KeyType=HASH \
        AttributeName=sprint_id,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    2>/dev/null || echo "Table sprint-capacity may already exist"

echo "Verifying table..."
aws dynamodb describe-table \
    --endpoint-url http://localstack:4566 \
    --region us-east-1 \
    --table-name sprint-capacity \
    --query 'Table.TableStatus' \
    --output text

echo "LocalStack initialization complete!"
