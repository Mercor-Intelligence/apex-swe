#!/bin/bash

# This script is used to create prereq infrastructure for on localstack
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test

# Create the api-token-secret in AWS Secrets Manager
awslocal secretsmanager create-secret \
  --name api-token-secret \
  --secret-string '{"api_key": "test-key-123", "created_at": "2025-01-01T00:00:00Z"}'

echo "Secret 'api-token-secret' created successfully"