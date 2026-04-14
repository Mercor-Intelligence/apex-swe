import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .file_tool import FileTool
from .terminal_tool import TerminalTool
from .todo_tool import TodoTool
from src.utils.logging_utils import get_logger

class ToolExecutor:
    """Tool executor that directly manages tools."""

    def __init__(
        self,
        working_dir: Path | None = None,
        docker_manager=None,
        todo_tool_enabled: bool = False,
    ):
        """Initialize tool executor."""
        self.working_dir = working_dir or Path.cwd()
        self.docker_manager = docker_manager

        self.tools = {
            "file": FileTool(self.working_dir),
            "terminal": TerminalTool(self.working_dir, docker_manager)
            if docker_manager
            else None,
        }

        # Only add todo tool if enabled
        if todo_tool_enabled:
            self.tools["todo"] = TodoTool()

        self.execution_history = []

    def execute(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Execute a single tool by name with parameters."""
        if tool_name not in self.tools:
            return self._create_error_result(
                tool_name,
                f"Unknown tool: {tool_name}",
                available_tools=list(self.tools.keys()),
            )

        tool = self.tools[tool_name]
        if not tool:
            return self._create_error_result(
                tool_name, f"Tool not available: {tool_name}"
            )

        start_time = time.time()

        try:
            result = tool.execute(**kwargs)
            execution_time = time.time() - start_time

            # Track execution
            self._record_execution(tool_name, kwargs, result, execution_time)

            # Add metadata
            result["_metadata"] = self._create_metadata(tool_name, execution_time)
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_result = self._create_error_result(tool_name, str(e), execution_time)
            self._record_execution(tool_name, kwargs, error_result, execution_time)
            return error_result

    def execute_tool(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """Alias for execute method for backward compatibility."""
        return self.execute(tool_name, **kwargs)

    def execute_all_tools(self, content: str, logs: list[str]) -> list[dict[str, Any]]:
        """Parse content and execute all found tool calls."""
        tool_calls = parse_tool_calls(content)
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("tool")
            if not tool_name:
                continue

            # Log execution
            self._log_execution(logs, tool_name, tool_call)

            # Execute tool with parsed parameters
            result = self._call_tool(tool_call)
            results.append({"tool": tool_name, "call": tool_call, "result": result})

        return results

    def _call_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Call a tool that was parsed from content."""
        tool_name = tool_call.get("tool")

        if tool_name == "terminal":
            command = tool_call.get("command", "")
            timeout = tool_call.get("timeout", 120)
            return self.execute("terminal", command=command, timeout=timeout)
        elif tool_name == "todo":
            action = tool_call.get("action")
            params = {k: v for k, v in tool_call.items() if k not in ("tool", "action")}
            return self.execute("todo", action=action, **params)
        elif tool_name == "file":
            operation = tool_call.get("operation")
            path = tool_call.get("path", "")
            params = {
                k: v
                for k, v in tool_call.items()
                if k not in ("tool", "operation", "path")
            }
            return self.execute("file", operation=operation, path=path, **params)
        else:
            return self._create_error_result(tool_name, f"Unknown tool: {tool_name}")

    def _log_execution(
        self, logs: list[str], tool_name: str, tool_call: dict[str, Any]
    ):
        """Log tool execution."""
        logger = get_logger()

        if tool_name == "terminal" and "command" in tool_call:
            command = tool_call.get("command", "")
            timeout = tool_call.get("timeout", 180.0)
            if logger:
                logger.log_command_execution(command, is_blocking=True, timeout=timeout)
        else:
            self._log(logs, f"Executing tool: {tool_name}")

    def _create_error_result(
        self,
        tool_name: str,
        error: str,
        execution_time: float = 0.0,
        available_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create standardized error result."""
        result = {
            "success": False,
            "error": error,
            "tool": tool_name,
            "execution_time": execution_time,
        }

        if available_tools:
            result["available_tools"] = available_tools

        return result

    def _create_metadata(self, tool_name: str, execution_time: float) -> dict[str, Any]:
        """Create execution metadata."""
        return {
            "tool": tool_name,
            "execution_time": execution_time,
            "timestamp": datetime.now().isoformat(),
        }

    def _log(self, logs: list[str], message: str):
        """Add log message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}"
        logs.append(log_entry)
        print(log_entry)

    def _record_execution(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
        execution_time: float,
    ):
        """Record tool execution in history."""
        self.execution_history.append(
            {
                "tool": tool_name,
                "params": params,
                "result": result,
                "execution_time": execution_time,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def list_tools(self) -> list[str]:
        """List all available tools."""
        return [name for name, tool in self.tools.items() if tool is not None]

    def has_tool(self, tool_name: str) -> bool:
        """Return True if a tool is available and enabled."""
        return tool_name in self.tools and self.tools.get(tool_name) is not None

    def get_todo_list_text(self) -> str | None:
        """Get todo list text."""
        # Fast path: if todo tool is not enabled, skip execution
        if not self.has_tool("todo"):
            return None
        try:
            result = self.execute("todo", action="list")
            if not result.get("success"):
                return None

            tasks = result.get("tasks", [])
            if not tasks:
                return "(empty)"

            return "\n".join(
                f"- [{t.get('status', 'todo')}] #{t.get('id', '?')}: {t.get('title', '')}"
                for t in tasks
            )
        except Exception as e:
            logger = get_logger()
            if logger:
                logger._log(f"Failed to fetch todo list: {e}")
            return None

    def get_tmux_session(self):
        """Get the tmux session from the terminal tool."""
        terminal_tool = self.tools.get("terminal")
        if terminal_tool and hasattr(terminal_tool, "tmux_session"):
            return terminal_tool.tmux_session
        return None

    def parse_and_execute_tools(
        self, content: str, logs: list[str]
    ) -> list[dict[str, Any]]:
        """Parse tool calls from agent response and execute them."""
        tool_results = []
        matches = []

        # First try Terminal Bench keystrokes format: <keystrokes>command</keystrokes>
        keystrokes_pattern = r"<keystrokes[^>]*>(.*?)</keystrokes>"
        keystrokes_matches = re.findall(keystrokes_pattern, content, re.DOTALL)

        if keystrokes_matches:
            self._log(logs, f"\nFound {len(keystrokes_matches)} keystrokes commands")
            # Execute keystrokes directly without JSON conversion
            for keystroke_command in keystrokes_matches:
                clean_command = html.unescape(keystroke_command.strip())
                if clean_command:
                    # Execute directly as terminal command
                    logger = get_logger()
                    if logger:
                        logger.log_command_execution(
                            clean_command, is_blocking=True, timeout=180.0
                        )

                    exec_start = time.time()
                    result = self.execute("terminal", command=clean_command)

                    if logger:
                        duration = time.time() - exec_start
                        logger._log(f"Blocking command completed in {duration:.2f}s.")

                    tool_results.append(
                        {
                            "tool": "terminal",
                            "call": {"tool": "terminal", "command": clean_command},
                            "result": result,
                        }
                    )
        # Do not return early; allow parsing of <tool_use> blocks as well

        # Fallback: try XML format: <tool_use>{...}</tool_use>
        if not matches:
            tool_pattern = r"<tool_use>\s*(\{.*?\})\s*</tool_use>"
            matches = re.findall(tool_pattern, content, re.DOTALL)

        # If no direct XML format found, try XML with nested markdown: <tool_use>```json{...}```</tool_use>
        if not matches:
            nested_pattern = r"<tool_use>\s*```json\s*(\{.*?\})\s*```\s*</tool_use>"
            matches = re.findall(nested_pattern, content, re.DOTALL)
            if matches:
                self._log(
                    logs,
                    f"Found {len(matches)} tool calls in nested XML+markdown format",
                )

        # If no XML format found, try JSON array format: [{...}]
        if not matches:
            json_pattern = r"```json\s*(\[.*?\])\s*```"
            json_matches = re.findall(json_pattern, content, re.DOTALL)
            if json_matches:
                try:
                    # Parse the JSON array
                    tool_calls = json.loads(json_matches[0])
                    if isinstance(tool_calls, list):
                        # Convert each tool call to a JSON string for processing
                        matches = [json.dumps(call) for call in tool_calls]
                        self._log(
                            logs,
                            f"Found {len(matches)} tool calls in JSON array format",
                        )
                except json.JSONDecodeError as e:
                    self._log(logs, f"Failed to parse JSON array format: {e}")
        # If no structured format found, try bash code blocks
        if not matches:
            bash_pattern = r"```bash\s*(.*?)\s*```"
            bash_matches = re.findall(bash_pattern, content, re.DOTALL)
            if bash_matches:
                self._log(logs, f"Found {len(bash_matches)} bash code blocks")
                # Convert bash commands to tool call format
                for bash_command in bash_matches:
                    # Clean up the command (remove empty lines, strip whitespace)
                    clean_command = html.unescape("\n".join(
                        line.strip()
                        for line in bash_command.split("\n")
                        if line.strip()
                    ))
                    if clean_command:
                        tool_call = {"tool": "terminal", "command": clean_command}
                        matches.append(json.dumps(tool_call))

        for match in matches:
            try:
                # Parse JSON
                tool_call = json.loads(match)
                tool_name = tool_call.get("tool")

                if not tool_name:
                    continue

                # Apex-Code evaluation tool logging
                logger = get_logger()
                if logger and tool_name == "terminal" and "command" in tool_call:
                    # Log in Apex-Code evaluation format
                    command = tool_call.get("command", "")
                    timeout = tool_call.get("timeout", 180.0)
                    logger.log_command_execution(
                        command, is_blocking=True, timeout=timeout
                    )
                else:
                    self._log(logs, f"Executing tool: {tool_name}")

                # Execute based on tool type
                exec_start = time.time()
                if tool_name == "terminal":
                    result = self.execute(
                        "terminal", command=html.unescape(tool_call.get("command", ""))
                    )
                    # Log completion with duration if Apex-Code logger is available
                    if logger and "command" in tool_call:
                        duration = time.time() - exec_start
                        # The first log was already done, this logs completion
                        logger._log(f"Blocking command completed in {duration:.2f}s.")
                elif tool_name == "todo":
                    # Extract params excluding 'tool' and 'action'
                    action = tool_call.get("action")
                    params = {
                        k: v
                        for k, v in tool_call.items()
                        if k not in ("tool", "action")
                    }
                    result = self.execute("todo", action=action, **params)
                else:
                    result = {"success": False, "error": f"Unknown tool: {tool_name}"}

                tool_results.append(
                    {"tool": tool_name, "call": tool_call, "result": result}
                )

            except json.JSONDecodeError as e:
                self._log(logs, f"Failed to parse tool call: {e}")
            except Exception as e:
                self._log(logs, f"Tool execution error: {e}")

        return tool_results

    def _log(self, logs: list[str], message: str) -> None:
        """Add log message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}"
        logs.append(log_entry)
        print(log_entry)  # Also print to console for immediate feedback

    def cleanup(self):
        """Clean up all tools."""
        for tool in self.tools.values():
            if tool and hasattr(tool, "cleanup"):
                try:
                    tool.cleanup()
                except:
                    pass
