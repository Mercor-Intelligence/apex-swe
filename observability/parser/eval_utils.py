"""
Evaluation utilities for SWE-bench-ext tasks.

This module provides standalone functions for:
- Loading task instance data from a task directory
- Generating grading setup scripts (test patch application, file resets)
- Generating test run scripts
- Parsing test output and computing results

These functions are designed to be sandbox-agnostic - they generate scripts
and parse outputs without depending on any specific execution environment.

Note: This module intentionally does NOT import from eval_runner to maintain
independence. The parser module can be used standalone without the eval_runner.
"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

from .frameworks import get_framework_config, get_test_command_with_output
from .parsing_utils import parse_test_output, normalize_test_id

# Constants for output limits
MAX_FAILED_TESTS_TO_SHOW = 10
MAX_PARSED_TESTS_TO_SHOW = 100
DEFAULT_MAX_OUTPUT_LENGTH = 100_000

# Default container paths (mirrors eval_runner.config.CONTAINER_CONFIG)
_DEFAULT_WORKDIR = "/app/repo"
_GIT_USER_EMAIL = "eval@apexcode.local"  # For grading scripts
_GIT_USER_NAME = "Eval Runner"


@dataclass
class TaskInstance:
    """Container for all task-related data loaded from a task directory."""

    task_id: str
    test_framework: str
    test_command: str
    language: str
    test_files: list[str]
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    test_patch: str
    golden_patch: str
    problem_statement: str
    prompt_statement: str
    requirements: list[str] = field(default_factory=list)
    interface: str = ""
    knowledge_base: str | None = None
    base_commit: str | None = None

    @property
    def result_file(self) -> str | None:
        """Get the result file path for this framework, if applicable."""
        config = get_framework_config(self.test_framework, self.test_command)
        return config.get("result_file")

    @property
    def output_flag(self) -> str | None:
        """Get the output flag for this framework, if applicable."""
        config = get_framework_config(self.test_framework, self.test_command)
        return config.get("output_flag")


@dataclass
class TestResults:
    """Container for parsed test results and computed scores."""

    score: float
    passed: bool
    fail_to_pass_results: dict[str, str]
    pass_to_pass_results: dict[str, str]
    parsed_results: dict[str, str]

    # Computed stats
    f2p_passed: int = 0
    f2p_total: int = 0
    p2p_passed: int = 0
    p2p_total: int = 0

    failed_f2p: list[str] = field(default_factory=list)
    failed_p2p: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Compute derived statistics."""
        self.f2p_total = len(self.fail_to_pass_results)
        self.p2p_total = len(self.pass_to_pass_results)
        self.f2p_passed = sum(
            1 for v in self.fail_to_pass_results.values() if v == "PASSED"
        )
        self.p2p_passed = sum(
            1 for v in self.pass_to_pass_results.values() if v == "PASSED"
        )
        self.failed_f2p = [
            t for t, v in self.fail_to_pass_results.items() if v != "PASSED"
        ]
        self.failed_p2p = [
            t for t, v in self.pass_to_pass_results.items() if v != "PASSED"
        ]


def load_task_yaml(task_dir: Path | str) -> dict:
    """
    Load task.yaml from a task directory.

    This is a shared helper for loading task configuration that's used by
    both parser.TaskConfig and eval_runner.EvalTaskConfig.

    Args:
        task_dir: Path to the task directory

    Returns:
        Dict with task.yaml contents, or empty dict if file doesn't exist
    """
    import yaml

    task_dir = Path(task_dir)
    task_yaml_path = task_dir / "task.yaml"

    if not task_yaml_path.exists():
        return {}

    try:
        return yaml.safe_load(task_yaml_path.read_text()) or {}
    except Exception:
        return {}


