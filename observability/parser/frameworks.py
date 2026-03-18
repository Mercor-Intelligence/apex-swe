#!/usr/bin/env python3
"""
Test framework output configuration mapping.

This module provides configuration for various test frameworks, including:
- Output flags for structured test results (JSON, XML)
- Result file locations for each framework
"""

from typing import TypedDict


class FrameworkConfig(TypedDict, total=False):
    """Type definition for framework configuration."""

    output_flag: str | None
    result_file: str | None


# Standard results directory inside container (consistent path)
RESULTS_DIR = "/workspace/test-results"

FRAMEWORK_CONFIGS: dict[str, FrameworkConfig] = {
    "pytest": {
        "output_flag": f"--junitxml={RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "unittest": {
        "output_flag": f"--junitxml={RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "go": {
        "output_flag": "-json",
        "result_file": None,  # JSON goes to stdout, captured via tee
    },
    "jest": {
        "output_flag": f"--json --outputFile={RESULTS_DIR}/output.json",
        "result_file": f"{RESULTS_DIR}/output.json",
    },
    "vitest": {
        "output_flag": f"--reporter=json --outputFile={RESULTS_DIR}/output.json",
        "result_file": f"{RESULTS_DIR}/output.json",
    },
    "mocha": {
        "output_flag": f"--reporter json --reporter-options output={RESULTS_DIR}/output.json",
        "result_file": f"{RESULTS_DIR}/output.json",
    },
    "bun": {
        "output_flag": None,  # Bun doesn't have structured JSON output flag by default
        "result_file": None,  # Parse from stdout
    },
    "junit": {
        "output_flag": None,  # Maven/Gradle generate files automatically
        "result_file": "/app/repo/target/surefire-reports/TEST-*.xml",
    },
    "maven": {
        "output_flag": None,  # Maven generates files automatically
        "result_file": "/app/repo/target/surefire-reports/TEST-*.xml",
    },
    "gtest": {
        "output_flag": f"--gtest_output=json:{RESULTS_DIR}/output.json",
        "result_file": f"{RESULTS_DIR}/output.json",
    },
    "cargo-nextest": {
        "output_flag": None,  # Profile is already in test_command
        "result_file": None,  # JUnit XML is output to repo/junit.xml by profile config
    },
    "ctest": {
        "output_flag": f"--output-on-failure --output-junit {RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "xctest": {
        # For SwiftPM with XCTest framework
        "output_flag": f"--parallel --num-workers=1 --xunit-output {RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "testing": {
        # For SwiftPM with new Swift Testing framework (Swift 6+)
        "output_flag": f"--disable-xctest --parallel --xunit-output {RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "cppunit": {
        "output_flag": None,
        "result_file": None,
    },
    # Lua test frameworks - Tier 1 (Standard XML output)
    "busted": {
        "output_flag": f"--output=junit -o {RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    "luaunit": {
        "output_flag": f"-o junit -n {RESULTS_DIR}/output.xml",
        "result_file": f"{RESULTS_DIR}/output.xml",
    },
    # Lua test frameworks - Tier 2 (Custom parsers)
    "telescope": {
        "output_flag": None,
        "result_file": None,
    },
    "lust": {
        "output_flag": None,
        "result_file": None,
    },
    "minitest": {
        "output_flag": None,
        "result_file": None,
    },
    "bespoke_libgeos": {
        "output_flag": None,
        "result_file": None,
    },
    # Alias for bespoke_libgeos
    "bespoke": {
        "output_flag": None,
        "result_file": None,
    },
}


def is_shell_script_command(command: str) -> bool:
    """
    Check if command is a shell script that likely won't pass through our output flags.

    Shell scripts typically have their own hardcoded test invocations and ignore
    additional CLI arguments we append.

    Args:
        command: The test command to check

    Returns:
        True if the command appears to be a shell script invocation
    """
    cmd = command.strip().split()[0] if command.strip() else ""

    # Direct shell script invocations
    if cmd.startswith("./") or cmd.startswith("/"):
        return cmd.endswith(".sh")

    # Commands that invoke scripts
    if cmd in ("bash", "sh", "zsh"):
        return True

    # npm/yarn run scripts (these run package.json scripts that may not pass args)
    if (
        "npm run" in command
        or "npm test" in command
        or "yarn run" in command
        or "yarn test" in command
    ):
        # Check if it's a known test framework invocation that passes args through
        if "npm test" in command or "yarn test" in command:
            return False  # Standard test scripts usually pass args
        # yarn run jest / npm run jest / etc pass args to the test framework
        for known_framework in ("jest", "vitest", "mocha", "ava", "tap", "tape"):
            if f"run {known_framework}" in command or f"run {known_framework} " in command:
                return False  # Known test frameworks pass args
        return True  # Custom scripts might not

    return False


def get_framework_config(framework: str, test_command: str = "") -> FrameworkConfig:
    """Get configuration for a test framework.

    Args:
        framework: Test framework name
        test_command: The test command (optional, used to detect Gradle vs Maven)
    """
    default_config: FrameworkConfig = {
        "output_flag": None,
        "result_file": None,
    }
    config = FRAMEWORK_CONFIGS.get(framework, default_config)

    # Special handling for JUnit: detect Gradle vs Maven from command
    if framework == "junit" and test_command:
        if "gradlew" in test_command or "gradle " in test_command:
            # Gradle uses different output location than Maven
            # Different Gradle versions and configs put results in different places:
            # - Old Gradle: /app/repo/build/test-results/TEST-*.xml (directly in test-results)
            # - New Gradle: /app/repo/build/test-results/test/TEST-*.xml (in test/ subdir)
            # - Multi-module: /app/repo/*/build/test-results/*/TEST-*.xml
            # Use space-separated globs to match all locations
            config = FrameworkConfig(
                output_flag=None,
                result_file="/app/repo/build/test-results/TEST-*.xml /app/repo/build/test-results/*/TEST-*.xml /app/repo/*/build/test-results/*/TEST-*.xml",
            )

    # Special handling for xctest: detect Swift Testing vs XCTest from command
    # When --disable-xctest is used, the task is using Swift Testing, not XCTest
    # Use the 'testing' framework config to avoid adding XCTest-only flags like --num-workers
    if framework == "xctest" and test_command:
        if "--disable-xctest" in test_command:
            config = FRAMEWORK_CONFIGS.get("testing", config)

    return config


def get_test_command_with_output(base_command: str, framework: str) -> str:
    """
    Add structured output flags to test command.

    Skips adding flags for shell scripts that won't pass them through.

    Returns: command_with_output_flags
    """
    config = get_framework_config(framework, base_command)
    output_flag = config.get("output_flag")

    # Don't add output flags to shell scripts - they won't pass them through
    # and the parser will need to rely on console output
    if output_flag and is_shell_script_command(base_command):
        return base_command

    enhanced = f"{base_command} {output_flag}" if output_flag else base_command

    return enhanced
