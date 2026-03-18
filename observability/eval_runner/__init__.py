"""
Evaluation Runner - Run model evaluations and score results.

This module provides:
1. Agent execution via inspect-ai
2. Scoring via the parser module (Docker-based test execution)
3. Health checks and retry utilities

Usage:
    from eval_runner import run_evaluation_sync, MODELS, get_all_task_ids
    
    # Run evaluation
    result = run_evaluation_sync(task_id="my-task", model="claude-opus-4-5")
"""

from eval_runner.config import (
    # Models
    MODELS,
    DEFAULT_MODEL,
    # Reasoning
    REASONING_EFFORT_LEVELS,
    ANTHROPIC_REASONING_TOKENS,
    DEFAULT_REASONING_EFFORT,
    # Task config
    get_all_task_ids,
    load_task_config,
    # Paths
    TASKS_DIR,
    # Health checks
    validate_health_checks,
)
from eval_runner.runner import (
    run_evaluation_sync,
    run_agent_sync,
    E2EResult,
    AgentRunResult,
)
from eval_runner.logger import (
    get_logger,
    set_log_level,
)

__all__ = [
    # Models
    "MODELS",
    "DEFAULT_MODEL",
    # Reasoning
    "REASONING_EFFORT_LEVELS",
    "ANTHROPIC_REASONING_TOKENS",
    "DEFAULT_REASONING_EFFORT",
    # Task config
    "get_all_task_ids",
    "load_task_config",
    # Paths
    "TASKS_DIR",
    # Health checks
    "validate_health_checks",
    # Runner
    "run_evaluation_sync",
    "run_agent_sync",
    "E2EResult",
    "AgentRunResult",
    # Logging
    "get_logger",
    "set_log_level",
]
