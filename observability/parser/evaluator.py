"""
F2P/P2P Generator for SWE-Bench Extended tasks.

This module provides the TaskEvaluator class for generating FAIL_TO_PASS and
PASS_TO_PASS test lists by comparing test results before and after applying
the golden patch.

Note: Agent evaluation is handled by eval_runner/inspect_scorer.py which runs
tests inside the inspect-ai sandbox with full Docker Compose support.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .docker_runner import DockerRunner

logger = logging.getLogger(__name__)
from .eval_utils import load_task_instance, load_task_yaml
from .parsing_utils import parse_test_output


@dataclass
class TaskConfig:
    """Configuration for a single evaluation task."""

    task_id: str
    docker_image: str
    test_command: str
    test_framework: str
    test_patch: str
    golden_patch: str
    test_files: list[str] = field(default_factory=list)
    fail_to_pass: list[str] | None = None
    pass_to_pass: list[str] | None = None
    language: str = ""
    problem_statement: str = ""
    prompt_statement: str = ""
    timeout: int = 600
    workdir: str | None = None  # Working directory in container (auto-detected from test_command if not set)
    task_dir: Path | None = None  # Path to task directory (for auto-building Docker images)
    requires_compose: bool = False  # If True, use docker compose exec instead of docker run (for tasks needing services like Redis)

    @classmethod
    def from_task_dir(cls, task_dir: Path | str, docker_image: str) -> "TaskConfig":
        """
        Create a TaskConfig from a task directory.

        Args:
            task_dir: Path to the task directory containing test_metadata.json, patches, etc.
            docker_image: Docker image to use for evaluation

        Returns:
            TaskConfig instance
        """
        task_dir = Path(task_dir)
        instance = load_task_instance(task_dir)
        
        # Load task.yaml for additional config (uses shared helper)
        task_yaml = load_task_yaml(task_dir)
        requires_compose = task_yaml.get("requires_compose", False)
        
        return cls(
            task_id=instance.task_id,
            docker_image=docker_image,
            test_command=instance.test_command,
            test_framework=instance.test_framework,
            test_patch=instance.test_patch,
            golden_patch=instance.golden_patch,
            test_files=instance.test_files,
            fail_to_pass=instance.fail_to_pass if instance.fail_to_pass else None,
            pass_to_pass=instance.pass_to_pass if instance.pass_to_pass else None,
            language=instance.language,
            problem_statement=instance.problem_statement,
            prompt_statement=instance.prompt_statement,
            task_dir=task_dir,
            requires_compose=requires_compose,
        )


@dataclass
class F2PP2PResult:
    """Result of generating F2P/P2P lists."""

    task_id: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    pre_patch_results: dict[str, str]
    post_patch_results: dict[str, str]
    pre_output: str
    post_output: str
    error: str | None = None
    pre_exit_code: int | None = None  # Exit code from baseline test run
    post_exit_code: int | None = None  # Exit code from golden patch test run


class TaskEvaluator:
    """
    F2P/P2P generator for SWE-Bench Extended tasks.

    This class generates FAIL_TO_PASS and PASS_TO_PASS test lists by:
    1. Running tests WITHOUT golden patch (baseline)
    2. Running tests WITH golden patch + test patch
    3. Computing F2P/P2P by comparing results

    Example usage:
        evaluator = TaskEvaluator(verbose=True)
        f2p_result = evaluator.generate_f2p_p2p(config)
    """

    def __init__(self, verbose: bool = False, workdir: str = "/app/repo"):
        """
        Initialize the TaskEvaluator.

        Args:
            verbose: Whether to print verbose output during evaluation
            workdir: Working directory inside Docker containers (default: /app/repo)
        """
        self.verbose = verbose
        self.workdir = workdir

    def _log(self, message: str, task_id: str = ""):
        """Log a message if verbose is enabled."""
        if self.verbose:
            prefix = f"[{task_id}] " if task_id else ""
            logger.info(f"{prefix}{message}")

    def _detect_workdir(self, test_command: str) -> str:
        """Detect workdir from test command if it starts with 'cd /path && ...'."""
        match = re.match(r'^cd\s+(/[^\s&]+)\s*&&', test_command)
        if match:
            return match.group(1)
        return self.workdir

    def _get_workdir(self, config: TaskConfig) -> str:
        """Get workdir from config or detect from test command."""
        if config.workdir:
            return config.workdir
        return self._detect_workdir(config.test_command)

    def _get_compose_path(self, config: TaskConfig) -> Path | None:
        """Get compose.yaml path from task config for auto-building Docker images."""
        if config.task_dir:
            # Check for compose.yaml or docker-compose.yaml
            for filename in ["compose.yaml", "docker-compose.yaml", "compose.yml", "docker-compose.yml"]:
                compose_path = config.task_dir / filename
                if compose_path.exists():
                    return compose_path
        return None

    def generate_f2p_p2p(self, config: TaskConfig) -> F2PP2PResult:
        """
        Generate FAIL_TO_PASS and PASS_TO_PASS test lists.

        This method:
        1. Runs tests WITHOUT golden patch (pre-patch)
        2. Runs tests WITH golden patch + test patch (post-patch)
        3. Computes F2P/P2P by comparing results

        F2P = Tests that FAILED in pre-patch but PASSED in post-patch
              + New tests that only exist in post-patch and PASSED
        P2P = Tests that PASSED in both pre-patch and post-patch

        Args:
            config: TaskConfig with test information

        Returns:
            F2PP2PResult with generated F2P/P2P lists and intermediate results
        """
        self._log(f"Generating F2P/P2P for {config.task_id}", config.task_id)

        # Get workdir from config or detect from test command
        workdir = self._get_workdir(config)
        self._log(f"Using workdir: {workdir}", config.task_id)

        runner = DockerRunner(config.docker_image, workdir=workdir, timeout=config.timeout)

        # Step 1: Pull or build image
        compose_path = self._get_compose_path(config)
        self._log(f"Ensuring Docker image is available (compose: {compose_path})...", config.task_id)
        pull_result = runner.pull_image(compose_path=compose_path)
        if not pull_result.success:
            return F2PP2PResult(
                task_id=config.task_id,
                fail_to_pass=[],
                pass_to_pass=[],
                pre_patch_results={},
                post_patch_results={},
                pre_output="",
                post_output="",
                error=f"Failed to pull image: {pull_result.stderr}",
            )

        # Step 2: Run pre-patch tests (only test.patch, no golden)
        self._log("Running pre-patch tests...", config.task_id)
        
        # Use compose-based execution if task requires services (like Redis)
        if config.requires_compose and compose_path:
            self._log("Using docker compose exec (task requires services)", config.task_id)
            pre_result = runner.run_with_compose(
                compose_path=compose_path,
                test_command=config.test_command,
                test_patch=config.test_patch,
                golden_patch=None,  # No golden patch for pre-test
                test_framework=config.test_framework,
            )
        else:
            pre_result = runner.run_with_patches(
                test_command=config.test_command,
                test_patch=config.test_patch,
                golden_patch=None,  # No golden patch for pre-test
                test_framework=config.test_framework,
            )
        pre_output = pre_result.output

        # Step 3: Run post-patch tests (test.patch + golden.patch)
        self._log("Running post-patch tests...", config.task_id)
        if config.requires_compose and compose_path:
            post_result = runner.run_with_compose(
                compose_path=compose_path,
                test_command=config.test_command,
                test_patch=config.test_patch,
                golden_patch=config.golden_patch,
                test_framework=config.test_framework,
            )
        else:
            post_result = runner.run_with_patches(
                test_command=config.test_command,
                test_patch=config.test_patch,
                golden_patch=config.golden_patch,
                test_framework=config.test_framework,
            )
        post_output = post_result.output

        # Step 4: Parse results
        self._log("Parsing results...", config.task_id)
        pre_parsed = parse_test_output(pre_output, config.test_framework) or {}
        post_parsed = parse_test_output(post_output, config.test_framework) or {}

        self._log(
            f"Pre: {len(pre_parsed)} tests, Post: {len(post_parsed)} tests",
            config.task_id,
        )

        # Step 5: Calculate F2P and P2P
        # F2P: Tests that failed in pre but passed in post
        f2p_tests = [
            t
            for t in pre_parsed
            if pre_parsed[t] == "FAILED" and post_parsed.get(t) == "PASSED"
        ]

        # Also include new passing tests (tests that only exist in post-patch)
        new_passing = [
            t
            for t in post_parsed
            if t not in pre_parsed and post_parsed[t] == "PASSED"
        ]
        f2p_tests.extend(new_passing)

        # P2P: Tests that passed in both
        p2p_tests = [
            t
            for t in pre_parsed
            if pre_parsed[t] == "PASSED" and post_parsed.get(t) == "PASSED"
        ]

        self._log(f"F2P: {len(f2p_tests)}, P2P: {len(p2p_tests)}", config.task_id)

        return F2PP2PResult(
            task_id=config.task_id,
            fail_to_pass=f2p_tests,
            pass_to_pass=p2p_tests,
            pre_patch_results=pre_parsed,
            post_patch_results=post_parsed,
            pre_output=pre_output,
            post_output=post_output,
            pre_exit_code=pre_result.exit_code,
            post_exit_code=post_result.exit_code,
        )
