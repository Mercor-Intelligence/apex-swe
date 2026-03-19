"""Utilities for the evaluation harness."""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .docker_manager import (
    DockerSetupMetadata,
    TaskSetupMetadata,
    check_docker,
    get_docker_info,
)
from src.harness.data_models import (
    ExecutionStatus,
    RunResult,
    TaskContext,
    TaskExecution,
)

logger = logging.getLogger(__name__)


def setup_task_environment(
    task_context: TaskContext,
    working_dir: Path | None = None,
    use_docker: bool = True,
) -> tuple[Path, "TaskSetupMetadata"]:
    """
    Set up the environment for task execution.

    Args:
        task_context: Task context with files and configuration
        working_dir: Optional working directory (creates temp if None)
        use_docker: Whether to use Docker for isolation

    Returns:
        Tuple of (working_directory, setup_metadata)
    """

    if working_dir is None:
        working_dir = Path(
            tempfile.mkdtemp(prefix=f"apex_task_{task_context.task_id}_")
        )
    else:
        working_dir.mkdir(parents=True, exist_ok=True)

    _setup_task_files_with_structure(task_context, working_dir)

    if task_context.environment:
        env_file = working_dir / ".env"
        with open(env_file, "w") as f:
            for key, value in task_context.environment.items():
                f.write(f"{key}={value}\n")

    docker_metadata = None
    if use_docker and check_docker():
        docker_metadata = _setup_docker_environment(task_context, working_dir)

    setup_metadata = TaskSetupMetadata(
        working_dir=str(working_dir),
        use_docker=use_docker,
        docker_metadata=docker_metadata,
    )

    return working_dir, setup_metadata


def _setup_task_files_with_structure(
    task_context: TaskContext, working_dir: Path
) -> None:
    """
    Efficiently set up task files preserving directory structure.

    Handles both tasks (with tests/ subdirectories) and simple tasks.
    Uses optimized batch operations for better performance.
    """
    tests_dir = task_context.task_dir / "tests"
    if tests_dir.exists() and tests_dir.is_dir():
        def ignore_patterns(src, names):
            return set()

        for item in tests_dir.iterdir():
            if item.is_dir():
                shutil.copytree(
                    item,
                    working_dir / item.name,
                    dirs_exist_ok=True,
                    ignore=ignore_patterns,
                )
            elif item.is_file():
                shutil.copy2(item, working_dir / item.name)

    root_patterns = [
        "*.yaml",  # YAML configs (task.yaml, docker-compose.yaml)
        "*.yml",  # Alternative YAML extension
        "Dockerfile*",  # Dockerfile and variants
        "Makefile",  # Build files
        "README*",
    ]

    for pattern in root_patterns:
        for file_path in task_context.task_dir.glob(pattern):
            if file_path.is_file():
                shutil.copy2(file_path, working_dir / file_path.name)

    if not (tests_dir.exists() and tests_dir.is_dir()):
        if task_context.files:
            for file_path in task_context.files:
                if not file_path.exists():
                    continue

                try:
                    rel_path = file_path.relative_to(task_context.task_dir)
                    dest_path = working_dir / rel_path

                    if dest_path.exists():
                        continue

                    if file_path.is_file():
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(file_path, dest_path)
                    elif file_path.is_dir():
                        shutil.copytree(file_path, dest_path, dirs_exist_ok=True)
                except ValueError:
                    if (
                        file_path.is_file()
                        and not (working_dir / file_path.name).exists()
                    ):
                        shutil.copy2(file_path, working_dir / file_path.name)


