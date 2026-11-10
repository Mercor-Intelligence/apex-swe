"""Terminal session management for interactive agent environments - Apex-Code evaluation system."""

import base64
import io
import logging
import re
import tarfile
import time
from pathlib import Path
from typing import Any

from docker.models.containers import Container, ExecResult
from pydantic import BaseModel, Field, field_validator

from .docker_manager import DockerComposeManager, get_docker_pool
from .logging_utils import get_logger

logger = logging.getLogger(__name__)


def convert_heredoc_to_python(command: str) -> str | None:
    """Convert a heredoc command to a Python-based file write.

    Handles patterns like:
    - cat > file << 'EOF' ... EOF
    - cat >> file << EOF ... EOF
    - cat << 'EOF' > file ... EOF
    - Also handles 2>&1 suffix and commands after the heredoc

    Returns the converted command or None if conversion failed.
    """
    # Skip if this looks like sed/grep/awk with << in arguments (false positive)
    if re.match(r"^\s*(sed|grep|awk)\s", command):
        return None

    # Pattern 1: cat > file << 'DELIM' ... DELIM [2>&1] [more commands]
    # Note: No $ anchor - allows commands after heredoc
    pattern1 = r"cat\s+(>{1,2})\s*([^\s<]+)\s*<<\s*[-]?['\"]?(\w+)['\"]?\s*\n(.*?)\n\3(?:\s*2>&1)?"
    match1 = re.search(pattern1, command, re.DOTALL)

    if match1:
        redirect_type = match1.group(1)  # > or >>
        filepath = match1.group(2)
        content = match1.group(4)
        mode = "a" if redirect_type == ">>" else "w"

        # Get any commands that come after the heredoc
        heredoc_end = match1.end()
        after_heredoc = command[heredoc_end:].strip()

        # Escape content for Python using base64 to handle any content safely
        encoded = base64.b64encode(content.encode()).decode()
        python_cmd = f'python3 -c \'import base64; open("{filepath}", "{mode}").write(base64.b64decode("{encoded}").decode())\''

        # Append any commands that came after the heredoc
        if after_heredoc:
            return f"{python_cmd}; {after_heredoc}"
        return python_cmd

    # Pattern 2: cat << 'DELIM' > file ... DELIM [2>&1] [more commands]
    pattern2 = r"cat\s*<<\s*[-]?['\"]?(\w+)['\"]?\s*(>{1,2})\s*([^\s\n]+)\s*\n(.*?)\n\1(?:\s*2>&1)?"
    match2 = re.search(pattern2, command, re.DOTALL)

    if match2:
        redirect_type = match2.group(2)
        filepath = match2.group(3)
        content = match2.group(4)
        mode = "a" if redirect_type == ">>" else "w"

        heredoc_end = match2.end()
        after_heredoc = command[heredoc_end:].strip()

        encoded = base64.b64encode(content.encode()).decode()
        python_cmd = f'python3 -c \'import base64; open("{filepath}", "{mode}").write(base64.b64decode("{encoded}").decode())\''

        if after_heredoc:
            return f"{python_cmd}; {after_heredoc}"
        return python_cmd

    pattern3 = r"cat\s*<<\s*[-]?['\"]?(\w+)['\"]?\s*\n(.*?)\n\1(?:\s*2>&1)?"
    match3 = re.search(pattern3, command, re.DOTALL)

    if match3:
        content = match3.group(2)

        heredoc_end = match3.end()
        after_heredoc = command[heredoc_end:].strip()

        encoded = base64.b64encode(content.encode()).decode()
        python_cmd = f"python3 -c 'import base64; print(base64.b64decode(\"{encoded}\").decode())'"

        if after_heredoc:
            return f"{python_cmd}; {after_heredoc}"
        return python_cmd

    return None


