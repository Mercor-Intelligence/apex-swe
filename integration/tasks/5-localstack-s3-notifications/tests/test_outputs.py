import subprocess
import base64
import json
import time
import requests
import pytest
import re
import os
import boto3
from botocore.exceptions import ClientError


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/s3_sqs_notification.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path} or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    script_path = "/app/s3_sqs_notification.py"
    if not os.path.exists(script_path):
        script_path = "/app/solution.py"
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"



# LocalStack configuration
LOCALSTACK_ENDPOINT = "http://localstack:4566"
BUCKET_NAME = "file-uploads-bucket"
QUEUE_NAME = "file-upload-queue"
OUTPUT_FILE = "/app/sqs_output.txt"


@pytest.fixture
def s3_client():
    """Create S3 client for LocalStack"""
    return boto3.client(
        's3',
        endpoint_url=LOCALSTACK_ENDPOINT,
        aws_access_key_id='test',
        aws_secret_access_key='test',
        region_name='us-east-1'
    )


@pytest.fixture
def sqs_client():
    """Create SQS client for LocalStack"""
    return boto3.client(
        'sqs',
        endpoint_url=LOCALSTACK_ENDPOINT,
        aws_access_key_id='test',
        aws_secret_access_key='test',
        region_name='us-east-1'
    )


def test_bucket_created(s3_client):
    """
    Test 1: Verify S3 bucket was created
    Purpose: Confirms bucket creation logic worked
    """
    # List all S3 buckets
    response = s3_client.list_buckets()
    bucket_names = [bucket['Name'] for bucket in response['Buckets']]

    # Assert file-uploads-bucket exists
    assert BUCKET_NAME in bucket_names, f"Bucket {BUCKET_NAME} not found in {bucket_names}"


def test_sqs_queue_exists(sqs_client):
    """
    Test 2: Verify prerequisite SQS queue exists
    Purpose: Validates environment setup
    """
    # Get queue URL - should not raise exception
    try:
        response = sqs_client.get_queue_url(QueueName=QUEUE_NAME)
        queue_url = response['QueueUrl']
        assert queue_url is not None
        assert QUEUE_NAME in queue_url
    except ClientError as e:
        pytest.fail(f"SQS queue {QUEUE_NAME} does not exist: {e}")


def test_bucket_notification_to_sqs_configured(s3_client, sqs_client):
    """
    Test 3: Verify S3 → SQS notification setup
    Purpose: Validates notification wiring
    """
    # Get notification configuration
    response = s3_client.get_bucket_notification_configuration(Bucket=BUCKET_NAME)

    # Assert QueueConfigurations exists
    assert 'QueueConfigurations' in response, "No QueueConfigurations found"
    assert len(response['QueueConfigurations']) > 0, "QueueConfigurations is empty"

    # Get the first (and should be only) queue configuration
    queue_config = response['QueueConfigurations'][0]

    # Verify queue ARN contains file-upload-queue
    queue_arn = queue_config['QueueArn']
    assert QUEUE_NAME in queue_arn, f"Queue name {QUEUE_NAME} not in ARN {queue_arn}"

    # Verify events include s3:ObjectCreated:*
    events = queue_config['Events']
    assert 's3:ObjectCreated:*' in events, f"s3:ObjectCreated:* not in events {events}"

    # Check for prefix filter 'uploads/' with standardized validation
    has_prefix_filter = False
    prefix_value = None

    # Standard AWS structure: Filter.Key.FilterRules
    if 'Filter' in queue_config:
        filter_rules = queue_config.get('Filter', {}).get('Key', {}).get('FilterRules', [])
        for rule in filter_rules:
            # LocalStack uses 'Prefix' (capital P), AWS uses 'prefix' (lowercase)
            rule_name = rule.get('Name', '').lower()
            if rule_name == 'prefix':
                prefix_value = rule.get('Value')
                if prefix_value == 'uploads/':
                    has_prefix_filter = True
                break

    # Alternative structure: Direct Prefix field (some LocalStack versions)
    if not has_prefix_filter and 'Prefix' in queue_config:
        prefix_value = queue_config.get('Prefix')
        if prefix_value == 'uploads/':
            has_prefix_filter = True

    # Validation with clear error message
    if not has_prefix_filter:
        error_msg = f"Expected prefix filter 'uploads/' not found. "
        if prefix_value is not None:
            error_msg += f"Found prefix: '{prefix_value}' instead. "
        error_msg += f"Queue config: {json.dumps(queue_config, indent=2, default=str)}"
        pytest.fail(error_msg)


