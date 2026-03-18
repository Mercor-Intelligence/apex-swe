#!/bin/bash

# This script is used to create prereq infrastructure for on localstack
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test

# Configure default region and LocalStack endpoint
export AWS_DEFAULT_REGION=us-east-1
AWS_ENDPOINT_URL=${AWS_ENDPOINT_URL:-http://localhost:4566}

# Helper: detect awslocal or fallback to aws --endpoint-url
if command -v awslocal >/dev/null 2>&1; then
  AWS_CMD="awslocal"
else
  AWS_CMD="aws --endpoint-url=$AWS_ENDPOINT_URL"
fi

echo "Checking connectivity to LocalStack at $AWS_ENDPOINT_URL..."
$AWS_CMD sts get-caller-identity >/dev/null 2>&1 || echo "Warning: Unable to get caller identity (ok on LocalStack without STS). Proceeding."

echo "Ensuring DynamoDB table 'orders' exists..."

# Idempotent table create: create only if not exists
TABLE_EXISTS=$($AWS_CMD dynamodb list-tables --output json | grep -o '"orders"' || true)
if [ -z "$TABLE_EXISTS" ]; then
  $AWS_CMD dynamodb create-table \
    --table-name orders \
    --attribute-definitions AttributeName=orderId,AttributeType=S \
    --key-schema AttributeName=orderId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  echo "Created DynamoDB table 'orders'."
else
  echo "DynamoDB table 'orders' already exists."
fi

# Optional: wait until table is active
$AWS_CMD dynamodb wait table-exists --table-name orders || true

echo "Prerequisites complete."