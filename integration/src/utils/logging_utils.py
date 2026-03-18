"""APEX SWE Harness logging utilities."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict

_run_id: Optional[str] = None
_run_dir: Optional[Path] = None
_run_timestamp: Optional[str] = None
_task_loggers: Dict[str, "TaskLogger"] = {}


class TaskLogger:
    """Manages structured data logging for task execution."""

    def __init__(self, run_id: str, task_id: str, episode_num: int, log_dir: Path):
        self.run_id = run_id
        self.task_id = task_id
        self.episode_num = episode_num
        self.log_dir = log_dir
        self.episode_dir = log_dir / "agent-logs" / f"episode-{episode_num}"
        self.panes_dir = log_dir / "panes"
        self.sessions_dir = log_dir / "sessions"
        
        for dir_path in [self.episode_dir, self.panes_dir, self.sessions_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        self.command_history_path = log_dir / "commands.txt"
        self.prompt_path = self.episode_dir / "prompt.txt"
        self.response_path = self.episode_dir / "response.json"
        self.debug_path = self.episode_dir / "debug.json"
        self.start_time = time.time()
        self.debug_data = {
            "episode": episode_num,
            "task_id": task_id,
            "start_time": datetime.now().isoformat(),
            "commands": [],
            "tool_calls": [],
        }

    def _log(self, message: str):
        print(f"[{self.task_id}] {message}")

    def log_prompt(self, prompt: str):
        self.prompt_path.write_text(prompt)

    def log_response(self, response: Dict[str, Any]):
        self.response_path.write_text(json.dumps(response, indent=4))

    def log_command(self, command: str, is_blocking: bool = False, timeout: Optional[float] = None):
        with open(self.command_history_path, "a") as f:
            f.write(f"{command}\\n\n")
        self.debug_data["commands"].append({
            "command": command,
            "is_blocking": is_blocking,
            "timeout": timeout,
            "timestamp": datetime.now().isoformat(),
        })

    def log_tool_execution(self, tool_name: str, tool_call: Dict[str, Any], tool_result: Dict[str, Any]):
        self.debug_data["tool_calls"].append({
            "tool": tool_name,
            "call": tool_call,
            "result": tool_result,
            "timestamp": datetime.now().isoformat(),
        })
        if tool_name == "terminal" and "command" in tool_call:
            self.log_command(
                tool_call["command"],
                is_blocking=tool_call.get("is_blocking", True),
                timeout=tool_call.get("timeout"),
            )

    def log_agent_action(self, action_type: str, data: Dict[str, Any]):
        self.debug_data.setdefault("agent_actions", []).append({
            "action": action_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })

    def log_evaluation_result(self, result: Dict[str, Any]):
        self.debug_data["evaluation"] = result

    def log_pane_capture(self, tmux_session, filename: str, capture_entire: bool = True) -> Optional[Path]:
        if hasattr(tmux_session, "save_pane_capture"):
            return tmux_session.save_pane_capture(self.panes_dir, filename, capture_entire)
        return None

    def log_session_files(self, tmux_session, session_type: str = "agent") -> Dict[str, Optional[Path]]:
        if hasattr(tmux_session, "copy_session_logs_to_host"):
            return tmux_session.copy_session_logs_to_host(self.sessions_dir, session_type)
        return {"log_file": None, "cast_file": None}

    def finalize(self):
        self.debug_path.write_text(json.dumps(self.debug_data, indent=2))

    def end_episode(self, status: str):
        self.debug_data.update({
            "end_time": datetime.now().isoformat(),
            "status": status,
            "duration": time.time() - self.start_time
        })
        self.finalize()


# Backward compatible wrapper
class ApexLogger:
    """Simplified wrapper - delegates to module-level functions."""
    
    def __init__(self, run_id: str, runs_dir: Path):
        global _run_id, _run_dir, _run_timestamp
        if not _run_id:  # Only initialize once
            _run_id = run_id
            _run_timestamp = f"{datetime.now().strftime('%Y-%m-%d__%H-%M-%S')}-{os.getpid()}"
            _run_dir = runs_dir / _run_timestamp
            _run_dir.mkdir(parents=True, exist_ok=True)
            (_run_dir / "apex.lock").touch()
            print("Starting harness run")
            print(f"Run ID: {run_id}")
        
        self.run_id = _run_id
        self.timestamp = _run_timestamp
        self.run_dir = _run_dir
        self.run_metadata_path = _run_dir / "run_metadata.json"
        self.task_loggers = _task_loggers

    def _log(self, message: str):
        print(message)

    def log_run_metadata(self, metadata: Dict[str, Any]):
        task_id = metadata.get("task_id", "unknown")
        agent = metadata.get("agent", metadata.get("model", "unknown"))
        timeout = metadata.get("timeout")
        
        info = f"Starting {agent} on {task_id}"
        if timeout:
            info += f" (timeout: {timeout}s)"
        print(info)
        self.run_metadata_path.write_text(json.dumps(metadata, indent=2))

    def log_command_execution(self, command: str, is_blocking: bool = False, 
                             timeout: Optional[float] = None, duration: Optional[float] = None):
        print(f"Sending keys: {repr(command)} timeout: {timeout or 180.0}s")
        if is_blocking and duration:
            print(f"Completed in {duration:.2f}s")

    def create_task_logger(self, task_id: str) -> TaskLogger:
        task_log_dir = self.run_dir / task_id / f"{task_id}.1-of-1.{self.timestamp}"
        task_log_dir.mkdir(parents=True, exist_ok=True)
        
        agent_logs_dir = task_log_dir / "agent-logs"
        episode_num = (
            len([d for d in agent_logs_dir.iterdir() if d.is_dir() and d.name.startswith("episode-")])
            if agent_logs_dir.exists() else 0
        )
        
        print(f"Executing {task_id}...")
        task_logger = TaskLogger(self.run_id, task_id, episode_num, task_log_dir)
        self.task_loggers[task_id] = task_logger
        _task_loggers[task_id] = task_logger
        return task_logger

    def finalize_run(self, summary: Dict[str, Any]):
        for task in summary.get("unresolved_tasks", []):
            print(f"Unresolved task {task}")


_apex_logger: Optional[ApexLogger] = None


def init_apex_logger(run_id: str, runs_dir: Path) -> ApexLogger:
    """Initialize logging for a harness run."""
    global _apex_logger
    _apex_logger = ApexLogger(run_id, runs_dir)
    return _apex_logger


def get_logger() -> Optional[ApexLogger]:
    """Get current logger instance."""
    return _apex_logger
