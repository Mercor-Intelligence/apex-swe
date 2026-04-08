"""Apex-Code evaluation system - simple pass/fail based on test scripts."""

import base64
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils import get_logger
from .data_models import ExecutionStatus, TaskExecution


class TaskEvaluator:
    """Apex-Code task evaluation using test scripts."""

    def __init__(self):
        """Initialize evaluator."""
        pass

    def evaluate_execution(
        self,
        execution: TaskExecution,
        task_dir: Path,
        working_dir: Path,
        max_test_timeout: float | None = None,
        docker_manager=None,
    ) -> dict[str, Any]:
        """
        Evaluate task execution using Apex-Code test scripts.

        Args:
            execution: The task execution to evaluate
            task_dir: Directory containing the task files
            working_dir: Working directory where the task was executed

        Returns:
            Evaluation results with pass/fail status
        """
        evaluation = {
            "execution_id": execution.trial_number,
            "timestamp": datetime.now().isoformat(),
            "passed": False,
            "status": "error",  # "passed", "failed", or "error"
            "test_output": "",
            "test_exit_code": -1,
            "execution_time": execution.execution_time,
            "memory_used": execution.memory_used,
        }

        if execution.status != ExecutionStatus.COMPLETED:
            evaluation["test_output"] = (
                f"Execution failed with status: {execution.status}"
            )
            if execution.error_message:
                evaluation["test_output"] += f"\nError: {execution.error_message}"
            evaluation["status"] = "error"
            return evaluation

        test_scripts = [
            "run-tests.sh",
            "test.sh",
            "tests.sh",
            "run_tests.sh",
            "verify.sh",
        ]

        test_script = None
        for script in test_scripts:
            script_path = task_dir / script
            if script_path.exists():
                test_script = script_path
                break

        if not test_script:
            evaluation["test_output"] = (
                f"EVALUATION FAILED: No test script found in working directory ({working_dir}) or task directory ({task_dir}). Expected one of: {', '.join(test_scripts)}"
            )
            evaluation["passed"] = False
            evaluation["status"] = "error"
            return evaluation

        logger = get_logger()
        if logger:
            logger._log(f"EVALUATION: Using test script: {test_script}")
            logger._log(
                "EVALUATION: Looking for test parser output ('PASSED' or 'FAILED')"
            )

        try:
            test_timeout = max_test_timeout if max_test_timeout else 60

            if docker_manager:
                test_files_to_copy = []
                test_files_to_copy.append(test_script)

                tests_dir = task_dir / "tests"
                if tests_dir.exists():
                    test_files_to_copy.append(tests_dir)

                docker_manager.exec_command("mkdir -p /tests")

                for file_or_dir in test_files_to_copy:
                    if file_or_dir.is_file():
                        content = file_or_dir.read_text()
                        container_path = f"/tests/{file_or_dir.name}"
                        safe_path = shlex.quote(container_path)

                        encoded_content = base64.b64encode(
                            content.encode("utf-8")
                        ).decode("ascii")
                        docker_manager.exec_command(
                            f"echo '{encoded_content}' | base64 -d > {safe_path}"
                        )
                        if file_or_dir.suffix == ".sh":
                            docker_manager.exec_command(f"chmod +x {safe_path}")
                    elif file_or_dir.is_dir():
                        for test_file in file_or_dir.rglob("*"):
                            if test_file.is_file():
                                relative_path = test_file.relative_to(task_dir)
                                container_path = f"/{relative_path}"
                                safe_path = shlex.quote(container_path)
                                parent_dir = shlex.quote(
                                    str(Path(container_path).parent)
                                )
                                docker_manager.exec_command(
                                    f"mkdir -p {parent_dir}"
                                )
                                try:
                                    content = test_file.read_text()

                                    encoded_content = base64.b64encode(
                                        content.encode("utf-8")
                                    ).decode("ascii")
                                    docker_manager.exec_command(
                                        f"echo '{encoded_content}' | base64 -d > {safe_path}"
                                    )
                                    if test_file.suffix == ".sh":
                                        docker_manager.exec_command(
                                            f"chmod +x {safe_path}"
                                        )
                                except Exception:
                                    pass

                safe_script_name = shlex.quote(test_script.name)
                test_command = (
                    f"cd /tests && chmod +x /tests/{safe_script_name} "
                    f"&& TEST_DIR=/tests bash /tests/{safe_script_name}"
                )
                result = docker_manager.exec_command(test_command, timeout=test_timeout)

                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                exit_code = result.get("exit_code", -1)

                test_passed = self._parse_test_output(stdout)

                evaluation[
                    "test_output"
                ] = f"""OFFICIAL TEST EXECUTION: {test_script.name}
Command: {test_command}
Timeout: {test_timeout}s

=== STDOUT ===
{stdout}

=== STDERR ===
{stderr}

=== RESULT ===
Exit Code: {exit_code}
Test Result: {"PASSED" if test_passed else "FAILED" if test_passed is False else "NO_PARSER_OUTPUT"}"""

                evaluation["test_exit_code"] = exit_code
                evaluation["passed"] = test_passed if test_passed is not None else False

                if test_passed is True:
                    evaluation["test_output"] += (
                        "\n\nEVALUATION RESULT: PASSED - Test parser found 'PASSED'"
                    )
                    evaluation["status"] = "passed"
                    success_message = f"EVALUATION PASSED: {test_script.name} - Test parser returned PASSED"
                    if logger:
                        logger._log(success_message)
                elif test_passed is False:
                    evaluation["test_output"] += (
                        "\n\nEVALUATION RESULT: FAILED - Test parser found 'FAILED'"
                    )
                    evaluation["status"] = "failed"
                    failure_message = f"EVALUATION FAILED: {test_script.name} - Test parser returned FAILED"
                    if logger:
                        logger._log(failure_message)
                else:
                    evaluation["test_output"] += (
                        f"\n\nEVALUATION RESULT: ERROR - No test parser output found (exit code: {exit_code})"
                    )
                    evaluation["status"] = "error"
                    no_parser_message = f"EVALUATION ERROR: {test_script.name} - No test parser output detected"
                    if logger:
                        logger._log(no_parser_message)

            else:
                test_script.chmod(0o755)

                env = os.environ.copy()
                env["TEST_DIR"] = str(task_dir / "tests")
                env["HOME"] = os.path.expanduser("~")

                result = subprocess.run(
                    [str(test_script)],
                    cwd=working_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=test_timeout,
                )

                test_passed = self._parse_test_output(result.stdout)

                evaluation[
                    "test_output"
                ] = f"""OFFICIAL TEST EXECUTION: {test_script.name}
Command: {str(test_script)}
Timeout: {test_timeout}s

=== STDOUT ===
{result.stdout}

=== STDERR ===
{result.stderr}

=== RESULT ===
Exit Code: {result.returncode}
Test Result: {"PASSED" if test_passed else "FAILED" if test_passed is False else "NO_PARSER_OUTPUT"}"""

                evaluation["test_exit_code"] = result.returncode
                evaluation["passed"] = test_passed if test_passed is not None else False

                if test_passed is True:
                    evaluation["test_output"] += (
                        "\n\nEVALUATION RESULT: PASSED - Test parser found 'PASSED'"
                    )
                    evaluation["status"] = "passed"
                    success_message = f"EVALUATION PASSED: {test_script.name} - Test parser returned PASSED"
                    if logger:
                        logger._log(success_message)
                elif test_passed is False:
                    evaluation["test_output"] += (
                        "\n\nEVALUATION RESULT: FAILED - Test parser found 'FAILED'"
                    )
                    evaluation["status"] = "failed"
                    failure_message = f"EVALUATION FAILED: {test_script.name} - Test parser returned FAILED"
                    if logger:
                        logger._log(failure_message)
                else:
                    evaluation["test_output"] += (
                        f"\n\nEVALUATION RESULT: ERROR - No test parser output found (exit code: {result.returncode})"
                    )
                    evaluation["status"] = "error"
                    no_parser_message = f"EVALUATION ERROR: {test_script.name} - No test parser output detected"
                    if logger:
                        logger._log(no_parser_message)

        except subprocess.TimeoutExpired:
            evaluation["test_output"] = (
                f"EVALUATION ERROR: Test script timed out after {test_timeout} seconds"
            )
            evaluation["test_exit_code"] = -1
            evaluation["passed"] = False
            evaluation["status"] = "error"

        except Exception as e:
            error_msg = f"EVALUATION ERROR: Error running test script {test_script.name}: {str(e)}"
            evaluation["test_output"] = error_msg
            evaluation["test_exit_code"] = -1
            evaluation["passed"] = False
            evaluation["status"] = "error"

        return evaluation

    def _parse_test_output(self, stdout: str) -> bool | None:
        """
        Parse test output to determine actual pass/fail status.

        Supports multiple test result formats:
        1. Structured format:
           - "results starts here" or "SWEBench results starts here"
           - "PASSED" or "FAILED"
           - "results ends here" or "SWEBench results ends here"
        2. Pytest native output:
           - "=== N passed in X.XXs ===" (all passed)
           - "=== N failed, M passed in X.XXs ===" (some failed)
           - "=== N failed in X.XXs ===" (all failed)
        3. Exit code based on script output

        Returns:
            True if PASSED found
            False if FAILED found
            None if no test parser output found
        """
        if not stdout:
            return None

        lines = stdout.split("\n")
        in_results_section = False

        for line in lines:
            line_stripped = line.strip()

            if "results starts here" in line_stripped.lower():
                in_results_section = True
                continue

            if "results ends here" in line_stripped.lower():
                break

            if in_results_section:
                if line_stripped == "PASSED":
                    return True
                elif line_stripped == "FAILED":
                    return False

        for line in reversed(lines):
            line_stripped = line.strip()

            failed_match = re.search(r"(\d+)\s+failed", line_stripped)
            if failed_match:
                num_failed = int(failed_match.group(1))
                if num_failed > 0:
                    return False

            passed_match = re.search(r"(\d+)\s+passed", line_stripped)
            if passed_match and re.search(r"in\s+[\d.]+s", line_stripped):
                num_passed = int(passed_match.group(1))
                if num_passed > 0:
                    return True

            if re.match(r"=+\s*FAILED\s*=+", line_stripped):
                return False

        return None

    def evaluate_run(
        self, executions: list[TaskExecution], task_dir: Path, working_dirs: list[Path]
    ) -> dict[str, Any]:
        """
        Evaluate a complete run with multiple trials.

        Args:
            executions: List of task executions
            task_dir: Directory containing the task files
            working_dirs: List of working directories for each execution

        Returns:
            Aggregated evaluation results
        """
        evaluations = []

        if len(working_dirs) < len(executions):
            working_dirs = working_dirs + [None] * (len(executions) - len(working_dirs))

        for i, execution in enumerate(executions):
            working_dir = (
                working_dirs[i] if working_dirs[i] else Path(f"/tmp/trial_{i + 1}")
            )
            eval_result = self.evaluate_execution(execution, task_dir, working_dir)
            evaluations.append(eval_result)

        passed_count = sum(1 for e in evaluations if e["passed"])
        total_count = len(evaluations)

        return {
            "evaluations": evaluations,
            "summary": {
                "total_trials": total_count,
                "passed_trials": passed_count,
                "failed_trials": total_count - passed_count,
                "success_rate": passed_count / total_count if total_count > 0 else 0.0,
                "average_execution_time": sum(e["execution_time"] for e in evaluations)
                / total_count
                if total_count > 0
                else 0.0,
                "average_memory_used": sum(
                    e["memory_used"] for e in evaluations if e["memory_used"]
                )
                / total_count
                if total_count > 0
                else 0.0,
            },
        }

    def format_evaluation_report(self, evaluation_results: dict[str, Any]) -> str:
        """
        Format evaluation results for display.

        Args:
            evaluation_results: Results from evaluate_run

        Returns:
            Formatted report string
        """
        summary = evaluation_results["summary"]
        evaluations = evaluation_results["evaluations"]

        report = []
        report.append("=" * 60)
        report.append("EVALUATION REPORT")
        report.append("=" * 60)
        report.append(f"Total Trials: {summary['total_trials']}")
        report.append(f"Passed: {summary['passed_trials']}")
        report.append(f"Failed: {summary['failed_trials']}")
        report.append(f"Success Rate: {summary['success_rate']:.1%}")
        report.append(
            f"Average Execution Time: {summary['average_execution_time']:.2f}s"
        )
        report.append(f"Average Memory Used: {summary['average_memory_used']:.1f}MB")
        report.append("")

        report.append("TRIAL RESULTS:")
        report.append("-" * 60)

        for i, eval in enumerate(evaluations):
            status = "✅ PASSED" if eval["passed"] else "❌ FAILED"
            report.append(f"Trial {i + 1}: {status}")

            if eval["test_output"]:
                output_lines = eval["test_output"].strip().split("\n")[:5]
                for line in output_lines:
                    report.append(f"  {line}")
                if len(eval["test_output"].strip().split("\n")) > 5:
                    report.append("  ...")

            report.append("")

        return "\n".join(report)