def test_queue_policy_allows_s3(sqs_client):
    """
    Test 4: Verify SQS queue has policy allowing S3
    Purpose: Ensures permission configuration is correct
    """
    # Get queue URL
    queue_url = sqs_client.get_queue_url(QueueName=QUEUE_NAME)['QueueUrl']

    # Get queue attributes including Policy
    response = sqs_client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=['Policy']
    )

    assert 'Attributes' in response, "No attributes in response"
    assert 'Policy' in response['Attributes'], "No Policy attribute found"

    # Parse policy JSON
    policy = json.loads(response['Attributes']['Policy'])

    # Check policy structure
    assert 'Statement' in policy, "No Statement in policy"

    # Find statement that allows S3
    s3_statement = None
    for statement in policy['Statement']:
        principal = statement.get('Principal', {})
        if isinstance(principal, dict) and principal.get('Service') == 's3.amazonaws.com':
            s3_statement = statement
            break

    assert s3_statement is not None, "No statement allowing s3.amazonaws.com found"

    # Assert action includes SQS:SendMessage
    action = s3_statement.get('Action')
    assert action == 'SQS:SendMessage' or 'SQS:SendMessage' in action, \
        f"SQS:SendMessage not in action {action}"


def test_file_uploaded_to_correct_location(s3_client):
    """
    Test 5: Verify test file was uploaded
    Purpose: Confirms upload step completed
    """
    # Check object exists
    try:
        response = s3_client.head_object(Bucket=BUCKET_NAME, Key='uploads/sample.csv')
        assert response is not None
    except ClientError as e:
        pytest.fail(f"File uploads/sample.csv not found in bucket {BUCKET_NAME}: {e}")

    # Download and verify it's valid CSV
    obj = s3_client.get_object(Bucket=BUCKET_NAME, Key='uploads/sample.csv')
    content = obj['Body'].read().decode('utf-8')

    # Assert contains sample data (should have headers and data)
    lines = content.strip().split('\n')
    assert len(lines) >= 2, f"CSV should have at least 2 lines (header + data), got {len(lines)}"

    # Verify it has comma-separated values
    assert ',' in lines[0], "CSV header should contain commas"


def test_sqs_message_received(sqs_client):
    """
    Test 6a: Verify message was processed by checking output file exists
    Purpose: Validates that the solution script successfully processed an SQS message

    This test confirms that at least one message was received and processed.
    """
    # The solution script should have consumed the message and written the output file
    assert os.path.exists(OUTPUT_FILE), \
        f"Output file {OUTPUT_FILE} does not exist, indicating no message was processed"


def test_no_duplicate_messages_in_queue(sqs_client):
    """
    Test 6b: Verify no duplicate or unprocessed messages remain in queue
    Purpose: Ensures clean message processing without duplicates

    After the solution runs, the queue should be empty (or only contain test events).
    This validates that messages are properly consumed and not left in the queue.
    """
    # Get queue URL
    queue_url = sqs_client.get_queue_url(QueueName=QUEUE_NAME)['QueueUrl']

    # Try to receive any remaining messages
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=2
    )

    # If there are messages, they should only be test events, not actual ObjectCreated events
    if 'Messages' in response and len(response['Messages']) > 0:
        for message in response['Messages']:
            message_body = json.loads(message['Body'])

            # Allow S3 test events (these are sent when notification is configured)
            if isinstance(message_body, dict) and message_body.get('Event') == 's3:TestEvent':
                # Clean up test event
                sqs_client.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
                continue

            # If it's a real ObjectCreated event, this indicates a duplicate or unprocessed message
            if 'Records' in message_body:
                event_record = message_body['Records'][0]
                if 'eventName' in event_record and event_record['eventName'].startswith('s3:ObjectCreated:'):
                    pytest.fail(
                        f"Found unprocessed ObjectCreated message in queue: "
                        f"{event_record.get('s3', {}).get('object', {}).get('key', 'unknown')}"
                    )


