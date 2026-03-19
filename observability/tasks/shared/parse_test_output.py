#!/usr/bin/env python3
"""
Standalone test output parser for use inside Docker containers.

This script parses test output from various frameworks and writes results
to a file in a compact format that avoids stdout truncation issues.

Usage:
    python3 parse_test_output.py <input_file> <output_file>

Output format (written to output_file):
    PARSED_TESTS
    COUNTS:<passed>,<failed>,<skipped>
    P|test_name_1
    P|test_name_2
    F|failed_test
    S|skipped_test

If parsing fails, outputs:
    RAW_OUTPUT
    <original content>
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from typing import List, Tuple


def parse_go_json(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Go test -json output (newline-delimited JSON)."""
    passed, failed, skipped = [], [], []
    lines = content.strip().split("\n")
    go_json_lines = 0
    
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if "Action" in obj:
                go_json_lines += 1
                test_name = obj.get("Test", "")
                package = obj.get("Package", "")
                if obj.get("Action") == "pass" and test_name:
                    test_id = f"{package}::{test_name}" if package else test_name
                    passed.append(test_id)
                elif obj.get("Action") == "fail" and test_name:
                    test_id = f"{package}::{test_name}" if package else test_name
                    failed.append(test_id)
                elif obj.get("Action") == "skip" and test_name:
                    test_id = f"{package}::{test_name}" if package else test_name
                    skipped.append(test_id)
        except json.JSONDecodeError:
            pass
    
    # Consider it parsed if we found any test results OR at least 2 Go JSON lines
    # (2 lines because run+pass/fail is minimum for a single test)
    parsed = bool(passed or failed or skipped) or go_json_lines >= 2
    return passed, failed, skipped, parsed


