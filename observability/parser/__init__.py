"""
Parser Module - Test output parsing and F2P/P2P generation.

This module provides:
1. Test output parsers for 20+ frameworks (pytest, jest, go, vitest, etc.)
2. Docker-based test execution
3. F2P/P2P (FAIL_TO_PASS / PASS_TO_PASS) list generation

Usage:
    from parser import TaskEvaluator, TaskConfig
    
    config = TaskConfig.from_task_dir("tasks/my-task", "my-image:latest")
    
    evaluator = TaskEvaluator(verbose=True)
    result = evaluator.generate_f2p_p2p(config)
    print(f"F2P: {result.fail_to_pass}")
    print(f"P2P: {result.pass_to_pass}")

Note: Agent evaluation is handled by eval_runner/inspect_scorer.py which runs
tests inside the inspect-ai sandbox with full Docker Compose support.
"""

from .evaluator import TaskEvaluator, TaskConfig, F2PP2PResult
from .parsing_utils import parse_test_output, normalize_test_id, parse_compact_format
from .frameworks import get_framework_config, get_test_command_with_output
from .eval_utils import (
    TaskInstance,
    TestResults,
    generate_grading_setup_script,
    generate_test_run_script,
    parse_test_results,
    generate_grading_explanation,
    parse_raw_test_output,
    load_task_yaml,
)
from .docker_runner import DockerRunner

__all__ = [
    # Main API
    "TaskEvaluator",
    "TaskConfig",
    "F2PP2PResult",
    "DockerRunner",
    # Utilities
    "TaskInstance",
    "TestResults",
    "parse_test_output",
    "parse_raw_test_output",
    "parse_compact_format",
    "normalize_test_id",
    "get_framework_config",
    "get_test_command_with_output",
    "generate_grading_setup_script",
    "generate_test_run_script",
    "parse_test_results",
    "generate_grading_explanation",
    "load_task_yaml",
]
