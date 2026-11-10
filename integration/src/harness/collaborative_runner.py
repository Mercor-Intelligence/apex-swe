"""Collaborative multi-agent runner — two agents, fully autonomous coordination."""

import concurrent.futures
import logging
import time
from datetime import datetime
from pathlib import Path

from src.utils import LiteLLM, create_llm
from src.tools import ToolExecutor
from src.utils.prompt_utils import build_collaborative_prompt, build_collaborative_episode_prompt
from src.utils.docker_manager import docker_environment
from src.utils.terminal_manager import TerminalSessionManager
from src.utils.harness_utils import setup_task_environment, cleanup_environment
from src.utils.logging_utils import get_logger, TaskLogger
from .evaluator import TaskEvaluator
from .data_models import ExecutionStatus, TaskContext, TaskExecution
from .multi_step_runner import _ensure_git_baseline, _capture_agent_patch

logger = logging.getLogger(__name__)

_SUBMISSION_FILE = "/app/READY_TO_SUBMIT"


class CollaborativeRunner:
    """
    Runs a task with two agents collaborating autonomously.

    Agents share the container filesystem and decide for themselves how to
    coordinate. The harness provides:
      - Two parallel agent loops with isolated tmux sessions
      - Completion when both agents signal <satisfied>true</satisfied>
    """

    def __init__(
        self,
        llm: LiteLLM,
        max_steps: int | None = None,
        todo_tool_enabled: bool = False,
        agent_models: list[str] | None = None,
    ):
        self.llm = llm
        self.max_steps = max_steps
        self.todo_tool_enabled = todo_tool_enabled
        self.agent_models = agent_models

    # ── MCP setup ──────────────────────────────────────────────────────────

    def _setup_mcp(self, docker_manager, task_context, log) -> None:
        """Wait for MCP configuration if the task uses tool containers."""
        if not docker_manager.has_tool_containers(task_context):
            return

        try:
            requirements = docker_manager.get_required_mcp_requirements()
            if requirements:
                req_text = "\n".join(requirements) + "\n"
                docker_manager.exec_command(
                    f"mkdir -p /config && printf '%s' '{req_text}' "
                    f"> /config/mcp-required.txt.tmp && "
                    f"mv /config/mcp-required.txt.tmp /config/mcp-required.txt"
                )
        except Exception as e:
            if log:
                log._log(f"Failed to write mcp-required.txt: {e}")

        for i in range(120):
            try:
                result = docker_manager._container.exec_run(
                    cmd=["sh", "-lc", "sh /app/wait-for-mcp-config.sh"]
                )
                if result.exit_code == 0:
                    if log:
                        log._log("MCP config ready")
                    return
            except Exception as e:
                if log:
                    log._log(f"MCP config check failed: {e}")
            if log and i % 6 == 0:
                log._log(f"Waiting for MCP config... ({i + 1}/120)")
            time.sleep(10)

        raise RuntimeError("MCP configuration not ready after 20 minutes")

    def _submission_ready(self, docker_manager) -> bool:
        """Return True if the submission file exists in the container."""
        try:
            result = docker_manager.exec_command(
                f"test -f {_SUBMISSION_FILE}", timeout=3
            )
            return result.get("exit_code", 1) == 0
        except Exception:
            return False

    # ── Agent loop ─────────────────────────────────────────────────────────

    def _run_agent(
        self,
        agent_id: int,
        task_context: TaskContext,
        docker_manager,
        working_dir: Path,
        max_timeout: float,
        start_time: datetime,
        log,
        task_logger,
    ) -> list[dict]:
        """Run one agent's collaborative loop until satisfied or limits hit."""
        model = (
            self.agent_models[agent_id]
            if self.agent_models and agent_id < len(self.agent_models)
            else self.llm.model_name
        )
        agent_llm = create_llm(model)
        agent_llm.conversation_history = []

        tool_executor = ToolExecutor(
            working_dir,
            docker_manager=docker_manager,
            todo_tool_enabled=self.todo_tool_enabled,
            session_name=f"collab_{agent_id}",
        )
        terminal_manager = TerminalSessionManager(docker_manager.container)

        agent_log_dir = task_logger.log_dir / f"agent_{agent_id}" if task_logger else None

        initial_prompt = build_collaborative_prompt(
            task_context, agent_id, working_dir, tool_executor, max_timeout
        )

        terminal_manager.capture_pane_safely(tool_executor, task_logger, f"agent_{agent_id}-pre.txt")

        steps = []
        current_prompt = initial_prompt
        step_num = 0

        while True:
            # Stop when both agents have reached consensus and created the submission file
            if self._submission_ready(docker_manager):
                if log:
                    log._log(f"Agent {agent_id + 1}: submission file detected, stopping")
                break

            step_num += 1
            episode_num = step_num - 1

            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > max_timeout:
                if log:
                    log._log(f"Agent {agent_id + 1}: timeout after {elapsed:.0f}s")
                break
            if self.max_steps and step_num > self.max_steps:
                if log:
                    log._log(f"Agent {agent_id + 1}: reached max steps ({self.max_steps})")
                break

            episode_logger = None
            if task_logger and agent_log_dir:
                episode_logger = TaskLogger(
                    task_logger.run_id,
                    task_context.task_id,
                    episode_num,
                    agent_log_dir,
                )
                episode_logger.log_prompt(current_prompt)

            response = agent_llm.call(current_prompt)
            agent_llm.add_to_conversation(current_prompt, response)

            if episode_logger:
                episode_logger.log_response({"content": response, "model": agent_llm.model_name})

            logs: list[str] = []
            tool_results = tool_executor.parse_and_execute_tools(response, logs)

            if episode_logger:
                for tr in tool_results:
                    episode_logger.log_tool_execution(tr["tool"], tr["call"], tr["result"])
                episode_logger.finalize()

            steps.append({
                "step": step_num,
                "agent_id": agent_id,
                "response": response,
                "tool_calls": tool_results,
                "timestamp": datetime.now().isoformat(),
            })

            terminal_content = terminal_manager.capture_current_state(tool_executor)
            todo_text = tool_executor.get_todo_list_text()
            current_prompt = build_collaborative_episode_prompt(
                step_num, initial_prompt, terminal_content, agent_id, todo_text
            )

        terminal_manager.capture_pane_safely(tool_executor, task_logger, f"agent_{agent_id}-post.txt")
        terminal_manager.copy_session_logs_safely(tool_executor, task_logger, f"agent_{agent_id}")

        try:
            tool_executor.cleanup()
        except Exception:
            pass

        return steps

    # ── Main entry point ───────────────────────────────────────────────────

    def run_single_trial(
        self,
        task_context: TaskContext,
        trial_number: int,
        working_dir: Path | None = None,
    ) -> TaskExecution:
        """Run one trial with two agents collaborating autonomously."""
        start_time = datetime.now()
        logs: list[str] = []

        max_timeout = float(task_context.timeout)
        if getattr(task_context, "max_agent_timeout_sec", None):
            max_timeout = float(task_context.max_agent_timeout_sec)

        working_dir, setup_metadata = setup_task_environment(
            task_context, working_dir, use_docker=True
        )
        docker_ctx = docker_environment(
            task_context, working_dir,
            sessions_logs_path=working_dir / "sessions",
            agent_logs_path=working_dir / "agent-logs",
        )

        log = get_logger()
        task_logger = None
        if log:
            task_logger = (
                log.task_loggers.get(task_context.task_id)
                or log.create_task_logger(task_context.task_id)
            )

        try:
            docker_manager = docker_ctx.__enter__()
            git_ready = _ensure_git_baseline(docker_manager, repo_path="/app", log=task_logger)
            self._setup_mcp(docker_manager, task_context, log)

            if log:
                log._log("Starting collaborative run with 2 agents")

            all_steps: list[dict] = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = {
                    pool.submit(
                        self._run_agent,
                        agent_id=i,
                        task_context=task_context,
                        docker_manager=docker_manager,
                        working_dir=working_dir,
                        max_timeout=max_timeout,
                        start_time=start_time,
                        log=log,
                        task_logger=task_logger,
                    ): i
                    for i in range(2)
                }
                for fut in concurrent.futures.as_completed(futures, timeout=max_timeout + 60):
                    agent_id = futures[fut]
                    try:
                        steps = fut.result()
                        all_steps.extend(steps)
                    except Exception as e:
                        if log:
                            log._log(f"Agent {agent_id + 1} error: {e}")

            if git_ready and task_logger:
                _capture_agent_patch(docker_manager, task_logger, repo_path="/app")

            execution_time = (datetime.now() - start_time).total_seconds()
            all_steps.sort(key=lambda s: s["timestamp"])

            execution = TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.COMPLETED,
                agent_response={
                    "content": all_steps[-1]["response"] if all_steps else "",
                },
                execution_time=execution_time,
                memory_used=None,
                logs=logs,
                metadata={
                    "working_dir": str(working_dir),
                    "setup_metadata": setup_metadata.model_dump(),
                    "multi_agent": True,
                    "n_agents": 2,
                    "steps_taken": len(all_steps),
                },
                started_at=start_time,
                completed_at=datetime.now(),
            )

            evaluator = TaskEvaluator()
            evaluation_result = evaluator.evaluate_execution(
                execution, task_context.task_dir, working_dir,
                max_test_timeout=task_context.max_test_timeout_sec,
                docker_manager=docker_manager,
            )
            execution.metadata["evaluation"] = evaluation_result
            execution.metadata["test_passed"] = evaluation_result.get("passed", False)
            if not evaluation_result.get("passed", False):
                execution.status = ExecutionStatus.FAILED

            if task_logger:
                task_logger.log_evaluation_result(evaluation_result)
                task_logger.end_episode(execution.status.value)

            return execution

        except Exception as e:
            return TaskExecution(
                trial_number=trial_number,
                status=ExecutionStatus.FAILED,
                error_message=str(e),
                execution_time=(datetime.now() - start_time).total_seconds(),
                logs=logs,
                metadata={"error_type": type(e).__name__, "multi_agent": True},
                started_at=start_time,
                completed_at=datetime.now(),
            )
        finally:
            try:
                time.sleep(0.5)
                docker_ctx.__exit__(None, None, None)
            except Exception:
                pass
            cleanup_environment(working_dir, setup_metadata, preserve_logs=True)
