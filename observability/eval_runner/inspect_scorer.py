"""
Unified Inspect Scorer - Uses pre-computed F2P cache for consistent scoring.

This scorer wraps test execution and uses F2P/P2P lists from the F2P cache
(pre-computed from golden patch). This ensures Inspect view shows the same
results as eval_runner/scorer.py.

Usage:
    from eval_runner.inspect_scorer import unified_scorer
    
    task = Task(
        dataset=samples,
        solver=solver,
        scorer=unified_scorer(),
    )
"""

from __future__ import annotations

import base64
import json
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from eval_runner.logger import get_logger, get_task_logger
from eval_runner.config import (
    get_f2p_for_task,
    generate_run_id,
    EVAL_OUTPUTS_DIR,
    TIMEOUTS,
    CONTAINER_CONFIG,
)
from parser.frameworks import get_test_command_with_output
from parser.eval_utils import parse_test_results, TestResults, TaskInstance

logger = get_logger(__name__)


def extract_test_patch_targets(patch_content: str) -> tuple[list[str], list[str]]:
    """Extract file paths from a patch.
    
    Args:
        patch_content: The patch content
        
    Returns:
        Tuple of (existing_files, new_files)
    """
    existing_files: list[str] = []
    new_files: list[str] = []
    
    lines = patch_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("diff --git"):
            i += 1
            continue
        
        parts = line.split()
        if len(parts) < 4:
            i += 1
            continue
        
        target = parts[3]
        if target.startswith("b/"):
            target = target[2:]
        
        if not target:
            i += 1
            continue
        
        is_new_file = False
        for j in range(i + 1, min(i + 5, len(lines))):
            check_line = lines[j].strip()
            if check_line.startswith("diff --git"):
                break
            if check_line.startswith("new file mode"):
                is_new_file = True
                break
        
        if is_new_file:
            if target not in new_files:
                new_files.append(target)
        else:
            if target not in existing_files:
                existing_files.append(target)
        
        i += 1
    
    return existing_files, new_files