def fix_heredoc_command(command: str) -> str:
    """Fix heredoc commands by converting them to safer alternatives.

    If conversion fails, handles incomplete heredocs gracefully to prevent
    terminal hangs that would block subsequent commands.
    """
    if "<<" not in command:
        return command

    # Skip if this looks like sed/grep/awk with << in arguments (false positive)
    if re.match(r"^\s*(sed|grep|awk)\s", command):
        return command

    # Check for heredoc patterns
    heredoc_pattern = r"<<\s*[-]?['\"]?(\w+)['\"]?"
    match = re.search(heredoc_pattern, command)

    if not match:
        return command

    delimiter = match.group(1)

    # Try to convert to Python
    converted = convert_heredoc_to_python(command)
    if converted:
        logger.info(f"Converted heredoc to Python command: {converted[:100]}...")
        return converted

    # Check if the closing delimiter is present
    # Look for delimiter on its own line (possibly followed by 2>&1)
    closing_pattern = rf"(?:^|\n){delimiter}(?:\s*2>&1)?"
    if re.search(closing_pattern, command):
        # Heredoc appears to be closed - ensure proper newline handling
        if not command.endswith("\n"):
            command = command + "\n"
        logger.debug("Fixed heredoc newline handling")
        return command

    # INCOMPLETE HEREDOC DETECTED - delimiter never appears after <<
    # This would hang the terminal waiting for EOF forever
    # Convert to a safe failing command that won't block
    logger.warning(
        f"Incomplete heredoc detected (missing '{delimiter}'). Converting to safe error."
    )

    # Extract what the command was trying to do
    # Common patterns: cat > file <<EOF, cat <<EOF > file
    file_match = re.search(r"cat\s+(?:>{1,2})\s*([^\s<]+)", command)
    if not file_match:
        file_match = re.search(r"cat\s*<<[^>]+(>{1,2})\s*([^\s]+)", command)

    if file_match:
        # There was a file target - create an error message in the file
        filepath = (
            file_match.group(1) if file_match.lastindex == 1 else file_match.group(2)
        )
        error_msg = (
            f"ERROR: Incomplete heredoc - missing closing delimiter '{delimiter}'"
        )
        return f"echo '{error_msg}' && echo 'Heredoc was incomplete - please use python3 or printf to write files instead of heredocs' >&2 && false"
    else:
        # No file target - just echo error
        return f"echo 'ERROR: Incomplete heredoc (missing {delimiter}). Use python3 or printf instead.' >&2 && false"


# Constants for terminal management
class TerminalConstants:
    """Terminal-related constants."""

    DEFAULT_SHELL = "/bin/bash"
    DEFAULT_TIMEOUT = 30
    SESSION_TIMEOUT = 3600  # 1 hour
    BUFFER_SIZE = 4096
    MAX_SESSION_HISTORY = 1000
    TMUX_COMPLETION_COMMAND = "; echo CMD_EXIT:$?; tmux wait -S done"
    ENTER_KEYS = {"Enter", "C-m", "KPEnter", "C-j", "^M", "^J"}
    ENDS_WITH_NEWLINE_PATTERN = r"[\r\n]$"
    NEWLINE_CHARS = "\r\n"


class TerminalCommand(BaseModel):
    """Terminal command with execution parameters."""

    command: str
    min_timeout_sec: float = 0.0
    max_timeout_sec: float = 180.0
    block: bool = False
    append_enter: bool = True


class TerminalSessionMetadata(BaseModel):
    """Metadata for terminal session management."""

    session_id: str
    container_name: str
    shell: str = TerminalConstants.DEFAULT_SHELL
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    last_activity: str = Field(
        default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S")
    )
    is_active: bool = True
    command_history: list[str] = Field(default_factory=list)

    @field_validator("session_id", "container_name")
    @classmethod
    def validate_identifiers(cls, v):
        """Validate session and container identifiers."""
        if not v or not v.strip():
            raise ValueError("Identifier cannot be empty")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Identifier must be alphanumeric with optional _ or -")
        return v