def load_task_instance(task_dir: Path | str) -> TaskInstance:
    """
    Load all task data from a task directory into a TaskInstance object.

    Args:
        task_dir: Path to the task directory (e.g., tasks/arduino-arduino-cli-2927-2940)

    Returns:
        TaskInstance containing all loaded task data

    Raises:
        FileNotFoundError: If required files are missing
        json.JSONDecodeError: If JSON files are malformed
    """
    task_dir = Path(task_dir)
    task_id = task_dir.name

    # Load required files
    test_metadata = json.loads((task_dir / "test_metadata.json").read_text())
    test_patch = (task_dir / "test.patch").read_text()
    golden_patch = (task_dir / "golden.patch").read_text()
    problem_statement = (task_dir / "problem_statement.md").read_text()
    prompt_statement = (task_dir / "prompt_statement.md").read_text()

    # Load optional files
    requirements = []
    requirements_file = task_dir / "requirements.json"
    if requirements_file.exists():
        try:
            requirements = json.loads(requirements_file.read_text())
        except json.JSONDecodeError:
            requirements = []

    # Load optional knowledge_base.md file
    knowledge_base = None
    knowledge_base_file = task_dir / "knowledge_base.md"
    if knowledge_base_file.exists():
        knowledge_base = knowledge_base_file.read_text()

    return TaskInstance(
        task_id=task_id,
        test_framework=test_metadata.get(
            "test_framework", test_metadata.get("language", "")
        ),
        test_command=test_metadata["test_command"],
        language=test_metadata["language"],
        test_files=test_metadata.get("test_files", []),
        fail_to_pass=test_metadata.get("FAIL_TO_PASS", []),
        pass_to_pass=test_metadata.get("PASS_TO_PASS", []),
        test_patch=test_patch,
        golden_patch=golden_patch,
        problem_statement=problem_statement,
        prompt_statement=prompt_statement,
        requirements=requirements,
        interface="",
        knowledge_base=knowledge_base,
        base_commit=test_metadata.get("base_commit"),
    )


def _generate_base64_patch_apply_script(patch_content: str, patch_name: str = "test") -> str:
    """
    Generate a bash script snippet that applies a patch using base64 encoding.

    This avoids issues with special characters in the patch content.

    Args:
        patch_content: The patch content to apply
        patch_name: Name for the patch (used in file naming and messages)

    Returns:
        Bash script snippet that creates and applies the patch
    """
    # Encode the patch as base64 to avoid escaping issues
    encoded_patch = base64.b64encode(patch_content.encode()).decode()

    return f'''
# Create {patch_name} patch from base64
base64 -d << 'EOF_PATCH_{patch_name.upper()}' > /tmp/{patch_name}.patch
{encoded_patch}
EOF_PATCH_{patch_name.upper()}
'''


def generate_grading_setup_script(
    instance: TaskInstance,
    apply_golden_patch: bool = False,
    workdir: str = _DEFAULT_WORKDIR,
) -> str:
    """
    Generate a self-contained bash script that sets up the grading environment.

    This script:
    1. Configures git and marks the directory as safe
    2. Resets test files to the initial commit state (undoing any agent changes)
    3. Creates the test patch file from embedded base64 content
    4. Optionally applies the golden patch (for golden patch testing mode)

    Args:
        instance: TaskInstance containing the test patch and metadata
        apply_golden_patch: If True, also apply the golden patch before tests
        workdir: Working directory where the repo is located

    Returns:
        A complete bash script string that can be executed in any Linux environment
    """
    script_parts = [
        "#!/bin/bash",
        "set -e",
        "",
        "# Configure git",
        f'git config --global user.email "{_GIT_USER_EMAIL}"',
        f'git config --global user.name "{_GIT_USER_NAME}"',
        f"git config --global --add safe.directory {workdir}",
        "",
        f"cd {workdir}",
        "",
        "# Get the initial commit hash",
        "initial_commit=$(git rev-list --max-parents=0 HEAD)",
        "",
    ]

    # Reset test files to initial state (undo any agent modifications to test files)
    if instance.test_files:
        script_parts.append("# Reset test files to initial commit state")
        script_parts.append(
            "# This ensures we evaluate the agent's code changes, not test modifications"
        )

        for test_file in instance.test_files:
            script_parts.append(
                f'''
if git cat-file -e "$initial_commit:{test_file}" 2>/dev/null; then
    git checkout "$initial_commit" -- "{test_file}" || true
else
    # File didn't exist in initial commit, delete it if it exists now
    if [ -f "{test_file}" ]; then
        rm "{test_file}"
    fi
fi'''
            )

        script_parts.append("")

    # Apply golden patch if requested (for golden patch testing mode)
    if apply_golden_patch:
        script_parts.append("# Apply golden patch")
        script_parts.append(
            _generate_base64_patch_apply_script(instance.golden_patch, "golden")
        )
        script_parts.append(
            f'''
cd {workdir}
echo "=== Applying golden patch ==="
git apply /tmp/golden.patch 2>/tmp/golden_error.txt || {{
    echo "ERROR: Failed to apply golden patch"
    cat /tmp/golden_error.txt
    exit 1
}}
echo "Golden patch applied successfully"
'''
        )

    # Create and apply test patch
    script_parts.append("# Create and apply test patch")
    script_parts.append(_generate_base64_patch_apply_script(instance.test_patch, "test"))
    script_parts.append(
        f'''
cd {workdir}
echo "=== Applying test patch ==="

# Try to apply test patch with 3-way merge
# This allows partial success if golden patch already modified some files
git apply -3 /tmp/test.patch 2>&1 || true

echo "Test patch applied"
'''
    )

    return "\n".join(script_parts)


