#!/bin/bash
set -e
echo "Initializing LocalStack for task 247 (Customer Journey Analytics)..."

export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test

# Wait a bit for LocalStack to be fully ready
sleep 2

# Create S3 bucket for customer analytics reports
echo "Creating S3 bucket: customer-analytics"
awslocal s3 mb s3://customer-analytics 2>/dev/null || echo "Bucket customer-analytics may already exist"
awslocal s3 ls | grep customer-analytics

echo "LocalStack initialization complete!"
echo "Resources created:"
echo "  - S3 bucket: customer-analytics"