class TerminalOutput(BaseModel):
    """Terminal command output."""

    command: str
    stdout: str
    stderr: str
    return_code: int
    execution_time: float
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class TmuxSession:
    """Manages a single tmux session within a Docker container - Apex-Code evaluation system."""

    def __init__(
        self,
        session_name: str,
        container: Container,
        commands_path: Path | None = None,
        disable_recording: bool = False,
        user: str = "",
    ):
        """Initialize tmux session."""
        self.container = container
        self._session_name = session_name
        self._commands_path = commands_path
        self._disable_recording = disable_recording
        self._user = user
        self._asciinema_markers = []
        self._previous_buffer: str | None = None

        # Heredoc state tracking - for detecting fragmented heredocs sent line by line
        self._heredoc_active = False
        self._heredoc_delimiter: str | None = None
        self._heredoc_lines: list[str] = []
        self._heredoc_start_command: str | None = None

        # Verify tmux is available
        result = self._exec_run(["tmux", "-V"])
        if result.exit_code != 0:
            # Try to install tmux automatically
            logger.warning("tmux not found, attempting to install...")
            # First try apt-get (Debian/Ubuntu)
            update_result = self._exec_run(["apt-get", "update"])
            if update_result.exit_code == 0:
                install_result = self._exec_run(["apt-get", "install", "-y", "tmux"])
                if install_result.exit_code == 0:
                    logger.info("Successfully installed tmux using apt-get")
                else:
                    raise RuntimeError(
                        f"Failed to install tmux with apt-get: {install_result.output.decode('utf-8', errors='replace')[:200]}"
                    )
            else:
                # Try apk (Alpine)
                install_result2 = self._exec_run(["apk", "add", "tmux"])
                if install_result2.exit_code == 0:
                    logger.info("Successfully installed tmux using apk")
                else:
                    raise RuntimeError(
                        f"tmux is not installed and could not be installed automatically. "
                        f"Tried apt-get and apk. Original error: {result.output.decode('utf-8', errors='replace')[:200]}"
                    )

            # Verify installation worked
            verify_result = self._exec_run(["tmux", "-V"])
            if verify_result.exit_code != 0:
                raise RuntimeError(
                    "tmux installation failed - still not available after install"
                )

        # Initialize metadata
        self.metadata = TerminalSessionMetadata(
            session_id=session_name,
            container_name=container.name,
        )

    @classmethod
    def from_container_name(
        cls, session_name: str, container_name: str
    ) -> "TmuxSession":
        """Create session from container name."""

        client = get_docker_pool().get_connection()
        try:
            container = client.containers.get(container_name)
            return cls(session_name=session_name, container=container)
        finally:
            get_docker_pool().return_connection(client)

    @property
    def session_name(self) -> str:
        """Get the session name."""
        return self._session_name

    @property
    def logging_path(self) -> Path:
        """Get logging path for this session."""
        return Path("/logs") / f"{self._session_name}.log"

    @property
    def _recording_path(self) -> Path | None:
        """Get recording path for this session."""
        if self._disable_recording:
            return None
        return Path("/logs") / f"{self._session_name}.cast"

    @property
    def _tmux_start_session(self) -> list[str]:
        """Get tmux start session command."""
        return [
            "bash",
            "-c",
            (
                f"tmux new-session -x 160 -y 40 -d -s {self._session_name} \\; "
                f"pipe-pane -t {self._session_name} "
                f'"cat > {self.logging_path}"'
            ),
        ]

    def _tmux_send_keys(self, keys: list[str]) -> list[str]:
        """Get tmux send-keys command."""
        return [
            "tmux",
            "send-keys",
            "-t",
            self._session_name,
            *keys,
        ]

    def _tmux_capture_pane(self, capture_entire: bool = False) -> list[str]:
        """Get tmux capture-pane command."""
        if capture_entire:
            extra_args = ["-S", "-"]
        else:
            extra_args = []

        return [
            "tmux",
            "capture-pane",
            "-p",
            *extra_args,
            "-t",
            self._session_name,
        ]

    def start(self) -> None:
        """Start the tmux session."""
        # Ensure logs directory exists before starting tmux session
        logs_dir = self.logging_path.parent
        mkdir_result = self._exec_run(["mkdir", "-p", str(logs_dir)])
        if mkdir_result.exit_code != 0:
            logger.warning(
                f"Failed to create logs directory {logs_dir}: {mkdir_result.output.decode('utf-8', errors='replace')[:200]}"
            )

        # Start the tmux session
        start_result = self._exec_run(self._tmux_start_session)
        if start_result.exit_code != 0:
            raise RuntimeError(
                f"Failed to start tmux session {self._session_name}: {start_result.output.decode('utf-8', errors='replace')[:200]}"
            )

        # Wait a moment for session to initialize
        time.sleep(0.5)

        # Source MCP config file to make environment variables available
        try:
            # Check if MCP config file exists and source it
            check_result = self._exec_run(["test", "-f", "/config/mcp-config.txt"])
            if check_result.exit_code == 0:
                # Source the MCP config file in the tmux session
                source_result = self._exec_run(
                    [
                        "tmux",
                        "send-keys",
                        "-t",
                        self._session_name,
                        ". /config/mcp-config.txt",
                        "Enter",
                    ]
                )
                if source_result.exit_code == 0:
                    logger.debug(f"Sourced MCP config in session {self._session_name}")
                else:
                    logger.warning(
                        f"Failed to source MCP config: {source_result.output.decode('utf-8', errors='replace')[:200]}"
                    )
            else:
                logger.debug("MCP config file not found, skipping sourcing")
        except Exception as e:
            logger.warning(f"Failed to source MCP config: {e}")

        # Verify session is actually running and responsive
        if not self.is_session_alive():
            raise RuntimeError(
                f"Tmux session {self._session_name} failed to start properly"
            )

        # Give it another moment to be fully responsive
        time.sleep(0.5)
        if not self.is_session_responsive():
            logger.warning(
                f"Session {self._session_name} started but may not be fully responsive"
            )

        if self._recording_path:
            logger.debug("Starting recording.")
            self.send_keys(
                keys=[
                    f"asciinema rec --stdin {self._recording_path}",
                    "Enter",
                ],
                min_timeout_sec=3.0,
            )
            self.send_keys(
                keys=[
                    "clear",
                    "Enter",
                ],
            )

        self.metadata.is_active = True
        logger.info(f"Tmux session {self._session_name} started and validated")

    def stop(self) -> None:
        """Stop the tmux session."""
        if self._recording_path:
            logger.debug("Stopping recording.")
            self.send_keys(
                keys=["C-d"],
                min_timeout_sec=0.1,
            )

        self.metadata.is_active = False
        logger.info(f"Tmux session {self._session_name} stopped")

    def copy_session_logs_to_host(
        self, host_sessions_dir: Path, session_type: str = "agent"
    ) -> dict[str, Path | None]:
        """Copy session logs from container to host with terminal-bench compatible naming.

        Args:
            host_sessions_dir: Host directory to copy session logs to
            session_type: Type of session ("agent" or "test") for naming

        Returns:
            Dict with paths to copied log and cast files
        """

        host_sessions_dir.mkdir(parents=True, exist_ok=True)
        result = {"log_file": None, "cast_file": None}

        def clean_ansi_sequences(content: bytes) -> bytes:
            """Remove ANSI escape sequences for readable logs."""
            text = content.decode("utf-8", errors="replace")
            # Remove ANSI color codes and terminal control sequences
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            text = ansi_escape.sub("", text)
            text = re.sub(r"\[?\?[0-9]+[hl]", "", text)  # Remove mode switching
            return text.encode("utf-8")

        def copy_file_from_container(
            container_path: Path, host_path: Path, clean_content: bool = False
        ) -> bool:
            """Helper to copy file from container to host."""
            try:
                if self._exec_run(["test", "-f", str(container_path)]).exit_code != 0:
                    return False

                archive_result = self.container.get_archive(str(container_path))
                if not archive_result:
                    return False

                tar_stream, _ = archive_result
                tar_data = b"".join(tar_stream)

                with tarfile.open(fileobj=io.BytesIO(tar_data)) as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            file_content = tar.extractfile(member)
                            if file_content:
                                content = file_content.read()
                                if clean_content:
                                    content = clean_ansi_sequences(content)

                                with open(host_path, "wb") as f:
                                    f.write(content)
                                return True
                return False
            except Exception as e:
                logger.warning(f"Failed to copy {container_path}: {e}")
                return False

        try:
            # Copy session log (cleaned for readability)
            host_log_path = host_sessions_dir / f"{session_type}.log"
            if copy_file_from_container(
                self.logging_path, host_log_path, clean_content=True
            ):
                result["log_file"] = host_log_path
                logger.debug(f"Copied session log to {host_log_path}")

            # Copy asciinema recording (keep raw for playback)
            if self._recording_path:
                host_cast_path = host_sessions_dir / f"{session_type}.cast"
                if copy_file_from_container(
                    self._recording_path, host_cast_path, clean_content=False
                ):
                    result["cast_file"] = host_cast_path
                    logger.debug(f"Copied session recording to {host_cast_path}")

        except Exception as e:
            logger.warning(f"Failed to copy session logs for {self._session_name}: {e}")

        return result

    def save_pane_capture(
        self, host_panes_dir: Path, filename: str, capture_entire: bool = True
    ) -> Path | None:
        """Capture and save terminal pane content with clean formatting.

        Args:
            host_panes_dir: Host directory to save pane captures
            filename: Output filename (e.g., 'pre-agent.txt')
            capture_entire: Whether to capture entire scrollback history

        Returns:
            Path to saved file or None if failed
        """

        def clean_terminal_content(content: str) -> str:
            """Clean terminal content for human readability."""
            # Remove ANSI escape sequences and terminal control codes
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            content = ansi_escape.sub("", content)
            content = re.sub(r"\[?\?[0-9]+[hl]", "", content)  # Mode switching
            return content

        try:
            host_panes_dir.mkdir(parents=True, exist_ok=True)

            # Capture and clean pane content
            raw_content = self.capture_pane(capture_entire=capture_entire)
            clean_content = clean_terminal_content(raw_content)

            # Save to file
            host_pane_path = host_panes_dir / filename
            host_pane_path.write_text(clean_content, encoding="utf-8")

            logger.debug(f"Saved pane capture: {filename} ({len(clean_content)} chars)")
            return host_pane_path

        except Exception as e:
            logger.warning(f"Failed to save pane capture {filename}: {e}")
            return None

    def _is_enter_key(self, key: str) -> bool:
        """Check if key is an enter key."""
        return key in TerminalConstants.ENTER_KEYS

    def _ends_with_newline(self, key: str) -> bool:
        """Check if key ends with newline."""
        result = re.search(TerminalConstants.ENDS_WITH_NEWLINE_PATTERN, key)
        return result is not None

    def _is_executing_command(self, key: str) -> bool:
        """Check if key executes a command."""
        return self._is_enter_key(key) or self._ends_with_newline(key)

    def _prevent_execution(self, keys: list[str]) -> list[str]:
        """Prevent command execution by removing enter keys."""
        keys = keys.copy()
        while keys and self._is_executing_command(keys[-1]):
            if self._is_enter_key(keys[-1]):
                keys.pop()
            else:
                stripped_key = keys[-1].rstrip(TerminalConstants.NEWLINE_CHARS)
                if stripped_key:
                    keys[-1] = stripped_key
                else:
                    keys.pop()
        return keys

    def _prepare_keys(
        self,
        keys: str | list[str],
        block: bool,
    ) -> tuple[list[str], bool]:
        """Prepare keys for sending to the terminal."""
        if isinstance(keys, str):
            keys = [keys]

        if not block or not keys or not self._is_executing_command(keys[-1]):
            return keys, False

        keys = self._prevent_execution(keys)

        # Execute command and always send completion signal afterward
        if keys:
            # Preserve newlines in multi-line commands by joining with newlines
            command = "\n".join(keys)

            # FRAGMENTED HEREDOC DETECTION: Check if this looks like a heredoc start
            # without the closing delimiter (model sending line by line)
            # Pattern matches: "cmd <<DELIM", "cmd << 'DELIM'", "cmd <<-DELIM", etc.
            heredoc_start_pattern = r"^(\w+)\s+<<\s*[-]?['\"]?(\w+)['\"]?\s*$"
            heredoc_start_match = re.match(heredoc_start_pattern, command.strip())

            if heredoc_start_match and not self._heredoc_active:
                # This is a heredoc START command (e.g., "apply_patch <<'PATCH'")
                self._heredoc_active = True
                self._heredoc_delimiter = heredoc_start_match.group(2)
                self._heredoc_start_command = command.strip()
                self._heredoc_lines = []
                logger.warning(
                    f"Detected fragmented heredoc start: {command[:50]}... delimiter={self._heredoc_delimiter}"
                )
                # Send the command but DON'T wait for completion (heredoc is open)
                return [command, "Enter"], False

            if self._heredoc_active:
                # We're in the middle of a fragmented heredoc
                line = command.strip()

                # Check if this line IS the closing delimiter
                if line == self._heredoc_delimiter:
                    # Close the heredoc
                    logger.info(
                        f"Heredoc closed with delimiter: {self._heredoc_delimiter}"
                    )
                    self._heredoc_active = False
                    self._heredoc_delimiter = None
                    self._heredoc_lines = []
                    self._heredoc_start_command = None
                    # Send the closing delimiter and THEN wait for completion
                    return [line + "\n; echo CMD_EXIT:$?; tmux wait -S done", "Enter"], True
                else:
                    # This is heredoc content - just send it, don't wait
                    self._heredoc_lines.append(line)
                    return [command, "Enter"], False

            # HEREDOC HANDLING: Try to convert heredocs to safer alternatives
            if "<<" in command:
                original_command = command
                command = fix_heredoc_command(command)
                if command != original_command:
                    logger.info("Heredoc command was converted/fixed")

            # Use a more robust wrapping approach that works with complex commands
            # Create a wrapper that handles all edge cases and always sends completion signal
            # Use a temporary file approach for very complex commands to avoid shell parsing issues
            # Check if command contains MCP server calls that don't work well with tmux wait
            # MCP servers (mcp-loki, mcp-prometheus) handle their own completion and hang with tmux wait
            if "mcp-loki" in command or "mcp-prometheus" in command:
                # Skip tmux wait for MCP commands - they handle their own I/O completion
                return [command, "Enter"], True

            if (
                len(command) > 8000
                or command.count('"') > 20
                or command.count("'") > 20
            ):
                # For very complex commands, use base64 encoding to safely pass any content
                encoded_cmd = base64.b64encode(command.encode()).decode()
                tmp_script = f"/tmp/tmux_cmd_{self._session_name}.sh"
                wrapped_command = (
                    f"python3 -c 'import base64; open(\"{tmp_script}\", \"w\").write(base64.b64decode(\"{encoded_cmd}\").decode())' && "
                    f"chmod +x {tmp_script} && {tmp_script}; echo CMD_EXIT:$?; tmux wait -S done"
                )
                # Return the wrapped command - completion signal is already included
                return [wrapped_command, "Enter"], True
            else:
                # Check if this is still a heredoc command (conversion may have failed)
                if "<<" in command:
                    # Find heredoc delimiter pattern: <<EOF, <<'EOF', <<"EOF", <<-EOF, etc.
                    heredoc_pattern = r"<<[-]?['\"]?(\w+)['\"]?"
                    match = re.search(heredoc_pattern, command)
                    if match:
                        delimiter = match.group(1)
                        # Check if command contains the closing delimiter on its own line
                        closing_pattern = rf"(?:^|\n){delimiter}\s*$"
                        if re.search(closing_pattern, command):
                            # Properly closed heredoc - ensure delimiter is followed by newline
                            # before appending completion command
                            if not command.endswith("\n"):
                                command = command + "\n"
                            return [command + "; echo CMD_EXIT:$?; tmux wait -S done", "Enter"], True
                    # Heredoc not properly closed or pattern not matched - send as-is
                    # and hope for the best (will likely timeout)
                    logger.warning("Heredoc could not be converted and may timeout")
                    return [command, "Enter", "echo CMD_EXIT:$?; tmux wait -S done", "Enter"], True
                else:
                    # For normal commands, append completion command with semicolon
                    return [command, "; echo CMD_EXIT:$?; tmux wait -S done", "Enter"], True

        keys.extend([TerminalConstants.TMUX_COMPLETION_COMMAND, "Enter"])
        return keys, True

    def send_blocking_keys(
        self,
        keys: list[str],
        min_timeout_sec: float = 0.0,
        max_timeout_sec: float = 180.0,
    ) -> dict[str, Any]:
        """Send blocking keys to tmux session (for compatibility).

        Note: This method exists for API compatibility but delegates to send_keys.
        """
        self.send_keys(
            keys=keys,
            block=True,
            min_timeout_sec=min_timeout_sec,
            max_timeout_sec=max_timeout_sec,
        )

        # Return minimal result for compatibility
        return {
            "exit_code": 0,
            "output": self.capture_pane(capture_entire=False),
            "timestamp": time.time(),
        }

    def _send_blocking_keys(
        self,
        keys: list[str],
        max_timeout_sec: float,
    ):
        """Send blocking keys to tmux session."""
        start_time_sec = time.time()

        # Send the keys first
        send_result = self._exec_run(self._tmux_send_keys(keys))
        if send_result.exit_code != 0:
            raise RuntimeError(
                f"Failed to send keys to tmux session: {send_result.output.decode('utf-8', errors='replace')[:200]}"
            )

        # Use the full timeout for tmux wait - don't subtract 1 second
        wait_timeout = max(5, int(max_timeout_sec))  # Minimum 5 seconds

        # Wait for completion signal with proper error handling
        result = self._exec_run(
            ["timeout", f"{wait_timeout}s", "tmux", "wait", "-S", "done"]
        )

        elapsed_time_sec = time.time() - start_time_sec

        if result.exit_code != 0:
            # Check if the wait timed out (124) vs other error
            if result.exit_code == 124:  # timeout command exit code
                # Check if tmux session is still alive
                check_result = self._exec_run(
                    [
                        "tmux",
                        "list-panes",
                        "-t",
                        self._session_name,
                        "-F",
                        "#{pane_pid}",
                    ]
                )
                if check_result.exit_code == 0:
                    # Session is alive, command genuinely timed out
                    logger.warning(
                        f"Command timed out after {wait_timeout}s (max_timeout_sec={max_timeout_sec})"
                    )
                    raise TimeoutError(
                        f"Command timed out after {max_timeout_sec} seconds"
                    )
                else:
                    # Session is dead or not accessible
                    logger.error(
                        f"Tmux session died after {elapsed_time_sec:.2f}s: {check_result.output.decode('utf-8', errors='replace')[:200]}"
                    )
                    raise TimeoutError(
                        f"Tmux session died after {elapsed_time_sec:.2f} seconds"
                    )
            else:
                # Other tmux wait error
                error_msg = result.output.decode("utf-8", errors="replace")[:200]
                logger.error(
                    f"Tmux wait failed with exit code {result.exit_code}: {error_msg}"
                )
                raise RuntimeError(f"Tmux wait failed: {error_msg}")

        logger.debug(f"Blocking command completed in {elapsed_time_sec:.2f}s.")

    def _send_non_blocking_keys(
        self,
        keys: list[str],
        min_timeout_sec: float,
    ):
        """Send non-blocking keys to tmux session."""
        start_time_sec = time.time()

        # Verify session is responsive before sending keys
        if not self.is_session_responsive():
            logger.warning(
                f"Session {self._session_name} appears unresponsive, attempting recovery"
            )
            if not self.recover_session():
                raise RuntimeError(
                    f"Tmux session {self._session_name} is unresponsive and cannot be recovered"
                )

        send_result = self._exec_run(self._tmux_send_keys(keys))
        if send_result.exit_code != 0:
            logger.error(
                f"Failed to send non-blocking keys: {send_result.output.decode('utf-8', errors='replace')[:200]}"
            )
            raise RuntimeError(
                f"Failed to send keys to tmux session: {send_result.output.decode('utf-8', errors='replace')[:200]}"
            )

        elapsed_time_sec = time.time() - start_time_sec

        if elapsed_time_sec < min_timeout_sec:
            time.sleep(min_timeout_sec - elapsed_time_sec)

    def send_keys(
        self,
        keys: str | list[str],
        block: bool = False,
        min_timeout_sec: float = 0.0,
        max_timeout_sec: float = 180.0,
    ):
        """Execute keys in the tmux session."""
        if block and min_timeout_sec > 0.0:
            logger.debug("min_timeout_sec will be ignored because block is True.")

        if self._commands_path:
            with self._commands_path.open("a") as f:
                f.write(f"{repr(keys)}\n")

        prepared_keys, is_blocking = self._prepare_keys(
            keys=keys,
            block=block,
        )

        logger.debug(
            f"Sending keys to session {self._session_name}: {repr(prepared_keys[:100]) if len(repr(prepared_keys)) > 100 else repr(prepared_keys)}"
            f" min_timeout_sec: {min_timeout_sec}"
            f" max_timeout_sec: {max_timeout_sec}"
            f" is_blocking: {is_blocking}"
        )

        # Pre-flight check: ensure session is alive before sending anything
        if not self.is_session_alive():
            raise RuntimeError(f"Tmux session {self._session_name} is not alive")

        if is_blocking:
            # For blocking commands, also check responsiveness
            if not self.is_session_responsive():
                logger.warning(
                    f"Session {self._session_name} appears unresponsive before blocking command"
                )
                if not self.recover_session():
                    raise RuntimeError(
                        f"Cannot send blocking command to unresponsive session {self._session_name}"
                    )

            self._send_blocking_keys(
                keys=prepared_keys,
                max_timeout_sec=max_timeout_sec,
            )
        else:
            self._send_non_blocking_keys(
                keys=prepared_keys,
                min_timeout_sec=min_timeout_sec,
            )

        # Update metadata
        self.metadata.last_activity = time.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(keys, str):
            self.metadata.command_history.append(keys)
        else:
            self.metadata.command_history.extend(keys)

        # Limit history
        if len(self.metadata.command_history) > TerminalConstants.MAX_SESSION_HISTORY:
            self.metadata.command_history = self.metadata.command_history[
                -TerminalConstants.MAX_SESSION_HISTORY :
            ]

    def send_command(self, command: TerminalCommand) -> None:
        """Send a terminal command."""
        if command.append_enter:
            keys = [command.command, "Enter"]
        else:
            keys = [command.command]

        self.send_keys(
            keys=keys,
            block=command.block,
            min_timeout_sec=command.min_timeout_sec,
            max_timeout_sec=command.max_timeout_sec,
        )

    def _exec_run(self, cmd: list[str]) -> ExecResult:
        """Execute command in container."""
        return self.container.exec_run(cmd, user=self._user)

    def is_session_alive(self) -> bool:
        """Check if the tmux session is still alive."""
        result = self._exec_run(["tmux", "has-session", "-t", self._session_name])
        return result.exit_code == 0

    def is_session_responsive(self) -> bool:
        """Check if the tmux session is responsive to commands."""
        try:
            # Try to capture pane - this will fail if session is hung
            result = self._exec_run(
                [
                    "timeout",
                    "5s",
                    "tmux",
                    "capture-pane",
                    "-p",
                    "-t",
                    self._session_name,
                ]
            )
            return result.exit_code == 0
        except Exception as e:
            logger.warning(f"Session responsiveness check failed: {e}")
            return False

    def recover_session(self) -> bool:
        """Attempt to recover a hung or problematic session."""
        try:
            logger.info(f"Attempting to recover tmux session {self._session_name}")

            # First, try to interrupt any running command
            self._exec_run(["tmux", "send-keys", "-t", self._session_name, "C-c"])
            time.sleep(1)

            # Clear any pending wait signals
            self._exec_run(
                ["tmux", "wait", "-U", "done"]
            )  # Remove wait signal if present

            # Check if session is now responsive
            if self.is_session_responsive():
                logger.info(f"Successfully recovered session {self._session_name}")
                return True
            else:
                logger.warning(f"Failed to recover session {self._session_name}")
                return False

        except Exception as e:
            logger.error(f"Session recovery failed: {e}")
            return False

    def capture_pane(self, capture_entire: bool = False) -> str:
        """Capture the current pane content."""
        result = self._exec_run(self._tmux_capture_pane(capture_entire=capture_entire))
        return result.output.decode(errors="replace")

    def get_incremental_output(self) -> str:
        """Get incremental output since last call."""
        current_buffer = self.capture_pane(capture_entire=True)

        # First capture - no previous state
        if self._previous_buffer is None:
            self._previous_buffer = current_buffer
            return f"Current Terminal Screen:\n{self._get_visible_screen()}"

        # Try to find new content
        new_content = self._find_new_content(current_buffer)

        # Update state
        self._previous_buffer = current_buffer

        if new_content is not None:
            if new_content.strip():
                # Clean up the new content further
                cleaned_content = new_content.strip()
                return f"New Terminal Output:\n{cleaned_content}"
            else:
                return f"Current Terminal Screen:\n{self._get_visible_screen()}"
        else:
            return f"Current Terminal Screen:\n{self._get_visible_screen()}"

    def _find_new_content(self, current_buffer):
        """Find new content by comparing buffers."""
        if self._previous_buffer is None:
            return None

        pb = self._previous_buffer.strip()
        if pb in current_buffer:
            idx = current_buffer.index(pb) + len(pb)
            new_content = current_buffer[idx:]
            # Clean up excessive whitespace
            lines = new_content.split("\n")
            # Remove leading empty lines
            while lines and not lines[0].strip():
                lines.pop(0)
            # Remove trailing empty lines
            while lines and not lines[-1].strip():
                lines.pop()

            return "\n".join(lines) if lines else None

        return None

    def _get_visible_screen(self) -> str:
        """Get the currently visible screen content."""
        return self.capture_pane(capture_entire=False)

    def clear_history(self) -> None:
        """Clear the session's history/buffer."""
        result = self._exec_run(["tmux", "clear-history", "-t", self._session_name])
        if result.exit_code != 0:
            logger.warning(
                f"Failed to clear tmux history for session {self._session_name}. "
                f"Exit code: {result.exit_code}"
            )
        else:
            logger.debug(f"Cleared history for tmux session: {self._session_name}")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


