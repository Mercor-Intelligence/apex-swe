import subprocess
#!/usr/bin/env python3
"""Pytest tests for Python dependency checker task."""

import requests
import os
import re
import pytest


def test_script_exists():
    """Test 0: Verify script exists at expected location."""
    script_path = "/app/check_dependencies.py"
    legacy_path = "/app/dependency_checker.py"
    alt_path = "/app/solution.py"
    assert os.path.exists(script_path) or os.path.exists(legacy_path) or os.path.exists(alt_path), \
        f"Required script not found at {script_path}, {legacy_path}, or {alt_path}"


def test_script_runs_successfully():
    """Test 0.5: Verify script executes without errors."""
    script_path = "/app/check_dependencies.py"
    legacy_path = "/app/dependency_checker.py"
    if not os.path.exists(script_path):
        if os.path.exists(legacy_path):
            script_path = legacy_path
        else:
            script_path = "/app/solution.py"
    
    result = subprocess.run(
        ['python3', script_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    assert result.returncode == 0, \
        f"Script failed with exit code {result.returncode}. Stderr: {result.stderr}"




def test_pypi_api_accessible():
    """Test that PyPI API is accessible (prerequisite check)."""
    test_url = "https://pypi.org/pypi/requests/json"

    response = requests.get(test_url, timeout=10)

    assert response.status_code == 200, f"PyPI API returned status {response.status_code}"

    data = response.json()
    version = data['info']['version']
    assert version, "Could not get version from PyPI API"


def test_requirements_file_exists():
    """Test that requirements.txt exists (prerequisite check)."""
    requirements_file = "/app/requirements.txt"

    assert os.path.exists(requirements_file), f"requirements.txt not found at {requirements_file}"

    with open(requirements_file, 'r') as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]

    assert len(lines) > 0, "requirements.txt is empty"


def test_output_file_exists():
    """Test that the output file was created."""
    output_file = "/app/dependency_report.txt"
    assert os.path.exists(output_file), f"Output file not found at {output_file}"


def test_table_format():
    """Test that the output has correct table format."""
    output_file = "/app/dependency_report.txt"

    with open(output_file, 'r') as f:
        lines = f.readlines()

    assert len(lines) >= 2, "Output too short to contain table"

    # Check header
    header = lines[0].strip()
    expected_header = "Package | Current | Latest | Status"

    assert header == expected_header, f"Header incorrect - Expected: '{expected_header}', Got: '{header}'"

    # Check data lines have pipe delimiter
    data_lines = [l.strip() for l in lines[2:] if l.strip()]

    for i, line in enumerate(data_lines, 1):
        assert '|' in line, f"Line {i+2} missing pipe delimiter: '{line}'"

        parts = [p.strip() for p in line.split('|')]
        assert len(parts) == 4, f"Line {i+2} doesn't have 4 columns: '{line}'"


def test_all_packages_checked():
    """Test that all packages in requirements.txt are checked."""
    requirements_file = "/app/requirements.txt"
    output_file = "/app/dependency_report.txt"

    # Count packages in requirements.txt
    with open(requirements_file, 'r') as f:
        req_packages = []
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '==' in line:
                package = line.split('==')[0].strip()
                req_packages.append(package)

    expected_count = len(req_packages)

    # Count packages in output (excluding header and separator)
    with open(output_file, 'r') as f:
        lines = f.readlines()

    # Skip header and separator lines
    data_lines = [l for l in lines[2:] if l.strip()]
    actual_count = len(data_lines)

    assert actual_count == expected_count, \
        f"Package count mismatch - Expected: {expected_count}, Got: {actual_count}"


def test_pypi_queries_work():
    """Test that PyPI queries worked (no ERROR in Latest column)."""
    output_file = "/app/dependency_report.txt"

    with open(output_file, 'r') as f:
        lines = f.readlines()

    # Skip header and separator
    data_lines = [l.strip() for l in lines[2:] if l.strip()]

    errors = []
    for i, line in enumerate(data_lines, 1):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 3:
            latest_version = parts[2]
            if latest_version == "ERROR":
                errors.append((i, line))

    assert not errors, \
        f"{len(errors)} package(s) have ERROR in Latest column: {errors}"


def test_version_comparison():
    """Test that version comparison logic works (Status is Up-to-date or Outdated)."""
    output_file = "/app/dependency_report.txt"

    with open(output_file, 'r') as f:
        lines = f.readlines()

    # Skip header and separator
    data_lines = [l.strip() for l in lines[2:] if l.strip()]

    valid_statuses = ["Up-to-date", "Outdated", "ERROR"]
    invalid = []

    for i, line in enumerate(data_lines, 1):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 4:
            status = parts[3]
            if status not in valid_statuses:
                invalid.append((i, status))

    assert not invalid, \
        f"{len(invalid)} row(s) have invalid status: {invalid}"


def test_latest_version_accuracy():
    """Test that Latest version is actually correct from PyPI for at least one package."""
    output_file = "/app/dependency_report.txt"
    
    with open(output_file, 'r') as f:
        lines = f.readlines()
    
    # Skip header and separator
    data_lines = [l.strip() for l in lines[2:] if l.strip()]
    
    # Check at least one package against PyPI
    verified = False
    for line in data_lines:
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 3:
            package_name = parts[0]
            reported_latest = parts[2]
            
            if reported_latest == "ERROR":
                continue
            
            try:
                # Query PyPI for actual latest version
                response = requests.get(f"https://pypi.org/pypi/{package_name}/json", timeout=10)
                if response.status_code == 200:
                    actual_latest = response.json()['info']['version']
                    assert reported_latest == actual_latest, \
                        f"Latest version mismatch for {package_name}: reported '{reported_latest}' but PyPI has '{actual_latest}'"
                    verified = True
                    break
            except Exception:
                continue
    
    assert verified, "Could not verify any package version against PyPI"


def test_status_correctness():
    """Test that Status correctly reflects version comparison."""
    output_file = "/app/dependency_report.txt"
    
    with open(output_file, 'r') as f:
        lines = f.readlines()
    
    # Skip header and separator
    data_lines = [l.strip() for l in lines[2:] if l.strip()]
    
    for line in data_lines:
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 4:
            current = parts[1]
            latest = parts[2]
            status = parts[3]
            
            if latest == "ERROR" or status == "ERROR":
                continue
            
            # Verify status matches version comparison
            if current == latest:
                assert status == "Up-to-date", \
                    f"Status should be 'Up-to-date' when current ({current}) == latest ({latest})"
            else:
                assert status == "Outdated", \
                    f"Status should be 'Outdated' when current ({current}) != latest ({latest})"