def evaluate_process_from_messages(
    state: TaskState,
    process_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze agent conversation messages for expected service interactions.

    Extracts all text from the inspect-ai TaskState messages (including tool
    call commands and tool results) and checks for evidence of service usage.

    Args:
        state: The inspect-ai TaskState containing conversation messages
        process_checks: List of check dicts with service, description, required, pattern

    Returns:
        Dict with checks, totals, and pass/fail summary
    """
    # Serialize all messages to a single searchable string
    parts: list[str] = []
    for msg in getattr(state, "messages", []):
        # Handle string content
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                else:
                    # ContentBlock objects — extract text/tool_call fields
                    parts.append(str(block))
        # Also capture tool_calls on assistant messages
        for tc in getattr(msg, "tool_calls", []) or []:
            parts.append(str(tc))
    combined = " ".join(parts).lower()

    results = []
    for check in process_checks:
        service = check.get("service", "").lower()
        description = check.get("description", f"Agent interacted with {service}")
        required = check.get("required", True)
        pattern = check.get("pattern", "")

        found = service in combined
        if found and pattern:
            found = bool(re.search(pattern.lower(), combined))

        results.append({
            "service": service,
            "description": description,
            "required": required,
            "passed": found,
        })

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    required_checks = [r for r in results if r["required"]]
    required_passed = sum(1 for r in required_checks if r["passed"])
    required_total = len(required_checks)

    return {
        "checks": results,
        "total": total,
        "passed": passed,
        "required_passed": required_passed,
        "required_total": required_total,
        "all_required_passed": required_passed == required_total,
    }


def save_run_outputs(
    task_id: str,
    run_id: str,
    agent_diff: str,
    test_output: str,
    test_exit_code: int,
    score_value: str,
    metadata: dict[str, Any],
) -> Optional[str]:
    """Save agent diff and test output to eval_outputs directory.
    
    Args:
        task_id: Task identifier
        run_id: Unique run identifier (UUID-based)
        agent_diff: The agent's diff
        test_output: Test execution output
        test_exit_code: Test command exit code
        score_value: Score value string
        metadata: Additional metadata
        
    Returns:
        Path to the run directory, or None if save failed
    """
    try:
        safe_task_id = task_id.replace("/", "_").replace("\\", "_")
        run_dir = EVAL_OUTPUTS_DIR / safe_task_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        (run_dir / "agent.patch").write_text(agent_diff or "", encoding="utf-8")
        (run_dir / "test_output.txt").write_text(test_output or "", encoding="utf-8")
        
        run_metadata = {
            "task_id": task_id,
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "test_exit_code": test_exit_code,
            "score": score_value,
            **metadata,
        }
        # Remove large fields from metadata
        run_metadata.pop("agent_diff", None)
        run_metadata.pop("raw_output", None)
        
        (run_dir / "metadata.json").write_text(
            json.dumps(run_metadata, indent=2, default=str), encoding="utf-8"
        )
        
        return str(run_dir)
    except OSError as e:
        logger.warning(f"Failed to save run outputs for {task_id}: {e}")
        return None


@scorer(metrics=[accuracy(), stderr()])
def unified_scorer(
    timeout: int = TIMEOUTS.in_agent_scorer,
):
    """Unified scorer using pre-computed F2P cache.

    This scorer:
    1. Loads F2P/P2P from cache (pre-computed from golden patch)
    2. Runs tests with agent's changes
    3. Validates against cached F2P/P2P lists

    Note: F2P/P2P from test_metadata.json is NOT used.

    Args:
        timeout: Test execution timeout in seconds
    """

    async def score(state: TaskState, target: Target) -> Score:
        task_id = state.metadata.get("task_id", "unknown")
        task_dir = state.metadata.get("task_dir", "")
        
        # Use run_id from runner if passed, otherwise generate new one
        run_id = state.metadata.get("run_id") or generate_run_id()
        task_logger = get_task_logger(task_id, __name__)

        # Load test_metadata.json for test_command and framework only
        metadata: dict[str, Any] = {}
        try:
            if task_dir:
                test_metadata_path = Path(task_dir) / "test_metadata.json"
                if test_metadata_path.exists():
                    metadata = json.loads(test_metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            task_logger.warning(f"Failed to load test_metadata.json: {e}")

        cmd = metadata.get("test_command", "npm test")
        framework = metadata.get("test_framework", "vitest")

        # Load F2P/P2P from cache (generated from golden patch)
        required_tests, regression_tests = get_f2p_for_task(
            task_id, 
            auto_generate=True, 
            timeout=timeout,
            verbose=False,
        )
        f2p_from_cache = bool(required_tests)
        
        if not required_tests:
            task_logger.warning("No F2P tests found - scoring may be inaccurate")

        # Add framework-specific output flags (centralized in parser.frameworks)
        cmd = get_test_command_with_output(cmd, framework)

        # Capture agent diff
        agent_diff = ""
        changed_files: list[str] = []
        try:
            diff_result = await sandbox().exec(
                ["bash", "-c", "cd /app/repo && git add -A && git diff HEAD 2>/dev/null || git diff 2>/dev/null"],
                timeout=TIMEOUTS.git_diff,
            )
            if diff_result.success:
                agent_diff = diff_result.stdout or ""
            
            status_result = await sandbox().exec(
                ["bash", "-c", "cd /app/repo && git status --porcelain 2>/dev/null"],
                timeout=TIMEOUTS.git_checkout,
            )
            if status_result.success:
                for line in (status_result.stdout or "").split("\n"):
                    if line.strip():
                        changed_files.append(line.strip())
        except Exception as e:
            task_logger.warning(f"Failed to capture agent diff: {e}")

        state.metadata["agent_diff"] = agent_diff
        state.metadata["run_id"] = run_id

        # Apply test.patch
        test_patch_applied = False
        test_patch_error = ""
        try:
            test_patch_content = None
            if task_dir:
                test_patch_path = Path(task_dir) / "test.patch"
                if test_patch_path.exists():
                    test_patch_content = test_patch_path.read_text(encoding="utf-8")
            
            if test_patch_content:
                existing_files, new_files = extract_test_patch_targets(test_patch_content)
                
                if existing_files:
                    quoted_files = " ".join(shlex.quote(f) for f in existing_files)
                    await sandbox().exec(
                        ["bash", "-c", f"cd /app/repo && git checkout HEAD -- {quoted_files} 2>&1 || true"],
                        timeout=TIMEOUTS.git_checkout,
                    )
                
                if new_files:
                    for new_file in new_files:
                        quoted_file = shlex.quote(new_file)
                        await sandbox().exec(
                            ["bash", "-c", f"cd /app/repo && rm -f {quoted_file} 2>&1 || true"],
                            timeout=TIMEOUTS.git_checkout,
                        )
                
                await sandbox().write_file("/app/test.patch", test_patch_content)
                apply_result = await sandbox().exec(
                    ["bash", "-c", "cd /app/repo && git apply /app/test.patch 2>&1"],
                    timeout=TIMEOUTS.git_apply,
                )
                if apply_result.success:
                    test_patch_applied = True
                else:
                    test_patch_error = apply_result.stdout or apply_result.stderr or "Unknown error"
                    task_logger.error(f"Test patch failed to apply: {test_patch_error}")
        except Exception as e:
            test_patch_error = str(e)
            task_logger.error(f"Exception applying test patch: {e}")

        # If test patch failed to apply, return INCORRECT immediately
        if test_patch_content and not test_patch_applied:
            output_dir = save_run_outputs(
                task_id=task_id,
                run_id=run_id,
                agent_diff=agent_diff,
                test_output=f"Test patch failed to apply: {test_patch_error}",
                test_exit_code=-1,
                score_value="I",
                metadata={
                    "error": "test_patch_failed",
                    "test_patch_error": test_patch_error,
                    "f2p_from_cache": f2p_from_cache,
                },
            )
            return Score(
                value=INCORRECT,
                answer="Test patch failed to apply",
                explanation=f"Test patch application failed: {test_patch_error}",
                metadata={
                    "task_id": task_id,
                    "run_id": run_id,
                    "error": "test_patch_failed",
                    "test_patch_error": test_patch_error,
                    "f2p_from_cache": f2p_from_cache,
                    "output_dir": output_dir,
                },
            )

        # Run tests and capture exit code
        # Use tee to capture both terminal output AND allow framework result files
        test_output_file = "/tmp/test_output.txt"
        test_results_dir = "/tmp/test-results"
        
        # Use centralized copy commands from CONTAINER_CONFIG
        copy_results_cmd = CONTAINER_CONFIG.get_test_results_copy_commands()
        copy_results_cmd += "\nls -la /tmp/test-results/ 2>/dev/null || true"
        
        # Also write to /var/log/app/ for live log streaming to Loki via promtail
        live_log_file = "/var/log/app/test_output.log"
        
        full_cmd = f"""
{CONTAINER_CONFIG.path_setup}
cd /app/repo
mkdir -p {test_results_dir}
mkdir -p /var/log/app
echo "=== TEST COMMAND: {cmd} ===" | tee {test_output_file} {live_log_file}
echo "=== START OUTPUT ===" | tee -a {test_output_file} {live_log_file}
({cmd}) 2>&1 | tee -a {test_output_file} {live_log_file}
_test_exit_code=${{PIPESTATUS[0]}}
echo "EXIT_CODE:$_test_exit_code" | tee -a {test_output_file} {live_log_file}
{copy_results_cmd}
exit $_test_exit_code
"""
        
        try:
            result = await sandbox().exec(
                ["bash", "-c", full_cmd],
                timeout=timeout,
            )

            # Read test output (terminal capture)
            read_result = await sandbox().exec(
                ["bash", "-c", f"base64 {test_output_file} 2>/dev/null || cat {test_output_file}"],
                timeout=TIMEOUTS.git_diff,
            )
            if read_result.success and read_result.stdout:
                try:
                    combined_output = base64.b64decode(read_result.stdout).decode("utf-8")
                except Exception:
                    raw_output = read_result.stdout
                    if "EXIT_CODE:" in raw_output or "PASS" in raw_output or "FAIL" in raw_output:
                        combined_output = raw_output
                    else:
                        combined_output = result.stdout or raw_output
                        task_logger.warning("Base64 decode failed, using direct output")
            else:
                combined_output = result.stdout or ""
            
            # Read framework-specific result files (XML/JSON) if they exist
            # These provide more reliable structured output than terminal capture
            result_files_cmd = f"""
for f in {test_results_dir}/*.xml {test_results_dir}/*.json; do
    if [ -f "$f" ]; then
        echo "=== RESULT FILE: $f ==="
        cat "$f"
        echo ""
    fi
done
"""
            result_files_result = await sandbox().exec(
                ["bash", "-c", result_files_cmd],
                timeout=TIMEOUTS.git_diff,
            )
            if result_files_result.success and result_files_result.stdout.strip():
                combined_output += f"\n\n=== RESULT FILES ===\n{result_files_result.stdout}"
                task_logger.info("Found and appended framework result files")

        except Exception as e:
            task_logger.error(f"Test execution failed: {e}")
            output_dir = save_run_outputs(
                task_id=task_id,
                run_id=run_id,
                agent_diff=agent_diff,
                test_output=f"Exception: {str(e)}",
                test_exit_code=-1,
                score_value="I",
                metadata={"error": str(e), "f2p_from_cache": f2p_from_cache},
            )
            return Score(
                value=INCORRECT,
                answer="Test execution failed",
                explanation=f"Error: {str(e)}",
                metadata={
                    "task_id": task_id,
                    "run_id": run_id,
                    "error": str(e),
                    "f2p_from_cache": f2p_from_cache,
                },
            )

        # Extract exit code
        test_exit_code = result.returncode
        if "EXIT_CODE:" in combined_output:
            try:
                exit_line = [l for l in combined_output.split("\n") if "EXIT_CODE:" in l][-1]
                parsed_exit_code = int(exit_line.split("EXIT_CODE:")[1].strip())
                # Log if there's a mismatch (should be rare now that script exits with test code)
                if parsed_exit_code != result.returncode:
                    task_logger.debug(
                        f"Exit code mismatch: parsed={parsed_exit_code}, returncode={result.returncode}"
                    )
                test_exit_code = parsed_exit_code
            except (ValueError, IndexError) as e:
                task_logger.warning(f"Failed to parse exit code from output, using returncode: {e}")
        
        # Use UNIFIED parsing and matching logic from parser/eval_utils.py
        # This ensures inspect_scorer uses the SAME logic as scorer.py -> parser/evaluator.py
        # 
        # Create a TaskInstance for the unified parse_test_results() function
        task_instance = TaskInstance(
            task_id=task_id,
            test_framework=framework,
            test_command=cmd,
            language="",  # Not needed for parsing
            test_files=[],  # Not needed for parsing
            fail_to_pass=required_tests,  # F2P tests from cache
            pass_to_pass=regression_tests,  # P2P tests from cache
            test_patch="",  # Already applied
            golden_patch="",  # Not needed
            problem_statement="",
            prompt_statement="",
        )
        
        # Use the unified parse_test_results() which handles:
        # - Test output parsing with parse_test_output()
        # - Test ID normalization with normalize_test_id()  
        # - Fuzzy matching with _match_test_with_fuzzy()
        # - Alternate separator handling (:: vs .)
        # - Build failure package tracking
        test_results: TestResults = parse_test_results(combined_output, task_instance)

        if not test_results.parsed_results:
            # No tests parsed - likely a build failure or test framework crash
            if test_exit_code != 0:
                task_logger.error(
                    f"No tests parsed and exit code is {test_exit_code} - likely build failure"
                )
                error_reason = f"Build/test failure (exit code {test_exit_code})"
            else:
                task_logger.warning("Failed to parse test output - no tests found")
                error_reason = "No tests found in output"
            
            output_dir = save_run_outputs(
                task_id=task_id,
                run_id=run_id,
                agent_diff=agent_diff,
                test_output=combined_output,
                test_exit_code=test_exit_code,
                score_value="I",
                metadata={
                    "parse_failed": True,
                    "likely_build_failure": test_exit_code != 0,
                    "f2p_from_cache": f2p_from_cache,
                },
            )
            return Score(
                value=INCORRECT,
                answer=error_reason,
                explanation=f"{error_reason}:\n{combined_output[:2000]}",
                metadata={
                    "task_id": task_id,
                    "run_id": run_id,
                    "exit_code": test_exit_code,
                    "parse_failed": True,
                    "likely_build_failure": test_exit_code != 0,
                    "f2p_from_cache": f2p_from_cache,
                    "agent_diff": agent_diff,
                },
            )

        # Extract results from unified TestResults
        # F2P results: tests that should go from FAIL -> PASS
        passed_required = [t for t, s in test_results.fail_to_pass_results.items() if s == "PASSED"]
        failed_required = [t for t, s in test_results.fail_to_pass_results.items() if s == "FAILED"]
        missing_required = [t for t, s in test_results.fail_to_pass_results.items() if s == "NOT_FOUND"]
        
        # P2P results: tests that should stay PASS -> PASS (regressions = failed P2P)
        regressed_tests = [t for t, s in test_results.pass_to_pass_results.items() if s != "PASSED"]

        # Use the unified scoring logic
        success = test_results.passed
        score_value = CORRECT if success else INCORRECT

        explanation_parts = [
            f"FAIL_TO_PASS: {test_results.f2p_passed}/{test_results.f2p_total} tests now pass",
        ]
        if failed_required:
            explanation_parts.append(f"Still failing: {', '.join(failed_required[:5])}")
        if missing_required:
            explanation_parts.append(f"Missing: {', '.join(missing_required[:5])}")
        if regressed_tests:
            explanation_parts.append(f"PASS_TO_PASS regressions: {', '.join(regressed_tests[:5])}")
        explanation_parts.append(f"\nTotal parsed: {len(test_results.parsed_results)}")
        explanation_parts.append(f"F2P from cache: {f2p_from_cache}")

        output_dir = save_run_outputs(
            task_id=task_id,
            run_id=run_id,
            agent_diff=agent_diff,
            test_output=combined_output,
            test_exit_code=test_exit_code,
            score_value=str(score_value),
            metadata={
                "passed_required": passed_required,
                "failed_required": failed_required,
                "missing_required": missing_required,
                "regressed_tests": regressed_tests,
                "f2p_from_cache": f2p_from_cache,
                # Complete scoring data for direct extraction
                "f2p_passed": test_results.f2p_passed,
                "f2p_total": test_results.f2p_total,
                "p2p_passed": test_results.p2p_passed,
                "p2p_total": test_results.p2p_total,
                "passed": success,
            },
        )

        # Process verification: check agent interacted with required services
        process_verification = None
        try:
            process_checks = metadata.get("process_checks")
            if not process_checks and task_dir:
                import yaml
                task_yaml_path = Path(task_dir) / "task.yaml"
                if task_yaml_path.exists():
                    task_yaml = yaml.safe_load(task_yaml_path.read_text(encoding="utf-8"))
                    process_checks = task_yaml.get("process_checks")
            if process_checks:
                process_verification = evaluate_process_from_messages(state, process_checks)
                task_logger.info(
                    f"Process verification: {process_verification['passed']}/{process_verification['total']} checks passed "
                    f"(required: {process_verification['required_passed']}/{process_verification['required_total']})"
                )
        except Exception as e:
            task_logger.warning(f"Process verification failed: {e}")

        score_metadata = {
            "task_id": task_id,
            "run_id": run_id,
            "passed_required": passed_required,
            "failed_required": failed_required,
            "missing_required": missing_required,
            "regressed_tests": regressed_tests,
            "total_parsed": len(test_results.parsed_results),
            "exit_code": test_exit_code,
            "f2p_from_cache": f2p_from_cache,
            "f2p_count": test_results.f2p_total,
            "p2p_count": test_results.p2p_total,
            "p2p_passed": test_results.p2p_passed,
            "agent_diff": agent_diff,
            "changed_files": changed_files,
            "test_patch_applied": test_patch_applied,
            "output_dir": output_dir,
        }
        if process_verification:
            score_metadata["process_verification"] = process_verification

        return Score(
            value=score_value,
            answer=f"{test_results.f2p_passed}/{test_results.f2p_total} FAIL_TO_PASS tests passed",
            explanation="\n".join(explanation_parts),
            metadata=score_metadata,
        )

    return score
