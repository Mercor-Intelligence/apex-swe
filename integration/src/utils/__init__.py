"""APEX SWE Harness Utilities.

Essential utilities including LLM callers, logging, Docker management, and terminal management.
"""

from .llm import LiteLLM, create_llm
from .logging_utils import (
    ApexLogger,
    TaskLogger,
    get_logger,
    init_apex_logger,
)
from .docker_manager import (
    DockerComposeManager,
    docker_environment,
    check_docker,
    get_docker_info,
)
from .terminal_manager import TerminalSessionManager
from .prompt_utils import build_episode_prompt, build_initial_prompt
from .harness_utils import (
    format_results,
    setup_task_environment,
    cleanup_environment,
)

__all__ = [
    "LiteLLM",
    "create_llm",
    "ApexLogger",
    "TaskLogger",
    "get_logger",
    "init_apex_logger",
    "DockerComposeManager",
    "docker_environment",
    "check_docker",
    "get_docker_info",
    "TerminalSessionManager",
    "build_episode_prompt",
    "build_initial_prompt",
    "format_results",
    "setup_task_environment",
    "cleanup_environment",
]
