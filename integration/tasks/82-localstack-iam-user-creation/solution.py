#!/usr/bin/env python3

import boto3
import sys
from botocore.exceptions import ClientError


def create_iam_user_and_key():
    """Create IAM user and access key in LocalStack, write output to file."""
    output_file = "/app/iam_output.txt"
    user_name = "test-user"
    localstack_endpoint = "http://localstack:4566"
    
    try:
        # Create IAM client for LocalStack
        iam_client = boto3.client(
            'iam',
            endpoint_url=localstack_endpoint,
            region_name='us-east-1',
            aws_access_key_id='test',
            aws_secret_access_key='test'
        )
        
        # Create IAM user (handle if already exists)
        try:
            iam_client.create_user(UserName=user_name)
            print(f"Created IAM user: {user_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                print(f"IAM user {user_name} already exists, continuing...")
            else:
                raise
        
        # Check for existing access keys before creating a new one
        existing_keys = iam_client.list_access_keys(UserName=user_name)
        if existing_keys['AccessKeyMetadata']:
            # Use existing access key
            access_key_id = existing_keys['AccessKeyMetadata'][0]['AccessKeyId']
            print(f"Using existing access key: {access_key_id}")
        else:
            # Create new access key for the user
            response = iam_client.create_access_key(UserName=user_name)
            access_key_id = response['AccessKey']['AccessKeyId']
            print(f"Created access key: {access_key_id}")
        
        # Write output to file
        output_text = f"Created user: {user_name}, Access Key: {access_key_id}"
        with open(output_file, 'w') as f:
            f.write(output_text)
        
        print(f"Successfully wrote output to {output_file}")
        print(f"Output: {output_text}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    create_iam_user_and_key()