def calculate_metrics(
    trials: list[TaskExecution],
    metrics_config: dict[str, Any] | None = None,
) -> dict[str, float | int | str]:
    """
    Calculate evaluation metrics from trial results using single-pass algorithms.

    Args:
        trials: List of task execution results
        metrics_config: Configuration for metric calculation

    Returns:
        Dictionary of calculated metrics
    """
    if not trials:
        return {}

    if metrics_config is None:
        metrics_config = {
            "include_timing": True,
            "include_success": True,
            "include_quality": True,
        }

    total_trials = len(trials)
    successful_count = failed_count = timeout_count = 0
    total_time = valid_times = 0
    min_time = max_time = 0
    total_memory = memory_count = 0
    max_memory = 0
    total_confidence = confidence_count = 0
    min_confidence = max_confidence = 0
    total_tokens = token_count = 0

    for trial in trials:
        if trial.status == ExecutionStatus.COMPLETED:
            test_passed = (
                trial.metadata.get("test_passed", False) if trial.metadata else False
            )
            if test_passed:
                successful_count += 1
            else:
                failed_count += 1
        elif trial.status == ExecutionStatus.FAILED:
            failed_count += 1
        elif trial.status == ExecutionStatus.TIMEOUT:
            timeout_count += 1

        if metrics_config.get("include_timing", True) and trial.execution_time > 0:
            total_time += trial.execution_time
            valid_times += 1
            if valid_times == 1:
                min_time = max_time = trial.execution_time
            else:
                min_time = min(min_time, trial.execution_time)
                max_time = max(max_time, trial.execution_time)

        if trial.memory_used is not None:
            total_memory += trial.memory_used
            memory_count += 1
            max_memory = max(max_memory, trial.memory_used)

        if (
            trial.status == ExecutionStatus.COMPLETED
            and trial.agent_response
            and metrics_config.get("include_quality", True)
        ):
            if trial.agent_response.confidence is not None:
                total_confidence += trial.agent_response.confidence
                confidence_count += 1
                if confidence_count == 1:
                    min_confidence = max_confidence = trial.agent_response.confidence
                else:
                    min_confidence = min(
                        min_confidence, trial.agent_response.confidence
                    )
                    max_confidence = max(
                        max_confidence, trial.agent_response.confidence
                    )

            if trial.agent_response.tokens_used is not None:
                total_tokens += trial.agent_response.tokens_used
                token_count += 1

    metrics = {
        "total_trials": total_trials,
        "successful_trials": successful_count,
        "failed_trials": failed_count,
        "timeout_trials": timeout_count,
        "success_rate": successful_count / total_trials if total_trials > 0 else 0.0,
    }

    if valid_times > 0:
        metrics.update(
            {
                "average_time": total_time / valid_times,
                "min_time": min_time,
                "max_time": max_time,
                "total_time": total_time,
            }
        )

    if memory_count > 0:
        metrics.update(
            {
                "average_memory": total_memory / memory_count,
                "max_memory": max_memory,
            }
        )

    if confidence_count > 0:
        metrics.update(
            {
                "average_confidence": total_confidence / confidence_count,
                "min_confidence": min_confidence,
                "max_confidence": max_confidence,
            }
        )

    if token_count > 0:
        metrics.update(
            {
                "average_tokens": total_tokens / token_count,
                "total_tokens": total_tokens,
            }
        )

    return metrics


def cleanup_environment(
    working_dir: Path,
    setup_metadata: "TaskSetupMetadata",
    preserve_logs: bool = True,
) -> None:
    """
    Clean up the task execution environment.

    Args:
        working_dir: Working directory to clean up
        setup_metadata: Metadata from setup_task_environment
        preserve_logs: Whether to preserve log files
    """
    try:
        if setup_metadata.use_docker and setup_metadata.docker_metadata:
            _cleanup_docker_environment(setup_metadata.docker_metadata)

        if preserve_logs:
            log_dir = working_dir / "logs"
            if log_dir.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                preserved_logs = Path(f"logs/{working_dir.name}_{timestamp}")
                preserved_logs.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(log_dir), str(preserved_logs))

        if working_dir.exists():
            try:
                shutil.rmtree(working_dir)
            except PermissionError as e:
                logger.warning(
                    f"Permission error during cleanup, attempting to fix: {e}"
                )
                try:
                    subprocess.run(
                        ["chmod", "-R", "777", str(working_dir)],
                        check=False,
                        capture_output=True,
                    )
                    shutil.rmtree(working_dir)
                except Exception as retry_error:
                    logger.warning(
                        f"Failed to cleanup after permission fix: {retry_error}"
                    )

    except Exception as e:
        logger.warning(f"Error during cleanup: {e}")


