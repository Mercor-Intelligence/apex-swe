"""Terminal execution tool."""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .tool import Tool
from src.utils.terminal_manager import TmuxSession
from src.utils.logging_utils import get_logger

# Ensures only one agent at a time runs tmux setup (which may involve apt-get install),
# preventing dpkg lock conflicts when multiple agents initialise simultaneously.
_tmux_init_lock = threading.Lock()


class TerminalTool(Tool):
    """Execute terminal commands inside a Docker container using tmux."""

    def __init__(self, working_dir: Path, docker_manager, session_name: str | None = None):
        """
        Initialize Docker terminal tool.

        Args:
            working_dir: Working directory for command execution
            docker_manager: DockerComposeManager instance
            session_name: Optional tmux session name override (ensures isolation between agents)
        """
        self.working_dir = working_dir
        self.docker_manager = docker_manager
        self.command_history = []
        self.tmux_session = None
        self._session_name_override = session_name
        self._initialize_tmux_session()

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def description(self) -> str:
        return "Execute terminal commands in Docker container"

    def _initialize_tmux_session(self):
        """Initialize tmux session for terminal-bench compatible logging."""
        with _tmux_init_lock:
            try:
                container = self.docker_manager.get_container()
                if container:
                    session_name = self._session_name_override or f"apex_{int(time.time())}"
                    self.tmux_session = TmuxSession(
                        session_name=session_name, container=container
                    )
                    self.tmux_session.start()

            except Exception as e:
                logger = get_logger()
                if logger:
                    logger._log(f"TmuxSession initialization failed: {e}")

    def execute(
        self, command: str, timeout: int | None = None, **kwargs
    ) -> dict[str, Any]:
        """
        Execute command in Docker container using tmux for better terminal emulation.

        Args:
            command: Command to execute
            timeout: Command timeout in seconds
            **kwargs: Additional parameters

        Returns:
            Execution result with stdout, stderr, and exit code
        """
        start_time = time.time()
        timeout = timeout or 120

        # Track command history
        self.command_history.append(
            {
                "command": command,
                "timestamp": datetime.now().isoformat(),
                "working_dir": str(self.working_dir),
            }
        )

        try:
            if self.tmux_session and self.tmux_session.is_session_alive():
                self.tmux_session.send_keys(
                    keys=[command, "Enter"],
                    block=True,
                    max_timeout_sec=float(timeout),
                )

                # Get current terminal state for the prompt (just the visible screen)
                output = self._limit_output_length(
                    self.tmux_session.capture_pane(capture_entire=False)
                )

                return {
                    "success": True,
                    "stdout": output,
                    "stderr": "",
                    "exit_code": 0,
                    "terminal_state": output,
                    "execution_time": time.time() - start_time,
                    "_metadata": {
                        "tool": "terminal",
                        "method": "tmux",
                        "container": self.docker_manager._container_name,
                    },
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "exit_code": -1,
                "execution_time": time.time() - start_time,
                "_metadata": {
                    "tool": "terminal",
                    "execution_time": time.time() - start_time,
                    "timestamp": datetime.now().isoformat(),
                    "error_type": type(e).__name__,
                },
            }

        # Fallback: tmux session not available
        return {
            "success": False,
            "error": "Terminal session not available (tmux not initialized or not alive)",
            "exit_code": -1,
            "execution_time": time.time() - start_time,
            "_metadata": {
                "tool": "terminal",
                "execution_time": time.time() - start_time,
                "timestamp": datetime.now().isoformat(),
                "error_type": "TmuxSessionNotAvailable",
            },
        }

    def _limit_output_length(self, output: str, max_bytes: int = 10000) -> str:
        """
        Limit output to specified byte length, keeping first and last portions.

        Args:
            output: The terminal output to potentially truncate
            max_bytes: Maximum allowed bytes (default 10000)

        Returns:
            str: Original output if under limit, or truncated with middle omitted
        """
        if len(output.encode("utf-8")) <= max_bytes:
            return output

        # Calculate portions (half each for first and last)
        portion_size = max_bytes // 2

        # Convert to bytes for accurate splitting
        output_bytes = output.encode("utf-8")

        # Get first portion
        first_portion = output_bytes[:portion_size].decode("utf-8", errors="ignore")

        # Get last portion
        last_portion = output_bytes[-portion_size:].decode("utf-8", errors="ignore")

        # Calculate omitted bytes
        omitted_bytes = (
            len(output_bytes)
            - len(first_portion.encode("utf-8"))
            - len(last_portion.encode("utf-8"))
        )

        return (
            f"{first_portion}\n[... output limited to {max_bytes} bytes; "
            f"{omitted_bytes} interior bytes omitted ...]\n{last_portion}"
        )

    def cleanup(self):
        """Clean up tmux session when done."""
        if self.tmux_session:
            try:
                self.tmux_session.cleanup()
            except:
                pass