def generate_test_run_script(
    instance: TaskInstance,
    workdir: str = _DEFAULT_WORKDIR,
) -> str:
    """
    Generate a bash script that runs the tests and outputs results.

    This script:
    1. Changes to the working directory
    2. Creates necessary output directories
    3. Runs the test command with appropriate output flags
    4. If a result file is generated, outputs it to stdout with markers

    The script ensures that structured test output (JSON, XML, etc.) is available
    in stdout/stderr for parsing, even if the framework writes to a file.

    Args:
        instance: TaskInstance containing test command and framework info
        workdir: Working directory where tests should run

    Returns:
        A complete bash script string that runs tests and outputs results
    """
    # Get the test command with output flags
    test_cmd = get_test_command_with_output(instance.test_command, instance.test_framework)

    script_parts = [
        "#!/bin/bash",
        "# Don't use set -e - we want to capture test failures, not abort on them",
        "set -o pipefail",
        "",
        f"cd {workdir}",
        "",
        "# Create test results directory",
        "mkdir -p /workspace/test-results",
        "",
        "# Markers for parsing (helps extract test output from other stdout content)",
        'echo "<<<SWE_BENCH_EXT_TEST_OUTPUT_START>>>"',
        "",
        "# Run tests",
        test_cmd,
        "test_exit_code=$?",
        "",
    ]

    # If there's a result file, output its contents for parsing
    result_file = instance.result_file
    if result_file:
        if "*" in result_file:
            # Handle glob patterns (e.g., Maven/JUnit XMLs)
            script_parts.append(
                f'''
# Output result files (glob pattern: {result_file})
echo "<<<SWE_BENCH_EXT_RESULT_FILE_START>>>"
for f in {result_file}; do
    if [ -f "$f" ]; then
        echo "=== FILE: $f ==="
        cat "$f"
        echo ""
    fi
done 2>/dev/null || true
echo "<<<SWE_BENCH_EXT_RESULT_FILE_END>>>"
'''
            )
        else:
            # Single result file
            script_parts.append(
                f'''
# Output result file: {result_file}
echo "<<<SWE_BENCH_EXT_RESULT_FILE_START>>>"
if [ -f "{result_file}" ]; then
    cat "{result_file}"
fi
echo "<<<SWE_BENCH_EXT_RESULT_FILE_END>>>"
'''
            )

    script_parts.append(
        '''
echo "<<<SWE_BENCH_EXT_TEST_OUTPUT_END>>>"

# Exit with test exit code
exit $test_exit_code
'''
    )

    return "\n".join(script_parts)


def _extract_result_file_content(test_output: str) -> str | None:
    """
    Extract result file content from test output if markers are present.

    Args:
        test_output: Full test output including potential result file content

    Returns:
        Extracted result file content, or None if not found
    """
    start_marker = "<<<SWE_BENCH_EXT_RESULT_FILE_START>>>"
    end_marker = "<<<SWE_BENCH_EXT_RESULT_FILE_END>>>"

    if start_marker in test_output and end_marker in test_output:
        start_idx = test_output.find(start_marker) + len(start_marker)
        end_idx = test_output.find(end_marker)
        if start_idx < end_idx:
            return test_output[start_idx:end_idx].strip()

    return None


