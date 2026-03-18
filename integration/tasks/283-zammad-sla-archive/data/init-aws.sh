#!/bin/bash
set -e

echo "Initializing LocalStack services..."

# Wait for LocalStack to be ready
echo "Waiting for LocalStack to be ready..."
for i in {1..30}; do
    if aws --endpoint-url=http://localstack:4566 s3 ls --region us-east-1 2>/dev/null; then
        echo "LocalStack is ready!"
        break
    fi
    echo "Waiting for LocalStack... (attempt $i/30)"
    sleep 2
done

# Create S3 bucket for support metrics
echo "Creating S3 bucket: support-metrics"
aws s3 mb s3://support-metrics \
    --endpoint-url http://localstack:4566 \
    --region us-east-1 \
    2>/dev/null || echo "Bucket support-metrics may already exist"

echo "Verifying bucket..."
aws s3 ls s3://support-metrics \
    --endpoint-url http://localstack:4566 \
    --region us-east-1

echo "LocalStack initialization complete!"