def test_output_file_created():
    """
    Test 7: Verify output file was created with event details
    Purpose: Validates message content was correctly extracted and stored
    """
    # Check that sqs_output.txt exists
    assert os.path.exists(OUTPUT_FILE), f"Output file {OUTPUT_FILE} does not exist"

    # Read file contents
    with open(OUTPUT_FILE, 'r') as f:
        content = f.read()

    # Assert file contains required fields
    assert 'eventName:' in content, "Output file should contain 'eventName:'"
    assert 's3.bucket.name:' in content, "Output file should contain 's3.bucket.name:'"
    assert 's3.object.key:' in content, "Output file should contain 's3.object.key:'"

    # Validate eventName matches pattern s3:ObjectCreated:* and is a valid event type
    event_name_match = re.search(r'eventName:\s*(\S+)', content)
    assert event_name_match, "Could not find eventName value"
    event_name = event_name_match.group(1)

    # Valid S3 ObjectCreated event types (AWS format with s3: prefix)
    valid_event_types_aws = [
        's3:ObjectCreated:Put',
        's3:ObjectCreated:Post',
        's3:ObjectCreated:Copy',
        's3:ObjectCreated:CompleteMultipartUpload'
    ]

    # LocalStack sometimes omits the 's3:' prefix
    valid_event_types_localstack = [
        'ObjectCreated:Put',
        'ObjectCreated:Post',
        'ObjectCreated:Copy',
        'ObjectCreated:CompleteMultipartUpload'
    ]

    valid_event_types = valid_event_types_aws + valid_event_types_localstack

    assert event_name in valid_event_types, \
        f"eventName should be one of {valid_event_types_aws} (or LocalStack format without 's3:' prefix), got '{event_name}'"

    # Validate bucket name
    bucket_match = re.search(r's3\.bucket\.name:\s*(\S+)', content)
    assert bucket_match, "Could not find s3.bucket.name value"
    bucket_name = bucket_match.group(1)
    assert bucket_name == BUCKET_NAME, \
        f"s3.bucket.name should be {BUCKET_NAME}, got {bucket_name}"

    # Validate object key
    key_match = re.search(r's3\.object\.key:\s*(\S+)', content)
    assert key_match, "Could not find s3.object.key value"
    object_key = key_match.group(1)
    assert object_key == 'uploads/sample.csv', \
        f"s3.object.key should be 'uploads/sample.csv', got {object_key}"


def test_end_to_end_notification_with_new_upload(s3_client, sqs_client):
    """
    Test 8: Complete end-to-end validation with a new file upload
    Purpose: Validates that the notification configuration works independently

    This test uploads a new file and verifies a message is received in the queue,
    confirming that the S3-to-SQS notification pipeline is truly functional
    and not just relying on pre-existing messages.
    """
    # Get queue URL
    queue_url = sqs_client.get_queue_url(QueueName=QUEUE_NAME)['QueueUrl']

    # First, purge any existing messages to ensure clean test
    # Note: LocalStack may or may not support purge, so we'll manually drain the queue
    for _ in range(10):  # Try to receive up to 10 messages
        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1
        )
        if 'Messages' not in response:
            break
        for message in response['Messages']:
            sqs_client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message['ReceiptHandle']
            )

    # Upload a new test file with unique name
    test_file_key = 'uploads/test-validation.csv'
    test_content = "header1,header2,header3\nvalue1,value2,value3\n"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=test_file_key,
        Body=test_content
    )
    print(f"Uploaded new test file: {test_file_key}")

    # Wait for notification delivery (async process)
    time.sleep(3)

    # Poll for the message
    max_attempts = 5
    message_received = False

    for attempt in range(max_attempts):
        print(f"Polling for message (attempt {attempt + 1}/{max_attempts})...")

        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5
        )

        if 'Messages' not in response or len(response['Messages']) == 0:
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            else:
                pytest.fail(
                    f"No message received after uploading {test_file_key} "
                    f"to prefix 'uploads/'. This indicates the S3-to-SQS "
                    f"notification is not working correctly."
                )

        message = response['Messages'][0]
        message_body = json.loads(message['Body'])

        # Skip test events
        if isinstance(message_body, dict) and message_body.get('Event') == 's3:TestEvent':
            print("Received test event, skipping...")
            sqs_client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message['ReceiptHandle']
            )
            time.sleep(2)
            continue

        # Validate message structure
        assert 'Records' in message_body, "Message should contain 'Records' array"
        assert len(message_body['Records']) > 0, "Records array should not be empty"

        event_record = message_body['Records'][0]

        # Validate event details
        assert 'eventName' in event_record, "Event record should contain 'eventName'"
        event_name = event_record['eventName']
        # LocalStack may omit 's3:' prefix, so check for both formats
        is_valid_event = (
            event_name.startswith('s3:ObjectCreated:') or
            event_name.startswith('ObjectCreated:')
        )
        assert is_valid_event, \
            f"Expected ObjectCreated event (with or without 's3:' prefix), got {event_name}"

        assert 's3' in event_record, "Event record should contain 's3' field"
        s3_data = event_record['s3']

        assert 'bucket' in s3_data, "S3 data should contain 'bucket'"
        assert s3_data['bucket']['name'] == BUCKET_NAME, \
            f"Expected bucket {BUCKET_NAME}, got {s3_data['bucket']['name']}"

        assert 'object' in s3_data, "S3 data should contain 'object'"
        received_key = s3_data['object']['key']

        # The message should be for our test file
        assert received_key == test_file_key, \
            f"Expected key {test_file_key}, got {received_key}"

        # Clean up the message
        sqs_client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=message['ReceiptHandle']
        )

        message_received = True
        print(f"Successfully received and validated message for {test_file_key}")
        break

    assert message_received, "Failed to receive valid message for the uploaded test file"

    # Clean up the test file
    s3_client.delete_object(Bucket=BUCKET_NAME, Key=test_file_key)
    print(f"Cleaned up test file: {test_file_key}")
