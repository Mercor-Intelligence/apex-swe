"""Multi-step task runner that allows agents to take multiple actions."""

import concurrent.futures
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path as _Path
from typing import Any

import psutil

from src.utils import LiteLLM
from src.tools import ToolExecutor
from src.utils.prompt_utils import build_episode_prompt, build_initial_prompt
from src.utils.docker_manager import docker_environment
from .evaluator import TaskEvaluator
from src.utils import TaskLogger, get_logger
from .data_models import (
    ExecutionStatus,
    TaskContext,
    TaskExecution,
)
from src.utils.terminal_manager import TerminalSessionManager
from src.utils.harness_utils import (
    cleanup_environment,
    setup_task_environment,
)

# Wire common/ into sys.path for import. Safe to run multiple times.
_REPO_ROOT = _Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.trajectory import TrajectoryWriter  # noqa: E402

logger = logging.getLogger(__name__)


def _ts_now() -> str:
    """Return current UTC time as ISO-8601 string with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dedupe_prefix_forms(test_id: str) -> list:
    """Return both the prefixed and non-prefixed forms of a test ID.

    Pytest's test ID format varies depending on where pytest is invoked from
    and the -v/-rA flags used. Some outputs prefix with "tests/", others don't.
    This helper returns both forms so downstream lookups succeed regardless of
    which form test_layers.json uses.
    """
    forms = {test_id}
    if test_id.startswith("tests/"):
        forms.add(test_id[len("tests/"):])
    else:
        forms.add("tests/" + test_id)
    return list(forms)


def _ensure_git_baseline(
    docker_manager, repo_path: str = "/app", log: TaskLogger | None = None
) -> bool:
    """Initialize git inside the container to enable diff capture."""
    try:
        check_git = docker_manager.exec_command("which git", timeout=5)
        if check_git["exit_code"] != 0:
            if log:
                log._log("git not available in container; cannot capture agent.patch")
            return False

        is_repo = (
            docker_manager.exec_command(
                f"cd {repo_path} && git rev-parse --is-inside-work-tree",
                timeout=5,
            )["exit_code"]
            == 0
        )

        if not is_repo:
            docker_manager.exec_command(f"cd {repo_path} && git init", timeout=10)
            docker_manager.exec_command(
                f"cd {repo_path} && git config user.email 'apex@eval.local'", timeout=5
            )
            docker_manager.exec_command(
                f"cd {repo_path} && git config user.name 'APEX Evaluator'", timeout=5
            )

        # Ensure we have a baseline commit and include any newly copied files
        head_exists = (
            docker_manager.exec_command(
                f"cd {repo_path} && git rev-parse --verify HEAD", timeout=5
            )["exit_code"]
            == 0
        )
        if not head_exists:
            docker_manager.exec_command(f"cd {repo_path} && git add -A", timeout=60)
            docker_manager.exec_command(
                f"cd {repo_path} && git commit -m 'Baseline state for APEX evaluation' --allow-empty",
                timeout=60,
            )
        else:
            # If the working tree is dirty (newly copied task files), commit them to baseline
            status = docker_manager.exec_command(
                f"cd {repo_path} && git status --porcelain", timeout=30
            )
            if status.get("stdout", "").strip():
                docker_manager.exec_command(f"cd {repo_path} && git add -A", timeout=60)
                docker_manager.exec_command(
                    f"cd {repo_path} && git commit -m 'Baseline state for APEX evaluation' --allow-empty",
                    timeout=60,
                )

        return True
    except Exception as e:
        if log:
            log._log(f"Failed to initialize git for agent patch capture: {e}")
        return False


def _capture_agent_patch(
    docker_manager, task_logger: TaskLogger | None, repo_path: str = "/app"
) -> bool:
    """Write git diff to agent.patch inside the task log directory."""
    try:
        docker_manager.exec_command(f"cd {repo_path} && git add -A", timeout=60)
        diff_result = docker_manager.exec_command(
            f"cd {repo_path} && git diff --cached HEAD", timeout=30
        )
        patch_text = diff_result.get("stdout", "")
        if not patch_text.strip():
            # Try non-cached diff as fallback
            diff_result = docker_manager.exec_command(
                f"cd {repo_path} && git diff HEAD", timeout=30
            )
            patch_text = diff_result.get("stdout", "")

        if patch_text and patch_text.strip() and task_logger:
            agent_patch_file = task_logger.log_dir / "agent.patch"
            agent_patch_file.write_text(patch_text)
            task_logger._log(f"Captured agent.patch ({len(patch_text.encode('utf-8'))} bytes)")
            return True
    except Exception as e:
        if task_logger:
            task_logger._log(f"Failed to capture agent.patch: {e}")
    return False


class ContextLengthExceededError(Exception):
    """Raised when the conversation exceeds the model's context length."""

    pass


