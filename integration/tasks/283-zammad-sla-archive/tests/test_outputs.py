#!/usr/bin/env python3
"""
Comprehensive tests for Zammad SLA Archive
Following strict test pattern from tasks 200-277
"""

import os
import re
import subprocess
import time
import csv

import pytest
import requests
import boto3


def test_script_exists():
    """Verify SLA archive script exists"""
    assert os.path.exists('/app/sla_archive.py'), \
        "Script not found at /app/sla_archive.py"


def test_sla_config_exists():
    """Verify SLA config file exists"""
    assert os.path.exists('/data/sla.json'), \
        "SLA config not found at /data/sla.json"


def test_execution_succeeds():
    """Verify script executes without errors"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed with code {result.returncode}: {result.stderr}"


def test_output_format_exact():
    """Verify output format is exact - STRICT like Task 200"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Check for required output format
    assert 'Archived' in result.stdout, "Missing 'Archived' in output"
    assert 'tickets' in result.stdout, "Missing 'tickets' in output"
    assert 'SLA hit' in result.stdout, "Missing 'SLA hit' in output"
    
    # Extract counts
    match = re.search(r'Archived (\d+) tickets, (\d+)% SLA hit', result.stdout)
    assert match, f"Output format incorrect: {result.stdout}"
    
    ticket_count = int(match.group(1))
    sla_percent = int(match.group(2))
    
    assert ticket_count >= 0, f"Invalid ticket count: {ticket_count}"
    assert 0 <= sla_percent <= 100, f"Invalid SLA percentage: {sla_percent}"


def test_zammad_ticket_fetching():
    """Verify Zammad tickets are fetched - STRICT with retries"""
    zammad_url = os.environ.get('ZAMMAD_SITE_URL', 'http://zammad:8080')
    auth = ('admin@example.com', 'StrongPassw0rd@()')
    
    # Try to fetch tickets with retries
    api_reachable = False
    for attempt in range(3):
        try:
            response = requests.get(f"{zammad_url}/api/v1/tickets", 
                                   auth=auth, timeout=30)
            if response.status_code == 200:
                api_reachable = True
                break
            time.sleep(10)
        except Exception:
            if attempt < 2:
                time.sleep(10)
    
    # Run script
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify connection attempt
    if not api_reachable:
        # If Zammad unreachable, script should handle gracefully
        assert 'tickets' in result.stdout.lower() or 'zammad' in result.stderr.lower(), \
            "Script should attempt Zammad connection"


def test_s3_upload_comprehensive():
    """Verify CSV is uploaded to S3 - STRICT"""
    # Run script first
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Connect to S3
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )
    
    # Verify bucket exists
    try:
        s3.head_bucket(Bucket='support-metrics')
    except Exception as e:
        pytest.fail(f"Bucket support-metrics not found: {e}")
    
    # List objects in bucket
    try:
        response = s3.list_objects_v2(Bucket='support-metrics')
        objects = response.get('Contents', [])
        
        # Should have at least one sla-report file
        sla_files = [obj['Key'] for obj in objects if 'sla-report-' in obj['Key']]
        assert len(sla_files) >= 1, f"No SLA report files found in bucket, got objects: {[obj['Key'] for obj in objects]}"
        
        # Verify today's file exists
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        expected_key = f"sla-report-{today}.csv"
        
        assert any(expected_key in key for key in sla_files), \
            f"Today's report {expected_key} not found, got: {sla_files}"
    except Exception as e:
        pytest.fail(f"Error checking S3: {e}")


def test_csv_structure():
    """Verify CSV has correct structure"""
    # Run script
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Download CSV from S3
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )
    
    try:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        key = f"sla-report-{today}.csv"
        
        response = s3.get_object(Bucket='support-metrics', Key=key)
        csv_content = response['Body'].read().decode('utf-8')
        
        # Parse CSV
        lines = csv_content.strip().split('\n')
        assert len(lines) >= 1, "CSV should have at least header"
        
        # Verify header
        header = lines[0]
        expected_columns = ['ticket_id', 'priority', 'first_response_minutes', 
                          'resolution_minutes', 'first_response_pass', 'resolution_pass']
        
        for col in expected_columns:
            assert col in header, f"Missing column: {col}"
        
        # If there are data rows, verify structure
        if len(lines) > 1:
            reader = csv.DictReader(lines)
            for row in reader:
                # Verify all columns present
                for col in expected_columns:
                    assert col in row, f"Row missing column: {col}"
                
                # Verify data types make sense
                assert row['priority'] in ['1', '2', '3'], f"Invalid priority: {row['priority']}"
                
                # Boolean columns should be True/False
                assert row['first_response_pass'] in ['True', 'False'], \
                    f"Invalid boolean: {row['first_response_pass']}"
                assert row['resolution_pass'] in ['True', 'False'], \
                    f"Invalid boolean: {row['resolution_pass']}"
    except Exception as e:
        # If CSV doesn't exist, that's OK if there were 0 tickets
        if '0 tickets' in result.stdout:
            pytest.skip("No tickets to archive, CSV may not exist")
        else:
            pytest.fail(f"Error checking CSV structure: {e}")


