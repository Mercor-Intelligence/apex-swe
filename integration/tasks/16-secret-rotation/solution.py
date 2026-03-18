#!/usr/bin/env python3
import boto3
import json


def fetch_and_write_api_key():
    """
    Fetch the api-token-secret from AWS Secrets Manager and write the api_key to file.
    """
    # Create Secrets Manager client with LocalStack endpoint
    secretsmanager_client = boto3.client(
        'secretsmanager',
        endpoint_url='http://localstack:4566',
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )
    
    # Get secret value
    response = secretsmanager_client.get_secret_value(SecretId='api-token-secret')
    secret_string = response['SecretString']
    
    # Parse JSON
    secret_data = json.loads(secret_string)
    api_key = secret_data['api_key']
    
    # Write api_key to file
    with open('/app/api_key.txt', 'w') as f:
        f.write(api_key)
    
    print(f"API key written to /app/api_key.txt")


if __name__ == "__main__":
    fetch_and_write_api_key()