class ConversationTooLongError(Exception):
    """Raised when conversation history becomes too long to manage effectively."""

    pass


class MultiStepRunner:
    """Handles multi-step task execution with tool support."""

    def __init__(
        self,
        llm: LiteLLM,
        max_steps: int | None = None,
        monitor_memory: bool = True,
        log_level: str = "INFO",
        todo_tool_enabled: bool = False,
        *,
        trajectory_writer: "TrajectoryWriter | None" = None,
    ):
        """
        Initialize multi-step runner.

        Args:
            llm: LLM for task execution
            max_steps: Maximum number of steps allowed (None = unlimited)
            monitor_memory: Whether to monitor memory usage
            log_level: Logging level for execution logs
            todo_tool_enabled: Whether to enable the todo tool
            trajectory_writer: Optional TrajectoryWriter for emitting trajectory events.
                If None, emission helpers become no-ops.
        """
        self.llm = llm
        self.max_steps = max_steps
        self.monitor_memory = monitor_memory
        self.todo_tool_enabled = todo_tool_enabled
        self.log_level = log_level
        self.trajectory_writer = trajectory_writer

    def _emit_reasoning(
        self,
        *,
        step: int,
        content: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        cost_usd: float,
        ts: str,
    ) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step,
            ts=ts,
            type="reasoning",
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

    def _emit_tool_call(
        self,
        *,
        step: int,
        tool: str,
        args: dict,
        call_id: str,
        ts: str,
    ) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step,
            ts=ts,
            type="tool_call",
            tool=tool,
            args=args,
            call_id=call_id,
        )

    def _emit_tool_result(
        self,
        *,
        step: int,
        call_id: str,
        status: str,
        exit_code: int,
        stdout_bytes: int,
        content: str,
        ts: str,
    ) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step,
            ts=ts,
            type="tool_result",
            call_id=call_id,
            status=status,
            exit_code=exit_code,
            stdout_bytes=stdout_bytes,
            content=content,
        )

    def _emit_completion(
        self,
        *,
        step: int,
        signal: str,
        total_tokens_in: int,
        total_tokens_out: int,
        total_cost_usd: float,
        wall_time_s: float,
        ts: str,
    ) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step,
            ts=ts,
            type="completion",
            signal=signal,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_cost_usd=total_cost_usd,
            wall_time_s=wall_time_s,
        )

    def _collect_per_test_results(self, *, evaluation_result, task_context, trial_dir):
        """Collect per-test results for layer evaluation.

        Parses pytest per-test lines from evaluation_result['test_output'] and
        executes any bash verifier scripts referenced in <task_dir>/test_layers.json.

        Returns: (test_results: dict[str, str], test_durations_ms: dict[str, int],
                  test_errors: dict[str, str])
        """
        import re as _re
        import subprocess as _sp
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        test_results: dict = {}
        test_durations_ms: dict = {}
        test_errors: dict = {}

        # --- Source 1: Parse pytest per-test lines from evaluator stdout ---
        output = (evaluation_result or {}).get("test_output", "") or ""

        # pytest -rA output includes both:
        #   "PASSED test_outputs.py::test_script_exists"
        #   "FAILED test_outputs.py::test_name - error message"
        # Test file prefix may or may not include "tests/" depending on how pytest is invoked.
        summary_pattern = _re.compile(
            r"^(PASSED|FAILED|ERROR)\s+((?:tests/)?[\w/.\-]+\.py::[\w\[\]_.\-]+)\s*-?\s*(.*)$",
            _re.MULTILINE,
        )
        for match in summary_pattern.finditer(output):
            status = match.group(1)
            test_id = match.group(2)
            err_text = match.group(3).strip()
            # Store under both forms (with and without tests/ prefix) for robust lookup
            for form in _dedupe_prefix_forms(test_id):
                test_results[form] = status
                test_durations_ms.setdefault(form, 0)
                if status != "PASSED" and err_text:
                    test_errors[form] = err_text[:500]

        # Also handle the verbose per-line format (in case pytest -v is used):
        #   "tests/test_outputs.py::test_script_exists PASSED   [  2%]"
        verbose_pattern = _re.compile(
            r"^((?:tests/)?[\w/.\-]+\.py::[\w\[\]_.\-]+)\s+(PASSED|FAILED|ERROR|SKIPPED)\b",
            _re.MULTILINE,
        )
        for match in verbose_pattern.finditer(output):
            test_id = match.group(1)
            status = match.group(2)
            if status == "SKIPPED":
                continue
            for form in _dedupe_prefix_forms(test_id):
                # Don't overwrite an existing status from summary pattern
                if form not in test_results:
                    test_results[form] = status
                    test_durations_ms.setdefault(form, 0)

        # --- Source 2: Execute bash verifier scripts referenced in test_layers.json ---
        task_dir = getattr(task_context, "task_dir", None)
        if task_dir and trial_dir:
            test_layers_path = _Path(task_dir) / "test_layers.json"
            if test_layers_path.exists():
                try:
                    doc = _json.loads(test_layers_path.read_text())
                    all_tests = []
                    for layer in doc.get("layers", []):
                        all_tests.extend(layer.get("tests", []))

                    for test_id in sorted(set(all_tests)):
                        if not test_id.endswith(".sh"):
                            continue
                        script_path = _Path(task_dir) / test_id
                        if not script_path.exists():
                            test_results[test_id] = "ERROR"
                            test_errors[test_id] = f"verifier script not found: {script_path}"
                            continue
                        try:
                            t0 = _time.monotonic()
                            result = _sp.run(
                                ["bash", str(script_path)],
                                cwd=str(trial_dir),
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            dur_ms = int((_time.monotonic() - t0) * 1000)
                            test_durations_ms[test_id] = dur_ms
                            # Parse PASSED/FAILED from last non-empty stdout line
                            last_line = ""
                            for ln in reversed((result.stdout or "").strip().split("\n")):
                                if ln.strip():
                                    last_line = ln.strip()
                                    break
                            if last_line.startswith("PASSED"):
                                test_results[test_id] = "PASSED"
                            else:
                                test_results[test_id] = "FAILED"
                                err_detail = last_line or f"exit={result.returncode}"
                                test_errors[test_id] = err_detail[:500]
                        except _sp.TimeoutExpired:
                            test_results[test_id] = "ERROR"
                            test_errors[test_id] = "verifier timeout (30s)"
                            test_durations_ms[test_id] = 30000
                        except Exception as _e:
                            test_results[test_id] = "ERROR"
                            test_errors[test_id] = f"verifier exception: {_e}"
                except Exception as _e:
                    # test_layers.json parse failed; leave test_results as-is (partial)
                    pass

        return test_results, test_durations_ms, test_errors

    def calculate_max_memory(self, steps: list[dict[str, Any]]) -> int | None:
        """Calculate maximum memory usage across all steps."""
        try:
            return int(psutil.Process().memory_info().rss / 1024 / 1024)
        except:
            return None

    def check_completion_indication(self, content: str) -> bool:
        """Check if agent indicates task completion."""
        xml_completion_tags = [
            "<task_complete>true</task_complete>",
            "task_complete>true<",
            "task_complete>true",
        ]

        content_lower = content.lower()
        return any(tag in content_lower for tag in xml_completion_tags)

    def _setup_docker_environment(self, task_context, max_timeout, docker_ctx, logger, task_logger):
        """
        Setup and start Docker environment with timeout.

        Returns:
            docker_manager: The initialized Docker manager
        """
        docker_manager = None

        def start_docker():
            return docker_ctx.__enter__()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(start_docker)

            try:
                docker_manager = future.result(timeout=max_timeout)

                if logger:
                    logger._log(f"Running docker compose command: docker compose up -d")
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise RuntimeError(f"Docker container startup timed out after {max_timeout}s")
            except Exception as e:
                raise RuntimeError(f"Docker startup failed: {e}")

        return docker_manager

    def _setup_git_and_mcp(self, docker_manager, task_context, logger, task_logger):
        """
        Setup git baseline and MCP configuration if needed.

        Returns:
            git_ready: Boolean indicating if git is ready
        """
        # Setup git baseline
        git_ready = _ensure_git_baseline(docker_manager, repo_path="/app", log=task_logger)

        # Setup MCP if tool containers are configured
        has_tool_containers = docker_manager.has_tool_containers(task_context)
        if has_tool_containers:
            try:
                requirements = docker_manager.get_required_mcp_requirements()
                if requirements:
                    # Filter requirements to only include services that are actually healthy
                    healthy = docker_manager.get_healthy_services()
                    if healthy:
                        from src.config import SERVICES_WITH_MCP
                        # Build reverse map: MCP token -> service names that produce it
                        token_to_services = {}
                        for svc, token in SERVICES_WITH_MCP.items():
                            token_to_services.setdefault(token, []).append(svc)

                        original_requirements = list(requirements)
                        requirements = [
                            req for req in requirements
                            if any(svc in healthy for svc in token_to_services.get(req, []))
                        ]
                        skipped = set(original_requirements) - set(requirements)
                        if skipped:
                            msg = f"Skipping MCP requirements for unhealthy services: {', '.join(skipped)}"
                            print(f"[MCP] ⚠️  {msg}")
                            if logger:
                                logger._log(msg)

                    print(f"Required MCP requirements: {', '.join(requirements)}")
                    if logger:
                        logger._log(f"Required MCP requirements: {', '.join(requirements)}")
                    req_text = "\n".join(requirements) + "\n"
                    docker_manager.exec_command(
                        f"mkdir -p /config && printf '%s' '{req_text}' > /config/mcp-required.txt.tmp && mv /config/mcp-required.txt.tmp /config/mcp-required.txt"
                    )
            except Exception as e:
                if logger:
                    logger._log(f"Failed to write mcp-required.txt: {e}")

            # Wait for MCP config to be ready (5s intervals, 60 iterations = 5 min max)
            mcp_ready = False
            max_polls = 60
            poll_interval = 5
            for i in range(max_polls):
                try:
                    result = docker_manager._container.exec_run(
                        cmd=["sh", "-lc", "sh /app/wait-for-mcp-config.sh"]
                    )
                    if result.exit_code == 0:
                        mcp_ready = True
                        if logger:
                            logger._log("MCP config is ready and task can begin")
                        break
                    else:
                        print(f"MCP config is not ready, waiting for {poll_interval} seconds")
                        if logger:
                            logger._log(f"MCP config is not ready, waiting for {poll_interval} seconds")
                except Exception as e:
                    if logger:
                        logger._log(f"⚠️ MCP config check failed: {e}")
                if logger and i % 12 == 0:
                    logger._log(
                        f"⏳ Waiting for API keys in MCP config to be ready... ({i + 1}/{max_polls})"
                    )
                time.sleep(poll_interval)

            if not mcp_ready:
                if logger:
                    logger._log(f"MCP config not ready after {max_polls * poll_interval // 60} minutes, aborting task execution")
                raise RuntimeError(f"MCP configuration not ready after {max_polls * poll_interval // 60} minutes")

        return git_ready

    def _initialize_tools_and_prompt(
        self,
        working_dir,
        docker_manager,
        task_context,
        tool_executor,
        terminal_manager,
        task_logger,
        max_timeout,
    ):
        """
        Initialize tool executor and build initial prompt.

        Returns:
            tuple: (initial_prompt, terminal_manager)
        """
        # Capture pre-agent terminal state
        terminal_manager.capture_pane_safely(tool_executor, task_logger, "pre-agent.txt")

        # Build initial prompt with todo list if enabled
        todo_list_text = tool_executor.get_todo_list_text()
        initial_prompt = build_initial_prompt(task_context, working_dir, tool_executor, max_timeout)
        if todo_list_text:
            initial_prompt = initial_prompt + f"\n\nINITIAL TODO LIST:\n{todo_list_text}"

        return initial_prompt

    def _execute_agent_loop(
        self,
        task_context,
        max_timeout,
        start_time,
        initial_prompt,
        tool_executor,
        terminal_manager,
        logger,
        task_logger,
        steps,
    ):
        """
        Execute the main agent interaction loop.

        Returns:
            None (modifies steps list in place)
        """
        current_prompt = initial_prompt
        self.llm.conversation_history = []
        effective_max_steps = task_context.max_steps or self.max_steps

        step_num = 0
        episode_task_logger = None
        completion_signal = "task_complete"

        while True:
            step_num += 1

            # Check timeout
            elapsed_time = (datetime.now() - start_time).total_seconds()
            if elapsed_time > max_timeout:
                if logger:
                    logger._log(f"Reached timeout limit ({max_timeout}s)")
                completion_signal = "timeout"
                break

            # Check max steps
            if effective_max_steps and step_num > effective_max_steps:
                if logger:
                    logger._log(f"Reached maximum steps limit ({effective_max_steps})")
                completion_signal = "max_steps"
                break

            # Check token limits
            status = self.llm.get_conversation_status()
            if status["current_tokens"] > self.llm.max_tokens * 0.9:
                if logger:
                    logger._log(
                        f"Conversation approaching hard token limit ({status['current_tokens']} tokens), terminating"
                    )
                raise ConversationTooLongError(
                    f"Conversation reached {status['current_tokens']} tokens, approaching model limit"
                )

            # Define episode_num outside the logger block since it's used unconditionally
            episode_num = step_num - 1

            # Create episode logger
            if logger:
                task_log_dir = (
                    logger.run_dir
                    / task_context.task_id
                    / f"{task_context.task_id}.1-of-1.{logger.timestamp}"
                )
                episode_task_logger = TaskLogger(
                    logger.run_id, task_context.task_id, episode_num, task_log_dir
                )

                episode_task_logger.log_prompt(current_prompt)

            # Manage conversation tokens
            elapsed_time = (datetime.now() - start_time).total_seconds()
            elapsed_minutes = elapsed_time / 60

            self.llm.manage_conversation_tokens(logger, episode_num, elapsed_minutes)

            # Call LLM
            response_content = self.llm.call(current_prompt)
            self.llm.add_to_conversation(current_prompt, response_content)

            # Count tokens
            total_tokens = self.llm.count_tokens(
                [
                    {"role": "user", "content": current_prompt},
                    {"role": "assistant", "content": response_content},
                ]
            )
            input_tokens = self.llm.count_tokens([{"role": "user", "content": current_prompt}])
            output_tokens = self.llm.count_tokens(
                [{"role": "assistant", "content": response_content}]
            )

            # Emit trajectory reasoning event
            _llm_meta = self.llm.get_last_response_metadata() if hasattr(self.llm, "get_last_response_metadata") else {}
            self._emit_reasoning(
                step=step_num,
                content=response_content,
                tokens_in=_llm_meta.get("tokens_in") or input_tokens,
                tokens_out=_llm_meta.get("tokens_out") or output_tokens,
                latency_ms=_llm_meta.get("latency_ms", 0),
                cost_usd=_llm_meta.get("cost_usd", 0.0),
                ts=_ts_now(),
            )

            response = {
                "content": response_content,
                "metadata": {
                    "model": self.llm.model_name,
                    "success": True,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
                "tokens_used": total_tokens,
            }

            # Log response
            if episode_task_logger:
                episode_task_logger.log_response(response)
                episode_task_logger.log_agent_action(
                    "response",
                    {
                        "step": episode_num,
                        "content_preview": response.get("content", "")[:200],
                        "tokens": response.get("tokens_used", 0),
                    },
                )

            # Track token usage
            response_tokens = response.get("tokens_used", 0)
            if response_tokens > 0:
                self.llm.log_token_usage(step_num - 1, response_tokens)

                token_status = self.llm.get_conversation_status()
                usage_percentage = (token_status["current_tokens"] / token_status["limit"]) * 100
                if logger and usage_percentage > 80:
                    logger._log(f"High token usage warning: {usage_percentage:.1f}% of limit")

            # Execute tools
            logs = []  # Local logs for this step
            tool_results = tool_executor.parse_and_execute_tools(response.get("content", ""), logs)

            # Emit trajectory tool_call + tool_result for each tool
            from uuid import uuid4 as _uuid4
            for _tr in tool_results:
                _call_id = f"c_{_uuid4().hex[:8]}"
                _tool_name = _tr.get("tool", "unknown")
                _call_args = _tr.get("call", {}) if isinstance(_tr.get("call"), dict) else {"raw": _tr.get("call")}
                self._emit_tool_call(
                    step=step_num,
                    tool=_tool_name,
                    args=_call_args,
                    call_id=_call_id,
                    ts=_ts_now(),
                )
                _result_str = str(_tr.get("result", ""))
                self._emit_tool_result(
                    step=step_num,
                    call_id=_call_id,
                    status="success",  # parse_and_execute_tools doesn't report status; default success
                    exit_code=0,
                    stdout_bytes=len(_result_str.encode("utf-8")),
                    content=_result_str,
                    ts=_ts_now(),
                )

            if episode_task_logger and tool_results:
                for tool_result in tool_results:
                    episode_task_logger.log_tool_execution(
                        tool_result["tool"],
                        tool_result["call"],
                        tool_result["result"],
                    )

            # Record step
            step_data = {
                "step_number": episode_num,
                "agent_response": response,
                "tool_calls": tool_results,
                "timestamp": datetime.now().isoformat(),
            }
            steps.append(step_data)

            if episode_task_logger:
                episode_task_logger.finalize()

            # Build next prompt
            terminal_content = terminal_manager.capture_current_state(tool_executor)
            todo_list_text = tool_executor.get_todo_list_text()
            current_prompt = build_episode_prompt(
                step_num, initial_prompt, terminal_content, todo_list_text
            )

            # Check for completion
            if self.check_completion_indication(response.get("content", "")):
                if task_logger:
                    task_logger.log_agent_action(
                        "completion",
                        {
                            "step": step_num - 1,
                            "reason": "explicit_completion",
                        },
                    )
                break

        print("Agent completed.")

        # Emit trajectory completion event
        _wall_time = (datetime.now() - start_time).total_seconds()
        # Sum totals from the steps list — steps[i]["agent_response"]["metadata"] has input/output tokens
        _total_in = sum(s.get("agent_response", {}).get("metadata", {}).get("input_tokens", 0) for s in steps)
        _total_out = sum(s.get("agent_response", {}).get("metadata", {}).get("output_tokens", 0) for s in steps)
        # Cost: we don't track cumulative cost — use 0.0 for now (best-effort; single-call LLM cost is in last metadata)
        self._emit_completion(
            step=step_num + 1,
            signal=completion_signal,
            total_tokens_in=_total_in,
            total_tokens_out=_total_out,
            total_cost_usd=0.0,  # TODO: accumulate from per-step metadata in future task
            wall_time_s=_wall_time,
            ts=_ts_now(),
        )

    def _post_execution_evaluation(
        self,
        docker_manager,
        git_ready,
        task_logger,
        tool_executor,
        terminal_manager,
        trial_number,
        start_time,
        steps,
        task_context,
        working_dir,
        setup_metadata,
        logger,
        execution,
    ):
        """
        Handle post-execution tasks: capture artifacts, evaluate, log results.

        Returns:
            TaskExecution: The updated execution object
        """
        # Capture post-agent terminal state
        terminal_manager.capture_pane_safely(tool_executor, task_logger, "post-agent.txt")

        # Capture git patch if git is ready
        if git_ready and task_logger:
            _capture_agent_patch(docker_manager, task_logger, repo_path="/app")

        # Run evaluation
        if logger:
            logger._log("Running task evaluation")
        evaluator = TaskEvaluator()
        evaluation_result = evaluator.evaluate_execution(
            execution,
            task_context.task_dir,
            working_dir,
            max_test_timeout=task_context.max_test_timeout_sec,
            docker_manager=docker_manager,
        )

        # Save test results
        if task_logger:
            test_results_path = task_logger.log_dir / "test_results.json"
            try:
                test_results_payload = {
                    "task_id": task_context.task_id,
                    "trial_number": trial_number,
                    "passed": evaluation_result.get("passed", False),
                    "status": evaluation_result.get(
                        "status", "error"
                    ),  # "passed", "failed", or "error"
                    "test_output": evaluation_result.get("test_output"),
                    "evaluation": evaluation_result,
                    "timestamp": datetime.now().isoformat(),
                }
                test_results_path.write_text(
                    json.dumps(test_results_payload, indent=2, default=str)
                )
                task_logger._log(f"Saved test_results.json to {test_results_path}")
            except Exception as e:
                task_logger._log(f"Failed to write test_results.json: {e}")

        if task_logger:
            task_logger.log_evaluation_result(evaluation_result)

        # Kosmos: write per-trial results.json alongside existing outputs.
        # Coarse first pass — maps aggregate pass/fail onto all F2P/P2P test
        # IDs uniformly. Per-test granularity is a future enhancement once the
        # evaluator exposes individual test results.
        trial_dir = getattr(self, "_kosmos_trial_dir", None)
        if trial_dir is not None:
            try:
                # Collect per-test results from (1) pytest stdout and (2) bash verifier scripts
                _test_results, _test_durations, _test_errors = self._collect_per_test_results(
                    evaluation_result=evaluation_result,
                    task_context=task_context,
                    trial_dir=self._kosmos_trial_dir,
                )

                # Fallback for F2P/P2P test IDs that weren't covered above (legacy aggregate verdict)
                _f2p = list(getattr(task_context, "fail_to_pass", []) or [])
                _p2p = list(getattr(task_context, "pass_to_pass", []) or [])
                _passed = bool(evaluation_result.get("passed", False))
                _status = "PASSED" if _passed else "FAILED"
                for _tid in _f2p + _p2p:
                    if _tid not in _test_results:
                        _test_results[_tid] = _status
                        _test_durations.setdefault(_tid, 0)
                if not _passed:
                    _err_fallback = (evaluation_result.get("test_output") or "")[:500]
                    for _tid in _f2p + _p2p:
                        if _test_results.get(_tid) == "FAILED" and _tid not in _test_errors:
                            _test_errors[_tid] = _err_fallback

                # Derive completion signal from execution.status when possible.
                _signal = "task_complete"
                _status_value = getattr(execution, "status", None)
                if _status_value is not None:
                    _s = str(getattr(_status_value, "value", _status_value)).lower()
                    if "timeout" in _s:
                        _signal = "timeout"
                    elif "error" in _s or "failed" in _s:
                        _signal = "error"

                _total_in = sum(
                    s.get("agent_response", {}).get("metadata", {}).get("input_tokens", 0)
                    for s in steps
                )
                _total_out = sum(
                    s.get("agent_response", {}).get("metadata", {}).get("output_tokens", 0)
                    for s in steps
                )

                evaluator.write_layer_results(
                    task_dir=task_context.task_dir,
                    trial_dir=trial_dir,
                    trial=trial_number,
                    task=task_context.task_id,
                    model=getattr(task_context, "model", None) or "",
                    wall_time_s=(datetime.now() - start_time).total_seconds(),
                    total_cost_usd=0.0,  # TODO: accumulate from per-step metadata in future task
                    total_tokens_in=_total_in,
                    total_tokens_out=_total_out,
                    completion_signal=_signal,
                    f2p_tests=_f2p,
                    p2p_tests=_p2p,
                    test_results=_test_results,
                    test_durations_ms=_test_durations,
                    test_errors=_test_errors,
                )
            except Exception as _e:
                if task_logger:
                    task_logger._log(f"[kosmos] write_layer_results failed: {_e}")
                elif logger:
                    logger._log(f"[kosmos] write_layer_results failed: {_e}")

        # Run process verification if task defines process_checks
        process_checks = getattr(task_context, "process_checks", None)
        if process_checks and task_logger:
            if logger:
                logger._log("Running process verification (tool-call log analysis)")
            process_result = evaluator.evaluate_process(
                task_logger.log_dir, process_checks
            )
            evaluation_result["process_verification"] = process_result

            # Save process results alongside test results
            try:
                process_path = task_logger.log_dir / "process_results.json"
                process_path.write_text(json.dumps(process_result, indent=2, default=str))
                if logger:
                    logger._log(
                        f"Process verification: {process_result['passed']}/{process_result['total']} checks passed "
                        f"({process_result['required_passed']}/{process_result['required_total']} required)"
                    )
            except Exception as e:
                if logger:
                    logger._log(f"Failed to write process_results.json: {e}")

        # Capture post-test artifacts
        terminal_manager.capture_pane_safely(tool_executor, task_logger, "post-test.txt")
        terminal_manager.copy_session_logs_safely(tool_executor, task_logger, "agent")

        # Update execution with evaluation results
        execution.metadata["evaluation"] = evaluation_result
        execution.metadata["test_passed"] = evaluation_result.get("passed", False)

        if not evaluation_result.get("passed", False):
            execution.status = ExecutionStatus.FAILED
            execution.error_message = (
                f"Tests failed: {evaluation_result.get('test_output', 'No output')}"
            )

        # Log final status
        test_passed = evaluation_result.get("passed", False)
        status_text = "PASS" if test_passed else "FAIL"
        evaluation_message = f"[{status_text}] Evaluation complete. Tests passed: {test_passed}"

        print(evaluation_message)
        if logger:
            logger._log(evaluation_message)

        if task_logger:
            task_logger.end_episode(execution.status.value)

        return execution

    def run_single_trial(
        self,
        task_context: TaskContext,
        trial_number: int,
        working_dir: Path | None = None,
    ) -> TaskExecution:
        """
        Run a single trial with multiple steps.

        Args:
            task_context: Task context with instructions and files
            trial_number: Trial number (1-based)
            working_dir: Optional working directory (creates temp if None)

        Returns:
            TaskExecution result
        """
        start_time = datetime.now()
        logs = []
        steps = []

        # Wire Kosmos trajectory writer + per-trial results dir.
        # The runner pool loans a runner to a single trial at a time, so setting
        # self.trajectory_writer here is safe.
        self._kosmos_trial_dir = None
        try:
            _run_dir = getattr(task_context, "run_dir", None)
            if _run_dir is not None:
                _trial_dir = Path(_run_dir) / f"trial_{trial_number:02d}"
                _trial_dir.mkdir(parents=True, exist_ok=True)
                self.trajectory_writer = TrajectoryWriter(_trial_dir / "trajectory.jsonl")
                self._kosmos_trial_dir = _trial_dir
            else:
                self.trajectory_writer = None
        except Exception:
            # If anything fails, fall back to no writer — do not break the trial
            self.trajectory_writer = None
            self._kosmos_trial_dir = None

        # Determine max timeout
        max_timeout = float(task_context.timeout)
        if (
            hasattr(task_context, "max_agent_timeout_sec")
            and task_context.max_agent_timeout_sec is not None
        ):
            max_timeout = float(task_context.max_agent_timeout_sec)

        # Setup environment
        working_dir, setup_metadata = setup_task_environment(
            task_context, working_dir, use_docker=True
        )

        docker_ctx = docker_environment(
            task_context,
            working_dir,
            sessions_logs_path=working_dir / "sessions",
            agent_logs_path=working_dir / "agent-logs",
        )

        # Get logger
        logger = get_logger()
        task_logger = None
        if logger:
            if task_context.task_id not in logger.task_loggers:
                task_logger = logger.create_task_logger(task_context.task_id)
            else:
                task_logger = logger.task_loggers[task_context.task_id]

        try:
            # Phase 1: Setup Docker environment
            docker_manager = self._setup_docker_environment(
                task_context, max_timeout, docker_ctx, logger, task_logger
            )

            # Phase 2: Setup git and MCP configuration
            git_ready = self._setup_git_and_mcp(docker_manager, task_context, logger, task_logger)

            # Phase 3: Initialize tools and terminal manager
            tool_executor = ToolExecutor(
                working_dir,
                docker_manager=docker_manager,
                todo_tool_enabled=self.todo_tool_enabled,
            )

            terminal_manager = TerminalSessionManager(docker_manager.container)

            initial_prompt = self._initialize_tools_and_prompt(
                working_dir,
                docker_manager,
                task_context,
                tool_executor,
                terminal_manager,
                task_logger,
                max_timeout,
            )

            # Phase 4: Execute main agent loop
            self._execute_agent_loop(
                task_context,
                max_timeout,
                start_time,
                initial_prompt,
                tool_executor,
                terminal_manager,
                logger,
                task_logger,
                steps,
            )

            # Phase 5: Create execution result
            execution_time = (datetime.now() - start_time).total_seconds()
            max_memory = self.calculate_max_memory(steps) if self.monitor_memory else None

            final_response = {
                "content": steps[-1]["agent_response"].get("content", "") if steps else "",
                "steps": steps,
                "total_steps": len(steps),
                "conversation_history": self.llm.conversation_history,
            }

            execution = TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.COMPLETED,
                agent_response=final_response,
                execution_time=execution_time,
                memory_used=max_memory,
                logs=logs,
                metadata={
                    "working_dir": str(working_dir),
                    "setup_metadata": setup_metadata.model_dump(),
                    "multi_step": True,
                    "max_steps": self.max_steps,
                    "steps_taken": len(steps),
                },
                started_at=start_time,
                completed_at=datetime.now(),
            )

            # Phase 6: Post-execution evaluation
            execution = self._post_execution_evaluation(
                docker_manager,
                git_ready,
                task_logger,
                tool_executor,
                terminal_manager,
                trial_number,
                start_time,
                steps,
                task_context,
                working_dir,
                setup_metadata,
                logger,
                execution,
            )

            return execution

        except ContextLengthExceededError as e:
            return TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.FAILED,
                error_message=f"Context length exceeded: {str(e)}",
                execution_time=(datetime.now() - start_time).total_seconds(),
                logs=logs,
                metadata={
                    "working_dir": str(working_dir),
                    "error_type": "ContextLengthExceededError",
                    "failure_mode": "context_length_exceeded",
                    "steps_completed": len(steps) if "steps" in locals() else 0,
                    "token_usage": self.llm.get_conversation_status(),
                },
                started_at=start_time,
                completed_at=datetime.now(),
            )

        except ConversationTooLongError as e:
            return TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.FAILED,
                error_message=f"Conversation too long: {str(e)}",
                execution_time=(datetime.now() - start_time).total_seconds(),
                logs=logs,
                metadata={
                    "working_dir": str(working_dir),
                    "error_type": "ConversationTooLongError",
                    "failure_mode": "conversation_too_long",
                    "steps_completed": len(steps) if "steps" in locals() else 0,
                    "token_usage": self.llm.get_conversation_status(),
                },
                started_at=start_time,
                completed_at=datetime.now(),
            )

        except Exception as e:
            return TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.FAILED,
                error_message=str(e),
                execution_time=(datetime.now() - start_time).total_seconds(),
                logs=logs,
                metadata={
                    "working_dir": str(working_dir),
                    "error_type": type(e).__name__,
                    "failure_mode": "unknown_error",
                    "steps_completed": len(steps) if "steps" in locals() else 0,
                    "token_usage": self.llm.get_conversation_status(),
                },
                started_at=start_time,
                completed_at=datetime.now(),
            )
        finally:
            if "tool_executor" in locals() and tool_executor:
                try:
                    tool_executor.cleanup()
                except Exception as e:
                    if "logs" in locals() and logs:
                        logs.append(f"Error cleaning up tools: {e}")
            # Close Kosmos trajectory writer if it was opened.
            if self.trajectory_writer is not None:
                try:
                    self.trajectory_writer.close()
                except Exception:
                    pass
                finally:
                    self.trajectory_writer = None

            if "docker_ctx" in locals() and docker_ctx:
                try:
                    time.sleep(0.5)
                    docker_ctx.__exit__(None, None, None)
                    if "logger" in locals() and logger:
                        container_name = "unknown"
                        if (
                            "docker_manager" in locals()
                            and docker_manager
                            and hasattr(docker_manager, "_container_name")
                        ):
                            container_name = docker_manager._container_name
                        logger._log(f"Running docker compose command: docker compose down")
                except Exception as e:
                    if "logs" in locals() and logs:
                        logs.append(f"Error cleaning up Docker: {e}")

            cleanup_environment(working_dir, setup_metadata, preserve_logs=True)