def format_results(
    trials: list[TaskExecution],
    task_id: str,
    model: str,
    run_id: str,
    created_at: datetime,
) -> RunResult:
    """
    Format trial results into a final RunResult using optimized single-pass processing.

    Args:
        trials: List of task execution results
        task_id: Task identifier
        model: Model used for evaluation
        run_id: Run identifier
        created_at: When the run was created

    Returns:
        Formatted RunResult
    """
    if not trials:
        raise ValueError("Cannot format results from empty trials list")

    total_trials = len(trials)
    successful_trials = []
    total_time = 0
    best_trial = None
    best_confidence = -1

    for trial in trials:
        total_time += trial.execution_time

        if trial.status == ExecutionStatus.COMPLETED:
            test_passed = (
                trial.metadata.get("test_passed", False) if trial.metadata else False
            )
            if test_passed:
                successful_trials.append(trial)

                if (
                    trial.agent_response
                    and trial.agent_response.confidence is not None
                    and trial.agent_response.confidence > best_confidence
                ):
                    best_confidence = trial.agent_response.confidence
                    best_trial = trial

    metrics = calculate_metrics(trials)

    overall_status = (
        ExecutionStatus.COMPLETED if successful_trials else ExecutionStatus.FAILED
    )

    success_count = len(successful_trials)
    summary = f"{success_count}/{total_trials} trials successful"
    if best_trial and best_trial.agent_response:
        summary += f", best confidence: {best_trial.agent_response.confidence:.2f}"

    return RunResult(
        run_id=run_id,
        task_id=task_id,
        model=model,
        status=overall_status,
        trials=trials,
        success_rate=metrics.get("success_rate", 0.0),
        average_time=total_time / total_trials,
        total_time=total_time,
        best_trial=best_trial,
        metrics=metrics,
        summary=summary,
        created_at=created_at,
        completed_at=datetime.now(),
    )


def _setup_docker_environment(
    task_context: TaskContext,
    working_dir: Path,
) -> "DockerSetupMetadata":
    """Set up Docker environment for task execution."""
    docker_compose_path = task_context.task_dir / "docker-compose.yaml"
    docker_compose_found = docker_compose_path.exists()
    if docker_compose_found:
        shutil.copy2(docker_compose_path, working_dir / "docker-compose.yaml")

    dockerfile_path = task_context.task_dir / "Dockerfile"
    dockerfile_found = dockerfile_path.exists()
    if dockerfile_found:
        shutil.copy2(dockerfile_path, working_dir / "Dockerfile")

    repo_root = Path(__file__).resolve().parents[1]
    shared_dir = repo_root / "tasks" / "shared"
    if shared_dir.exists() and shared_dir.is_dir():
        dest_shared = working_dir / "shared"
        if dest_shared.exists():
            shutil.rmtree(dest_shared)
        shutil.copytree(shared_dir, dest_shared, symlinks=True)
        logger.debug(f"Copied shared directory to {dest_shared}")

    return DockerSetupMetadata(
        docker_available=check_docker(),
        container_name=f"apex_task_{task_context.task_id}_{int(time.time())}",
        docker_info=get_docker_info(),
        docker_compose_found=docker_compose_found,
        dockerfile_found=dockerfile_found,
    )


def _cleanup_docker_environment(docker_metadata: "DockerSetupMetadata") -> None:
    """Clean up Docker containers efficiently."""
    container_name = docker_metadata.container_name
    if container_name:
        try:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    container_name,
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
        except Exception:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
            except Exception:
                pass


def log_message(logs: list[str], message: str, log_level: str = "INFO") -> None:
    """Add log message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] {message}"
    logs.append(log_entry)
    if log_level in ["DEBUG", "INFO"]:
        print(log_entry)