def parse_raw_test_output(test_output: str, test_framework: str) -> dict[str, str] | None:
    """
    Parse raw test output and return normalized test results.

    This function:
    1. Extracts structured test output from markers if present
    2. Uses the appropriate parser for the test framework
    3. Falls back to parsing full output if result file parsing fails
    4. Normalizes test IDs to remove unstable runtime prefixes

    Args:
        test_output: Raw test output string
        test_framework: Test framework name (e.g., 'pytest', 'go', 'jest')

    Returns:
        Dict of normalized test_id -> status, or None if parsing failed completely
    """
    # Try to extract result file content from markers
    result_file_content = _extract_result_file_content(test_output)

    # Parse test output using appropriate parser
    if result_file_content:
        parsed_results = parse_test_output(result_file_content, test_framework)
        # Fallback to full output if result file parsing failed
        if not parsed_results:
            parsed_results = parse_test_output(test_output, test_framework)
    else:
        parsed_results = parse_test_output(test_output, test_framework)

    # Normalize test IDs to remove unstable runtime prefixes
    if parsed_results:
        parsed_results = {
            normalize_test_id(tid, test_framework): status
            for tid, status in parsed_results.items()
        }

    return parsed_results


def _match_test_with_fuzzy(
    test_id: str,
    parsed_results: dict[str, str],
    build_failed_packages: set[str],
) -> str:
    """
    Try to match a test ID against parsed results, using fuzzy matching if needed.

    Args:
        test_id: The expected test ID to find
        parsed_results: Dict of parsed test IDs to statuses
        build_failed_packages: Set of packages that failed to build

    Returns:
        Test status: "PASSED", "FAILED", "SKIPPED", or "NOT_FOUND"
    """
    # Direct match
    if test_id in parsed_results:
        return parsed_results[test_id]

    # Try alternate separators (. vs ::) for gtest compatibility
    # Some test metadata uses :: while actual output uses . or vice versa
    alternate_id = None
    if "::" in test_id and "." not in test_id.split("::")[-1]:
        # Try converting TestClass::TestName -> TestClass.TestName
        alternate_id = test_id.replace("::", ".", 1)
    elif "." in test_id and "::" not in test_id:
        # Try converting TestClass.TestName -> TestClass::TestName
        alternate_id = test_id.replace(".", "::", 1)
    
    if alternate_id and alternate_id in parsed_results:
        return parsed_results[alternate_id]

    # Try fuzzy matching for tests with path::name format
    if "::" in test_id:
        file_path, test_name = test_id.rsplit("::", 1)

        # For parameterized tests, extract base name before brackets
        base_test_name = test_name.split("[")[0] if "[" in test_name else test_name

        # Look for tests in same file with similar names (try both :: and . separators)
        file_path_variants = [file_path, file_path.replace("::", ".")]
        for fp_variant in file_path_variants:
            for parsed_id in parsed_results.keys():
                # Check both :: and . as prefix separator
                if parsed_id.startswith(fp_variant + "::") or parsed_id.startswith(fp_variant + "."):
                    # Extract parsed test name
                    if "::" in parsed_id:
                        parsed_test_name = parsed_id.rsplit("::", 1)[1]
                    else:
                        parsed_test_name = parsed_id.rsplit(".", 1)[1]
                    
                    parsed_base_name = (
                        parsed_test_name.split("[")[0]
                        if "[" in parsed_test_name
                        else parsed_test_name
                    )

                    # Exact match on base name (handles parameterized tests)
                    if base_test_name == parsed_base_name:
                        return parsed_results[parsed_id]

                    # Fuzzy match on words for renamed tests
                    test_words = set(test_name.lower().split())
                    parsed_words = set(parsed_test_name.lower().split())
                    if len(test_words & parsed_words) >= len(test_words) * 0.7:
                        return parsed_results[parsed_id]

    # Check if the test's package failed to build
    test_package = test_id.split("::")[0] if "::" in test_id else test_id
    if test_package in build_failed_packages:
        return "FAILED"

    return "NOT_FOUND"