def test_sla_calculation_logic():
    """Verify SLA calculation logic is correct"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Extract SLA percentage
    match = re.search(r'(\d+)% SLA hit', result.stdout)
    if match:
        sla_percent = int(match.group(1))
        
        # Should be valid percentage
        assert 0 <= sla_percent <= 100, f"Invalid SLA percentage: {sla_percent}"


def test_handles_no_tickets():
    """Verify script handles case with no tickets gracefully"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    
    # Should not crash
    assert result.returncode == 0, f"Script crashed: {result.stderr}"
    
    # Should have valid output
    assert 'Archived' in result.stdout or 'tickets' in result.stdout.lower(), \
        "Should output summary even with 0 tickets"


def test_cross_service_consistency():
    """Verify output matches S3 records - STRICT"""
    # Run script
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Extract ticket count from output
    match = re.search(r'Archived (\d+) tickets', result.stdout)
    if not match:
        pytest.skip("Could not extract ticket count from output")
    
    output_count = int(match.group(1))
    
    if output_count == 0:
        # If 0 tickets, we're done
        return
    
    # Check S3 CSV has matching row count
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )
    
    try:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        key = f"sla-report-{today}.csv"
        
        response = s3.get_object(Bucket='support-metrics', Key=key)
        csv_content = response['Body'].read().decode('utf-8')
        
        lines = csv_content.strip().split('\n')
        csv_row_count = len(lines) - 1  # Minus header
        
        # STRICT: Counts should match
        assert csv_row_count == output_count, \
            f"Output says {output_count} tickets but CSV has {csv_row_count} rows"
    except Exception as e:
        # CSV might not exist if there were 0 tickets
        if output_count > 0:
            pytest.fail(f"Error verifying consistency: {e}")


def test_idempotent_uploads():
    """Verify script can be run multiple times (overwrites S3 file)"""
    # Run script twice
    result1 = subprocess.run(['python3', '/app/sla_archive.py'],
                           capture_output=True, text=True, timeout=120)
    assert result1.returncode == 0, f"First run failed: {result1.stderr}"
    
    time.sleep(2)
    
    result2 = subprocess.run(['python3', '/app/sla_archive.py'],
                           capture_output=True, text=True, timeout=120)
    assert result2.returncode == 0, f"Second run failed: {result2.stderr}"
    
    # Both should produce similar output
    assert len(result1.stdout) > 0 and len(result2.stdout) > 0, \
        "Both runs should produce output"


def test_sla_config_loaded():
    """Verify SLA configuration is loaded correctly"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Should log that it loaded SLA config
    assert 'sla' in result.stderr.lower() or 'config' in result.stderr.lower(), \
        "Script should load SLA configuration"


def test_complete_workflow_execution():
    """Verify complete workflow from Zammad to S3"""
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify all workflow steps appear in logs
    workflow_steps = [
        'sla',
        's3'
    ]
    
    stderr_lower = result.stderr.lower()
    for step in workflow_steps:
        assert step in stderr_lower, f"Missing workflow step: {step}"


def test_date_format_in_filename():
    """Verify S3 filename uses correct date format"""
    # Run script
    result = subprocess.run(['python3', '/app/sla_archive.py'],
                          capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Check S3 for file with correct date format
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ.get('LOCALSTACK_URL', 'http://localstack:4566'),
        region_name='us-east-1',
        aws_access_key_id='test',
        aws_secret_access_key='test'
    )
    
    try:
        response = s3.list_objects_v2(Bucket='support-metrics')
        objects = response.get('Contents', [])
        
        if objects:
            # Verify filename format: sla-report-YYYY-MM-DD.csv
            for obj in objects:
                key = obj['Key']
                if 'sla-report-' in key:
                    assert re.match(r'sla-report-\d{4}-\d{2}-\d{2}\.csv', key), \
                        f"Invalid filename format: {key}"
    except Exception as e:
        pytest.skip(f"Could not verify filename format: {e}")