class TerminalSessionManager:
    """Manages multiple tmux sessions - Apex-Code evaluation system."""

    def __init__(self, container: Container):
        """Initialize terminal session manager."""
        self.container = container
        self.sessions: dict[str, TmuxSession] = {}

    def create_session(
        self,
        session_name: str,
        commands_path: Path | None = None,
        disable_recording: bool = False,
        user: str = "",
    ) -> TmuxSession:
        """Create a new tmux session."""
        if session_name in self.sessions:
            raise ValueError(f"Session {session_name} already exists")

        session = TmuxSession(
            session_name=session_name,
            container=self.container,
            commands_path=commands_path,
            disable_recording=disable_recording,
            user=user,
        )

        self.sessions[session_name] = session
        return session

    def get_session(self, session_name: str) -> TmuxSession | None:
        """Get an existing session."""
        return self.sessions.get(session_name)

    def list_sessions(self) -> list[str]:
        """List all active sessions."""
        return [
            name
            for name, session in self.sessions.items()
            if session.is_session_alive()
        ]

    def stop_session(self, session_name: str) -> None:
        """Stop a specific session."""
        if session_name in self.sessions:
            self.sessions[session_name].stop()
            del self.sessions[session_name]

    def stop_all_sessions(self) -> None:
        """Stop all sessions."""
        for session in self.sessions.values():
            session.stop()
        self.sessions.clear()

    def cleanup_inactive_sessions(
        self, timeout: int = TerminalConstants.SESSION_TIMEOUT
    ) -> None:
        """Clean up inactive sessions."""
        current_time = time.time()
        inactive_sessions = []

        for name, session in self.sessions.items():
            try:
                # Parse last activity time
                last_activity = time.strptime(
                    session.metadata.last_activity, "%Y-%m-%d %H:%M:%S"
                )
                last_activity_time = time.mktime(last_activity)

                if current_time - last_activity_time > timeout:
                    inactive_sessions.append(name)
            except Exception:
                # If we can't parse the time, consider it inactive
                inactive_sessions.append(name)

        for session_name in inactive_sessions:
            logger.info(f"Cleaning up inactive session: {session_name}")
            self.stop_session(session_name)

    def capture_pane_safely(self, tool_executor, task_logger, filename: str) -> None:
        """Safely capture terminal pane state without breaking execution."""

        def operation():
            tmux_session = tool_executor.get_tmux_session()
            if tmux_session and task_logger:
                task_logger.log_pane_capture(
                    tmux_session, filename, capture_entire=True
                )

        self.retry_operation(
            operation,
            f"Pane capture for {filename}",
            f"Failed to save pane capture {filename}",
        )

    def capture_current_state(self, tool_executor) -> str:
        """Capture current terminal state and return the content as a string.

        Captures entire scrollback to ensure agents can see full command output,
        including test results, build logs, etc. that may be longer than the visible screen.
        """
        try:
            tmux_session = tool_executor.get_tmux_session()
            if tmux_session:
                # Use get_incremental_output which provides better context about what's new
                # Falls back to full screen if this is the first capture
                return tmux_session.get_incremental_output()
            else:
                return "Terminal session not available"
        except Exception as e:
            logger = get_logger()
            if logger:
                logger._log(f"Failed to capture terminal state: {e}")
            return f"Error capturing terminal state: {e}"

    def copy_session_logs_safely(
        self, tool_executor, task_logger, session_type: str = "agent"
    ) -> None:
        """Safely copy session logs without breaking execution."""

        def operation():
            tmux_session = tool_executor.get_tmux_session()
            if tmux_session and task_logger:
                return task_logger.log_session_files(tmux_session, session_type)

        self.retry_operation(
            operation,
            "Session log copy",
            "Failed to copy /logs/apex_*.log and /logs/apex_*.cast",
        )

    def retry_operation(self, operation, operation_name, failure_message):
        """Retry an operation with exponential backoff."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                operation()
                return  # Success, exit retry loop
            except Exception as e:
                logger = get_logger()
                if logger:
                    if attempt < max_retries - 1:
                        logger._log(
                            f"{operation_name} failed (attempt {attempt + 1}): {e}, retrying..."
                        )
                        time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    else:
                        logger._log(f"{failure_message}: {e}")