def parse_test_results(
    test_output: str,
    instance: TaskInstance,
) -> TestResults:
    """
    Parse test output and compute results against expected FAIL_TO_PASS and PASS_TO_PASS.

    This function:
    1. Extracts structured test output from markers if present
    2. Uses the appropriate parser for the test framework
    3. Normalizes test IDs for stable matching
    4. Matches against expected FAIL_TO_PASS and PASS_TO_PASS lists
    5. Computes overall pass/fail and score

    Args:
        test_output: Raw test output from running the test script
        instance: TaskInstance containing expected test results and framework info

    Returns:
        TestResults with parsed results, matching, and computed score
    """
    test_framework = instance.test_framework

    # Normalize expected test IDs
    fail_to_pass = [normalize_test_id(tid, test_framework) for tid in instance.fail_to_pass]
    pass_to_pass = [normalize_test_id(tid, test_framework) for tid in instance.pass_to_pass]

    # Parse test output using the common parsing function (returns normalized IDs)
    parsed_results = parse_raw_test_output(test_output, test_framework)

    # Handle case where parsing failed completely
    if parsed_results is None:
        parsed_results = {}

    # Handle synthetic build/compile tests
    # If a test ID ends with ::build or ::compile and is NOT in parsed_results,
    # it means the build/compilation SUCCEEDED (failures would be reported)
    for tid in fail_to_pass + pass_to_pass:
        if (tid.endswith("::build") or tid.endswith("::compile")) and tid not in parsed_results:
            parsed_results[tid] = "PASSED"

    # Identify packages that failed to build (package-level failures without ::)
    build_failed_packages = {
        pkg
        for pkg, status in parsed_results.items()
        if status == "FAILED" and "::" not in pkg
    }

    # Match FAIL_TO_PASS tests
    fail_to_pass_results = {}
    for test_id in fail_to_pass:
        fail_to_pass_results[test_id] = _match_test_with_fuzzy(
            test_id, parsed_results, build_failed_packages
        )

    # Match PASS_TO_PASS tests
    pass_to_pass_results = {}
    for test_id in pass_to_pass:
        pass_to_pass_results[test_id] = _match_test_with_fuzzy(
            test_id, parsed_results, build_failed_packages
        )

    # Compute pass/fail
    # Empty F2P list means we can't validate the fix
    if not fail_to_pass_results:
        all_f2p_passed = False
    else:
        all_f2p_passed = all(v == "PASSED" for v in fail_to_pass_results.values())
    
    all_p2p_passed = all(v == "PASSED" for v in pass_to_pass_results.values())
    passed = all_f2p_passed and all_p2p_passed

    return TestResults(
        score=1.0 if passed else 0.0,
        passed=passed,
        fail_to_pass_results=fail_to_pass_results,
        pass_to_pass_results=pass_to_pass_results,
        parsed_results=parsed_results,
    )


def generate_grading_explanation(
    results: TestResults,
    test_output: str = "",
    max_output_length: int = DEFAULT_MAX_OUTPUT_LENGTH,
) -> str:
    """
    Generate a human-readable explanation of test results.

    Args:
        results: TestResults from parse_test_results
        test_output: Optional raw test output to include
        max_output_length: Maximum length of test output to include

    Returns:
        Formatted explanation string
    """
    parts = [
        "Test Results:",
        f"  FAIL_TO_PASS: {results.f2p_passed}/{results.f2p_total} passed",
        f"  PASS_TO_PASS: {results.p2p_passed}/{results.p2p_total} passed",
        f"  Total parsed tests: {len(results.parsed_results)}",
    ]

    if (results.failed_f2p or results.failed_p2p) and len(
        results.parsed_results
    ) <= MAX_PARSED_TESTS_TO_SHOW:
        parts.append("\nParsed test IDs:")
        for test_id in sorted(results.parsed_results.keys()):
            parts.append(f"  {test_id}: {results.parsed_results[test_id]}")

    if results.failed_f2p:
        parts.append(f"\nFailed FAIL_TO_PASS tests ({len(results.failed_f2p)}):")
        for test in results.failed_f2p[:MAX_FAILED_TESTS_TO_SHOW]:
            parts.append(f"  - {test}: {results.fail_to_pass_results[test]}")
        if len(results.failed_f2p) > MAX_FAILED_TESTS_TO_SHOW:
            parts.append(
                f"  ... and {len(results.failed_f2p) - MAX_FAILED_TESTS_TO_SHOW} more"
            )

    if results.failed_p2p:
        parts.append(f"\nFailed PASS_TO_PASS tests ({len(results.failed_p2p)}):")
        for test in results.failed_p2p[:MAX_FAILED_TESTS_TO_SHOW]:
            parts.append(f"  - {test}: {results.pass_to_pass_results[test]}")
        if len(results.failed_p2p) > MAX_FAILED_TESTS_TO_SHOW:
            parts.append(
                f"  ... and {len(results.failed_p2p) - MAX_FAILED_TESTS_TO_SHOW} more"
            )

    if test_output:
        truncated = test_output[:max_output_length]
        if len(test_output) > max_output_length:
            truncated += "\n... (output truncated)"
        parts.append(f"\nTest output:\n{truncated}")

    return "\n".join(parts)
