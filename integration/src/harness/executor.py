"""Evaluation executor - orchestrates evaluation runs."""

import concurrent.futures
import fnmatch
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue

import yaml

from src.utils import LiteLLM, create_llm
from src.utils import get_logger, init_apex_logger
from .data_models import (
    EvaluationConfig,
    ModelType,
    RunResult,
    TaskContext,
    TaskExecution,
)
from .multi_step_runner import MultiStepRunner
from src.utils.harness_utils import format_results
from .data_models import ExecutionStatus

logger = logging.getLogger(__name__)


class EvaluationExecutor:
    """Main evaluation orchestrator - coordinates task execution and result aggregation."""

    def __init__(
        self,
        llm_factory: dict[ModelType, LiteLLM] | None = None,
        max_workers: int = 4,
    ):
        """
        Initialize evaluation executor.

        Args:
            llm_factory: Optional mapping of model types to LLMs
            max_workers: Maximum number of parallel workers for trial execution
        """
        self.llm_factory = llm_factory or {}
        self.max_workers = max_workers
        self._thread_local = threading.local()

    def execute_run(
        self, config: EvaluationConfig, resume_from: str | None = None
    ) -> RunResult:
        """
        Execute a complete evaluation run.

        Args:
            config: Evaluation configuration
            resume_from: Optional run ID to resume from

        Returns:
            RunResult with aggregated results
        """
        logger = init_apex_logger(config.run_id, config.runs_dir)
        task_context = self._load_task_context(config)

        duration_source = "default"
        task_duration = config.timeout
        if (
            hasattr(task_context, "max_agent_timeout_sec")
            and task_context.max_agent_timeout_sec is not None
        ):
            task_duration = task_context.max_agent_timeout_sec
            duration_source = "task.yaml"

        logger.log_run_metadata(
            {
                "task_id": config.task_id,
                "model": config.model.value,
                "max_trials": config.max_trials,
                "timeout": task_duration,
                "resume_from": resume_from,
                "max_workers": self.max_workers,
                "tasks": [
                    {
                        "name": config.task_id,
                        "duration": f"{task_duration}s",
                        "source": duration_source,
                    }
                ],
            }
        )

        llm = self._get_llm(config.model, task_context, reasoning_effort=getattr(config, 'reasoning_effort', None))

        existing_trials = []
        if resume_from:
            existing_trials = self._load_existing_trials(resume_from, config)

        completed_trials = len(existing_trials)
        remaining_trials = max(0, config.max_trials - completed_trials)

        if remaining_trials == 0:
            return format_results(
                trials=existing_trials,
                task_id=config.task_id,
                model=config.model,
                run_id=config.run_id,
                created_at=config.created_at,
            )

        new_trials = self._execute_trials_parallel(
            task_context=task_context,
            llm=llm,
            max_trials=remaining_trials,
            start_trial_num=completed_trials + 1,
            todo_tool_enabled=config.todo_tool_enabled,
        )

        trials = existing_trials + new_trials

        result = format_results(
            trials=trials,
            task_id=config.task_id,
            model=config.model,
            run_id=config.run_id,
            created_at=config.created_at,
        )

        logger = get_logger()
        if logger:
            logger.finalize_run(
                {
                    "success_rate": result.success_rate,
                    "total_trials": len(trials),
                    "average_time": result.average_time,
                    "status": result.status,
                }
            )

        return result

    def _load_task_context(self, config: EvaluationConfig) -> TaskContext:
        """Load task context from tasks directory."""
        task_dir = config.tasks_dir / config.task_id

        if not task_dir.exists():
            raise FileNotFoundError(f"Task directory not found: {task_dir}")

        # Load task.yaml if it exists
        task_yaml_path = task_dir / "task.yaml"
        instruction = "Complete the task as specified."
        max_agent_timeout_sec = 1800  # Default: 30 minutes
        max_test_timeout_sec = None

        process_checks = None

        if task_yaml_path.exists():
            try:
                with open(task_yaml_path) as f:
                    task_data = yaml.safe_load(f)
                instruction = task_data.get("instruction", instruction)
                max_agent_timeout_sec = task_data.get("max_agent_timeout_sec")
                max_test_timeout_sec = task_data.get("max_test_timeout_sec")
                process_checks = task_data.get("process_checks")
            except Exception:
                pass

        # Load test_metadata.json for FAIL_TO_PASS / PASS_TO_PASS lists (Kosmos)
        fail_to_pass: list[str] = []
        pass_to_pass: list[str] = []
        test_meta_path = task_dir / "test_metadata.json"
        if test_meta_path.exists():
            try:
                with open(test_meta_path) as f:
                    meta_data = json.load(f)
                fail_to_pass = list(meta_data.get("FAIL_TO_PASS") or [])
                pass_to_pass = list(meta_data.get("PASS_TO_PASS") or [])
            except Exception:
                # Malformed metadata is non-fatal; leave lists empty.
                pass

        task_files = []

        excluded_files = {
            "run-tests.sh",
            "test.sh",
            "tests.sh",
            "run_tests.sh",
            "verify.sh",
            "solution.sh",
            "solution.yaml",
            "solution.py",
            "issues.json",
            "scraped-*.json",
            "chat.json",
            "pull_requests.json",
            "TASK_README.md",
            "espocrm-data.json",
            "medusa-seed-data.json",
            "zammad-data.json",
            "init-aws.sh",
            "task-spec.md",
            "rubric.json",
        }

        for file_path in task_dir.rglob("*"):
            try:
                relative_path = file_path.relative_to(task_dir)
                if relative_path.parts and relative_path.parts[0] == "tests":
                    continue
            except ValueError:
                continue

            if any(
                fnmatch.fnmatch(file_path.name, pattern) for pattern in excluded_files
            ):
                continue

            if (
                file_path.is_file()
                and not file_path.name.startswith(".")
                and file_path.suffix not in [".pyc", ".pyo"]
            ):
                task_files.append(file_path)

        return TaskContext(
            task_id=config.task_id,
            task_dir=task_dir,
            instruction=instruction,
            files=task_files,
            timeout=config.timeout,
            max_agent_timeout_sec=max_agent_timeout_sec,
            max_test_timeout_sec=max_test_timeout_sec,
            max_steps=getattr(config, "max_steps", None),
            process_checks=process_checks,
            run_dir=config.runs_dir / config.run_id,
            model=config.model.value if hasattr(config.model, "value") else str(config.model),
            fail_to_pass=fail_to_pass,
            pass_to_pass=pass_to_pass,
        )

    def _get_llm(
        self, model_type: ModelType, task_context: TaskContext | None = None, reasoning_effort: str | None = None
    ) -> LiteLLM:
        """Get LLM for the specified model type."""
        if model_type in self.llm_factory:
            return self.llm_factory[model_type]

        model_name = model_type.value
        return create_llm(model_name, reasoning_effort=reasoning_effort)

    def _execute_trials_parallel(
        self,
        task_context: TaskContext,
        llm: LiteLLM,
        max_trials: int,
        start_trial_num: int = 1,
        todo_tool_enabled: bool = False,
    ) -> list[TaskExecution]:
        """
        Execute trials in parallel using ThreadPoolExecutor with optimized resource usage.

        Args:
            task_context: Task context for execution
            llm: LLM to use for execution
            max_trials: Number of trials to execute
            start_trial_num: Starting trial number (for resume functionality)
            todo_tool_enabled: Whether to enable the todo tool

        Returns:
            List of TaskExecution results
        """
        runner_pool = Queue(maxsize=self.max_workers)
        for _ in range(self.max_workers):
            max_steps = task_context.max_steps
            runner_pool.put(
                MultiStepRunner(
                    llm,
                    max_steps=max_steps,
                    monitor_memory=True,
                    log_level="INFO",
                    todo_tool_enabled=todo_tool_enabled,
                )
            )

        def run_single_trial_wrapper(trial_num: int) -> TaskExecution:
            """Wrapper for single trial execution with improved error isolation."""
            runner = None

            try:
                runner = runner_pool.get()

                return runner.run_single_trial(
                    task_context=task_context,
                    trial_number=trial_num,
                    working_dir=None,
                )
            except Exception as e:
                error_context = {
                    "trial_number": trial_num,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "timestamp": datetime.now().isoformat(),
                    "thread_id": threading.current_thread().ident,
                }

                return TaskExecution(
                    trial_number=trial_num,
                    status="failed",
                    agent_response={
                        "content": "",
                        "error": str(e),
                        "context": error_context,
                    },
                    error_message=f"{type(e).__name__}: {str(e)}",
                    execution_time=0.0,
                    memory_used=0,
                    logs=[
                        f"Trial {trial_num} failed with {type(e).__name__}: {str(e)}"
                    ],
                    metadata={"error_context": error_context},
                    started_at=datetime.now().isoformat(),
                    completed_at=datetime.now().isoformat(),
                )
            finally:
                if runner:
                    try:
                        runner_pool.put(runner)
                    except Exception:
                        pass

        trials = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            future_to_trial = {
                executor.submit(run_single_trial_wrapper, trial_num): trial_num
                for trial_num in range(start_trial_num, start_trial_num + max_trials)
            }

            for future in concurrent.futures.as_completed(
                future_to_trial, timeout=task_context.timeout * 2
            ):
                trial_num = future_to_trial[future]
                try:
                    trial_result = future.result()
                    trials.append(trial_result)
                except concurrent.futures.TimeoutError:
                    timeout_trial = TaskExecution(
                        trial_number=trial_num,
                        status="timeout",
                        agent_response={
                            "content": "",
                            "error": "Trial execution timeout",
                        },
                        error_message=f"Trial {trial_num} timed out after {task_context.timeout * 2} seconds",
                        execution_time=task_context.timeout * 2,
                        memory_used=0,
                        logs=[f"Trial {trial_num} timed out"],
                        metadata={"error_type": "timeout"},
                        started_at=datetime.now().isoformat(),
                        completed_at=datetime.now().isoformat(),
                    )
                    trials.append(timeout_trial)
                except Exception as e:
                    error_trial = TaskExecution(
                        trial_number=trial_num,
                        status=ExecutionStatus.FAILED,
                        error_message=f"Unexpected error collecting trial {trial_num}: {str(e)}",
                        execution_time=0.0,
                        logs=[f"Error collecting trial {trial_num}: {str(e)}"],
                        metadata={"error_type": "collection_error"},
                        started_at=datetime.now(),
                        completed_at=datetime.now(),
                    )
                    trials.append(error_trial)

        trials.sort(key=lambda x: x.trial_number)
        return trials

    def _load_existing_trials(
        self, run_id: str, config: EvaluationConfig
    ) -> list[TaskExecution]:
        """
        Load existing trials from a previous run for resume functionality with validation.

        Args:
            run_id: Run ID to load trials from
            config: Current evaluation configuration

        Returns:
            List of existing TaskExecution results
        """
        try:
            results_file = config.runs_dir / run_id / "results.json"
            if not results_file.exists():
                logger.warning(f"Results file not found for run {run_id}")
                return []

            if not self._validate_resume_compatibility(run_id, config):
                logger.warning(f"Resume compatibility check failed for {run_id}")
                return []

            existing_trials = self._load_trials(results_file)
            validated_trials = self._validate_loaded_trials(existing_trials, config)

            logger.info(
                f"Successfully loaded {len(validated_trials)} trials from {run_id}"
            )
            return validated_trials

        except Exception as e:
            logger.warning(f"Could not load existing trials from {run_id}: {e}")
            return []

    def _validate_resume_compatibility(
        self, run_id: str, config: EvaluationConfig
    ) -> bool:
        """
        Validate that the run can be resumed with current configuration.

        Args:
            run_id: Run ID to validate
            config: Current evaluation configuration

        Returns:
            True if compatible, False otherwise
        """
        try:
            metadata_file = config.runs_dir / run_id / "metadata.json"
            if not metadata_file.exists():
                return False

            with open(metadata_file) as f:
                metadata = json.load(f)

            if metadata.get("task_id") != config.task_id:
                logger.warning(
                    f"Task ID mismatch: {metadata.get('task_id')} != {config.task_id}"
                )
                return False

            if metadata.get("model") != config.model.value:
                logger.warning(
                    f"model mismatch: {metadata.get('model')} != {config.model.value}"
                )
                return False

            old_timeout = metadata.get("timeout", 300)
            if abs(old_timeout - config.timeout) > 60:
                logger.warning(f"Timeout mismatch: {old_timeout} != {config.timeout}")
                return False

            return True

        except Exception as e:
            logger.warning(f"Resume compatibility check failed: {e}")
            return False

    def _load_trials(self, results_file: Path) -> list[TaskExecution]:
        """Standard JSON loading for smaller files."""
        with open(results_file) as f:
            results_data = json.load(f)

        existing_trials = []
        for trial_data in results_data.get("trials", []):
            try:
                trial = TaskExecution(**trial_data)
                existing_trials.append(trial)
            except Exception as e:
                logger.warning(f"Failed to parse trial data: {e}")
                continue

        return existing_trials

    def _validate_loaded_trials(
        self, trials: list[TaskExecution], config: EvaluationConfig
    ) -> list[TaskExecution]:
        """
        Validate loaded trials for consistency and completeness.

        Args:
            trials: List of loaded trials
            config: Current evaluation configuration

        Returns:
            List of validated trials
        """
        validated_trials = []

        for trial in trials:
            if not hasattr(trial, "trial_number") or trial.trial_number is None:
                logger.warning("Skipping trial with invalid trial_number")
                continue

            if not hasattr(trial, "status") or trial.status is None:
                logger.warning(
                    f"Skipping trial {trial.trial_number} with invalid status"
                )
                continue

            if trial.trial_number > config.max_trials:
                logger.warning(
                    f"Skipping trial {trial.trial_number} (exceeds max_trials {config.max_trials})"
                )
                continue

            validated_trials.append(trial)

        validated_trials.sort(key=lambda x: x.trial_number)

        return validated_trials