def parse_go_verbose(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Go test -v output (verbose text format)."""
    passed, failed, skipped = [], [], []
    
    # Extract package name from ok/FAIL lines
    package = ""
    package_pattern = re.compile(r"^(ok|FAIL)\s+(\S+)\s+", re.MULTILINE)
    for match in package_pattern.finditer(content):
        package = match.group(2)
    
    # Parse individual test results
    go_verbose = re.compile(r"^---\s+(PASS|FAIL|SKIP):\s+(\S+)", re.MULTILINE)
    go_matches = go_verbose.findall(content)
    
    for status, test_name in go_matches:
        test_id = f"{package}::{test_name}" if package else test_name
        if status == "PASS":
            passed.append(test_id)
        elif status == "FAIL":
            failed.append(test_id)
        elif status == "SKIP":
            skipped.append(test_id)
    
    parsed = bool(passed or failed or skipped)
    return passed, failed, skipped, parsed


def parse_pytest(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse pytest verbose text output."""
    passed, failed, skipped = [], [], []
    
    pytest_pattern = re.compile(r"^(.+::.+?)\s+(PASSED|FAILED|SKIPPED|ERROR)", re.MULTILINE)
    pytest_matches = pytest_pattern.findall(content)
    
    for test_name, status in pytest_matches:
        test_name = test_name.strip()
        if status == "PASSED":
            passed.append(test_name)
        elif status in ("FAILED", "ERROR"):
            failed.append(test_name)
        elif status == "SKIPPED":
            skipped.append(test_name)
    
    parsed = bool(passed or failed or skipped)
    return passed, failed, skipped, parsed


def parse_gtest(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Google Test output."""
    gtest_ok = re.compile(r"\[\s*OK\s*\]\s+(\S+)")
    gtest_fail = re.compile(r"\[\s*FAILED\s*\]\s+(\S+)")
    gtest_skip = re.compile(r"\[\s*SKIPPED\s*\]\s+(\S+)")
    
    passed = gtest_ok.findall(content)
    failed = gtest_fail.findall(content)
    skipped = gtest_skip.findall(content)
    
    parsed = bool(passed or failed)
    return passed, failed, skipped, parsed


def parse_gradle(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Gradle test output."""
    passed, failed, skipped = [], [], []
    
    gradle_pattern = re.compile(r"^\s*(\S+)\s+>\s+(\S+)\s+(PASSED|FAILED|SKIPPED)", re.MULTILINE)
    gradle_matches = gradle_pattern.findall(content)
    
    for test_class, test_method, status in gradle_matches:
        test_name = f"{test_class}::{test_method}"
        if status == "PASSED":
            passed.append(test_name)
        elif status == "FAILED":
            failed.append(test_name)
        elif status == "SKIPPED":
            skipped.append(test_name)
    
    parsed = bool(passed or failed or skipped)
    return passed, failed, skipped, parsed


def parse_junit_xml(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse JUnit XML format.
    
    Handles multiple XML documents in the content (e.g., multiple TEST-*.xml files
    concatenated together from Gradle/Maven test reports).
    """
    passed, failed, skipped = [], [], []
    
    if "<?xml" not in content or "<testcase" not in content:
        return passed, failed, skipped, False
    
    # Find all XML documents in the content
    # Each JUnit XML file starts with <?xml and ends with </testsuite> or </testsuites>
    search_start = 0
    while True:
        xml_start = content.find("<?xml", search_start)
        if xml_start == -1:
            break
        
        # Find the end of this XML document
        xml_end = -1
        
        # First try </testsuites> (wrapper element)
        testsuites_end = content.find("</testsuites>", xml_start)
        if testsuites_end != -1:
            xml_end = testsuites_end + len("</testsuites>")
        
        # If no </testsuites>, try </testsuite> (single suite)
        if xml_end == -1:
            testsuite_end = content.find("</testsuite>", xml_start)
            if testsuite_end != -1:
                xml_end = testsuite_end + len("</testsuite>")
        
        if xml_end == -1 or xml_end <= xml_start:
            search_start = xml_start + 1
            continue
        
        # Parse this XML document
        try:
            tree = ET.fromstring(content[xml_start:xml_end])
            for tc in tree.iter("testcase"):
                classname = tc.get("classname", "")
                name = tc.get("name", "")
                test_id = f"{classname}::{name}" if classname else name
                
                # Skip empty test IDs
                if not test_id or test_id == "::":
                    continue
                    
                if tc.find("failure") is not None or tc.find("error") is not None:
                    if test_id not in failed:
                        failed.append(test_id)
                elif tc.find("skipped") is not None:
                    if test_id not in skipped:
                        skipped.append(test_id)
                else:
                    if test_id not in passed:
                        passed.append(test_id)
        except ET.ParseError:
            pass  # Skip malformed XML, try next document
        
        search_start = xml_end
    
    parsed = bool(passed or failed or skipped)
    return passed, failed, skipped, parsed


def parse_jest_vitest_json(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Jest/Vitest/Mocha JSON output."""
    passed, failed, skipped = [], [], []
    
    json_start = content.find("{")
    if json_start == -1:
        return passed, failed, skipped, False
    
    # Find matching closing brace
    brace_count = 0
    json_end = json_start
    for i, c in enumerate(content[json_start:]):
        if c == "{":
            brace_count += 1
        elif c == "}":
            brace_count -= 1
            if brace_count == 0:
                json_end = json_start + i + 1
                break
    
    try:
        data = json.loads(content[json_start:json_end])
        
        # Jest/Vitest format with testResults
        if "testResults" in data:
            for suite in data.get("testResults", []):
                file_path = suite.get("name", "")
                for test in suite.get("assertionResults", []):
                    name = test.get("fullName") or test.get("title", "")
                    test_id = f"{file_path}::{name}" if name else ""
                    status = test.get("status", "")
                    if status == "passed":
                        passed.append(test_id)
                    elif status == "failed":
                        failed.append(test_id)
                    elif status in ("pending", "skipped"):
                        skipped.append(test_id)
            parsed = bool(passed or failed or skipped)
            return passed, failed, skipped, parsed
        
        # Mocha JSON format with passes/failures arrays
        if "passes" in data or "failures" in data:
            passed = [t.get("fullTitle", "") for t in data.get("passes", []) if t.get("fullTitle")]
            failed = [t.get("fullTitle", "") for t in data.get("failures", []) if t.get("fullTitle")]
            skipped = [t.get("fullTitle", "") for t in data.get("pending", []) if t.get("fullTitle")]
            parsed = bool(passed or failed or skipped)
            return passed, failed, skipped, parsed
        
        # Mocha JSON format with tests array
        if "tests" in data:
            for test in data.get("tests", []):
                title = test.get("fullTitle", test.get("title", ""))
                if not title:
                    continue
                state = test.get("state", "")
                if state == "passed":
                    passed.append(title)
                elif state == "failed":
                    failed.append(title)
                elif state == "pending":
                    skipped.append(title)
            parsed = bool(passed or failed or skipped)
            return passed, failed, skipped, parsed
            
    except json.JSONDecodeError:
        pass
    
    return passed, failed, skipped, False


def parse_jest_vitest_text(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Jest/Vitest/Mocha text output with checkmarks."""
    passed, failed, skipped = [], [], []
    
    # Pattern: ✓ test name or ✔ test name
    passed_pattern = re.compile(r"^\s*[✓✔]\s+(.+?)\s*(?:\(\d+.*?\))?$", re.MULTILINE)
    failed_pattern = re.compile(r"^\s*[✕✗×]\s+(.+?)\s*(?:\(\d+.*?\))?$", re.MULTILINE)
    skipped_pattern = re.compile(r"^\s*[○⊘-]\s+(.+?)\s*(?:\(\d+.*?\))?$", re.MULTILINE)
    
    for match in passed_pattern.finditer(content):
        passed.append(match.group(1).strip())
    
    for match in failed_pattern.finditer(content):
        failed.append(match.group(1).strip())
    
    for match in skipped_pattern.finditer(content):
        skipped.append(match.group(1).strip())
    
    parsed = bool(passed or failed or skipped)
    return passed, failed, skipped, parsed


def parse_bespoke(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse bespoke/custom test output using generic success/failure detection.
    
    Note: validation_code_snippet execution happens in the host-side parser,
    not here. This is a fallback for generic patterns.
    """
    passed, failed, skipped = [], [], []
    content_lower = content.lower()
    
    # Check for common success indicators
    success_indicators = [
        "tests passed", "all tests passed", "test passed",
        "tests summary: ok", "build succeeded", "build successful",
        "ok (", "passed!", "success"
    ]
    
    failure_indicators = [
        "tests failed", "test failed", "failed!", "failure",
        "tests summary: fail", "build failed", "error:",
        "assertion error", "assertionerror"
    ]
    
    has_success = any(ind in content_lower for ind in success_indicators)
    has_failure = any(ind in content_lower for ind in failure_indicators)
    
    # Look for numeric test summaries
    # Pattern: "X passed" or "X tests passed"
    passed_count_match = re.search(r"(\d+)\s+(?:tests?\s+)?passed", content_lower)
    failed_count_match = re.search(r"(\d+)\s+(?:tests?\s+)?failed", content_lower)
    
    if passed_count_match:
        count = int(passed_count_match.group(1))
        for i in range(count):
            passed.append(f"bespoke::test_{i+1}")
    
    if failed_count_match:
        count = int(failed_count_match.group(1))
        for i in range(count):
            failed.append(f"bespoke::failed_test_{i+1}")
    
    # If no numeric counts, use indicator-based detection
    if not passed and not failed:
        if has_failure:
            failed.append("bespoke::tests")
        elif has_success:
            passed.append("bespoke::tests")
    
    parsed = bool(passed or failed)
    return passed, failed, skipped, parsed


def parse_mocha_json(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """Parse Mocha's specific JSON format ({"stats":..., "tests":...})."""
    passed, failed, skipped = [], [], []
    
    json_start = content.find('{"stats"')
    if json_start == -1:
        return passed, failed, skipped, False
    
    try:
        # Find matching closing brace
        brace_count = 0
        json_end = json_start
        for i, c in enumerate(content[json_start:]):
            if c == "{":
                brace_count += 1
            elif c == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_end = json_start + i + 1
                    break
        
        data = json.loads(content[json_start:json_end])
        
        if "tests" in data:
            for test in data.get("tests", []):
                title = test.get("fullTitle", test.get("title", ""))
                if not title:
                    continue
                state = test.get("state", "")
                if state == "passed":
                    passed.append(title)
                elif state == "failed":
                    failed.append(title)
                elif state == "pending":
                    skipped.append(title)
            
            parsed = bool(passed or failed or skipped)
            return passed, failed, skipped, parsed
    except json.JSONDecodeError:
        pass
    
    return passed, failed, skipped, False


def parse_test_output(content: str) -> Tuple[List[str], List[str], List[str], bool]:
    """
    Parse test output trying multiple formats in order of likelihood.
    
    Supports frameworks:
    - Go (JSON and verbose text)
    - pytest (text and JUnit XML)
    - Jest/Vitest (JSON and text)
    - Mocha (JSON and text)
    - JUnit XML
    - Gradle
    - Google Test (gtest)
    - Bespoke (generic detection)
    
    Returns:
        Tuple of (passed_tests, failed_tests, skipped_tests, successfully_parsed)
    """
    # Strip debug headers added by test_scorer if present
    # These headers help with debugging but shouldn't affect parsing
    if "=== START OUTPUT ===" in content:
        parts = content.split("=== START OUTPUT ===", 1)
        if len(parts) > 1:
            content = parts[1]
    
    # Try each parser in order of specificity/likelihood
    parsers = [
        # Go formats (very distinctive)
        ("go_json", parse_go_json),
        ("go_verbose", parse_go_verbose),
        # pytest (common, distinctive pattern)
        ("pytest", parse_pytest),
        # gtest (distinctive brackets)
        ("gtest", parse_gtest),
        # Gradle (distinctive ">" pattern)
        ("gradle", parse_gradle),
        # JUnit XML (structured)
        ("junit_xml", parse_junit_xml),
        # Mocha specific JSON format
        ("mocha_json", parse_mocha_json),
        # Jest/Vitest JSON (common)
        ("jest_vitest_json", parse_jest_vitest_json),
        # Jest/Vitest/Mocha text with checkmarks
        ("jest_vitest_text", parse_jest_vitest_text),
        # Bespoke fallback (generic detection - try last)
        ("bespoke", parse_bespoke),
    ]
    
    for name, parser in parsers:
        try:
            passed, failed, skipped, parsed = parser(content)
            if parsed:
                return passed, failed, skipped, True
        except Exception:
            continue
    
    return [], [], [], False


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 parse_test_output.py <input_file> <output_file>", file=sys.stderr)
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    try:
        with open(input_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(f"ERROR:Failed to read input file: {e}", file=sys.stderr)
        sys.exit(1)
    
    passed, failed, skipped, parsed = parse_test_output(content)
    
    # KEY FIX: If we parsed but found 0 tests, treat as raw output
    # This preserves the original content for debugging
    has_tests = bool(passed or failed or skipped)
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            if parsed and has_tests:
                # Successfully parsed with actual test results
                f.write("PARSED_TESTS\n")
                f.write(f"COUNTS:{len(passed)},{len(failed)},{len(skipped)}\n")
                for t in passed:
                    f.write(f"P|{t}\n")
                for t in failed:
                    f.write(f"F|{t}\n")
                for t in skipped:
                    f.write(f"S|{t}\n")
                print(f"PARSED_FILE:{output_file}")
                print(f"COUNTS:{len(passed)},{len(failed)},{len(skipped)}")
            else:
                # Parsing failed or no tests found - preserve raw output for debugging
                f.write("RAW_OUTPUT\n")
                f.write(content)
                print(f"RAW_FILE:{output_file}")
    except Exception as e:
        print(f"ERROR:Failed to write output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
