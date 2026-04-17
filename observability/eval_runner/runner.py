"""
Main Runner - Execute agents and orchestrate evaluations.

This module provides:
1. Agent execution via inspect-ai
2. Full evaluation pipeline (agent + scoring)
3. Support for custom scorers via inspect-ai's standard interface

Custom Scorer Support:
    inspect-ai supports passing custom scorers to Task. The default scorer is
    `unified_scorer()` which validates FAIL_TO_PASS/PASS_TO_PASS tests using cached F2P lists.
    
    You can pass a custom scorer by:
    1. Creating a scorer function using @scorer decorator
    2. Passing it to run_agent_sync via the `custom_scorer` parameter
    
    Example:
        from inspect_ai.scorer import scorer, Score, CORRECT, INCORRECT
        
        @scorer(metrics=[accuracy()])
        def my_custom_scorer():
            async def score(state, target):
                # Your scoring logic
                return Score(value=CORRECT, explanation="...")
            return score
        
        result = run_agent_sync(task_id="...", model="...", custom_scorer=my_custom_scorer())
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import os
import yaml
from inspect_ai import Task, eval as inspect_eval
from inspect_ai.agent import AgentPrompt, react
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.tool import bash

from eval_runner.logger import get_logger, get_task_logger
from eval_runner.config import (
    DEFAULT_MODEL,
    get_model_config,
    load_task_config,
    get_f2p_for_task,
    EVAL_DEFAULTS,
    DEFAULT_LOG_DIR,
    TASKS_DIR,
    OBSERVABILITY_DIR,
    TIMEOUTS,
    generate_run_id,
    get_run_dir_by_id,
    get_latest_run_dir,
    get_agent_diff_from_run,
    validate_health_checks,
    ANTHROPIC_REASONING_TOKENS,
    DEFAULT_REASONING_EFFORT,
)
from eval_runner.retry_utils import (
    retry_with_backoff,
    TRANSIENT_EXCEPTIONS,
)
from eval_runner.inspect_scorer import unified_scorer

from agent.prompts.system_prompt import build_observability_prompt
from agent.tools.apply_patch import apply_patch
from agent.tools.read_file import read_file
from agent.tools.search_files import search_files
from agent.tools.update_plan import update_plan

# Add observability to path for sibling package imports (parser, agent)
sys.path.insert(0, str(OBSERVABILITY_DIR))

# Wire common/ into sys.path for Kosmos instrumentation
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from common.trajectory import TrajectoryWriter  # noqa: E402


def normalize_inspect_events_to_trajectory(events, out_path):
    """Convert a sequence of inspect-ai event dicts into a trajectory.jsonl.

    Event dicts are expected to have an 'event' type discriminator with values
    in {'model', 'tool', 'score'}. Unknown event types are skipped. A final
    'score' event is mapped to a completion marker.

    Passes with empty events: the file is still created (empty) as a marker
    that the trial ran.
    """
    writer = TrajectoryWriter(out_path)
    try:
        step = 0
        for evt in events:
            kind = evt.get("event") if isinstance(evt, dict) else None
            ts = evt.get("timestamp", "") if isinstance(evt, dict) else ""
            if kind == "model":
                step += 1
                writer.write(
                    step=step, ts=ts, type="reasoning",
                    content=evt.get("output_text", ""),
                    tokens_in=int(evt.get("input_tokens", 0) or 0),
                    tokens_out=int(evt.get("output_tokens", 0) or 0),
                    latency_ms=int(evt.get("total_time_ms", 0) or 0),
                    cost_usd=float(evt.get("cost_usd", 0.0) or 0.0),
                )
            elif kind == "tool":
                writer.write(
                    step=step or 1, ts=ts, type="tool_call",
                    tool=evt.get("tool", "unknown"),
                    args=evt.get("args", {}) if isinstance(evt.get("args"), dict) else {"raw": evt.get("args")},
                    call_id=evt.get("call_id") or f"c_{step}",
                )
                out = evt.get("output", "") or ""
                writer.write(
                    step=step or 1, ts=ts, type="tool_result",
                    call_id=evt.get("call_id") or f"c_{step}",
                    status=evt.get("status", "success"),
                    exit_code=int(evt.get("exit_code", 0) or 0),
                    stdout_bytes=len(out.encode("utf-8")),
                    content=out,
                )
            elif kind == "score":
                signal = "task_complete" if evt.get("value") == "pass" else "error"
                writer.write(
                    step=step + 1, ts=ts, type="completion",
                    signal=signal,
                    total_tokens_in=int(evt.get("total_input_tokens", 0) or 0),
                    total_tokens_out=int(evt.get("total_output_tokens", 0) or 0),
                    total_cost_usd=float(evt.get("total_cost_usd", 0.0) or 0.0),
                    wall_time_s=float(evt.get("wall_time_s", 0.0) or 0.0),
                )
    finally:
        writer.close()


def _extract_events_from_inspect_sample(sample) -> list:
    """Best-effort extraction of normalized events from an inspect-ai sample.

    Returns [] if the sample shape doesn't match our expectations — the
    normalizer will then produce an empty trajectory.jsonl, which is a
    signal that trial ran but events weren't captured.

    Real inspect-ai event shapes (verified against installed package):
      - ModelEvent: event="model", timestamp, output (ModelOutput with .usage.input_tokens)
      - ToolEvent: event="tool", timestamp, function, arguments, id, result, error
      - ScoreEvent: event="score", timestamp, score (Score with .value)
    """
    try:
        raw_events = getattr(sample, "events", None) or []
    except Exception:
        return []

    out: list[dict] = []
    for ev in raw_events:
        try:
            # inspect-ai events are typed objects; try to coerce to dict shape
            event_type = getattr(ev, "event", None) or getattr(ev, "type", None)
            if event_type == "model":
                # Pull token usage from ev.output.usage if available
                model_output = getattr(ev, "output", None)
                usage = getattr(model_output, "usage", None) if model_output is not None else None
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
                # Try to extract textual completion from the model output
                output_text = ""
                try:
                    if model_output is not None:
                        completion = getattr(model_output, "completion", None)
                        if completion is not None:
                            output_text = str(completion)
                        else:
                            output_text = str(model_output)
                except Exception:
                    output_text = ""
                out.append({
                    "event": "model",
                    "timestamp": str(getattr(ev, "timestamp", "") or ""),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_time_ms": 0,  # inspect-ai may not expose this per event
                    "cost_usd": 0.0,
                    "output_text": output_text,
                })
            elif event_type == "tool":
                err = getattr(ev, "error", None)
                out.append({
                    "event": "tool",
                    "timestamp": str(getattr(ev, "timestamp", "") or ""),
                    "tool": str(getattr(ev, "function", "") or getattr(ev, "tool", "") or "unknown"),
                    "args": dict(getattr(ev, "arguments", {}) or {}),
                    "call_id": str(getattr(ev, "id", "") or getattr(ev, "call_id", "") or ""),
                    "status": "error" if err else "success",
                    "exit_code": 0,
                    "output": str(getattr(ev, "result", "") or getattr(ev, "output", "") or ""),
                })
            elif event_type in ("score", "sample_limit", "state"):
                pass  # score is emitted below; other events skipped
        except Exception:
            continue

    # Synthesize a completion event from sample's score if available
    try:
        score = getattr(sample, "scores", None)
        value = "pass"
        if score and isinstance(score, dict):
            # take the first scorer result
            first = next(iter(score.values()), None)
            if first:
                val = getattr(first, "value", None)
                if val and str(val).upper() != "C":  # "C" = correct; anything else = fail
                    value = "fail"
        out.append({
            "event": "score",
            "timestamp": "",
            "value": value,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "wall_time_s": 0.0,
        })
    except Exception:
        pass

    return out


def extract_scoring_from_metadata(task_id: str, run_id: str) -> Optional[dict[str, Any]]:
    """
    Extract scoring data directly from the run's metadata.json.
    
    The inspect_scorer saves complete scoring data to metadata.json, so we
    don't need to re-run tests - just read the results.
    
    Returns:
        Dict with scoring data if metadata exists, None otherwise
    """
    run_dir = get_run_dir_by_id(task_id, run_id)
    if not run_dir:
        return None
    
    metadata_file = run_dir / "metadata.json"
    if not metadata_file.exists():
        return None
    
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        # Verify we have complete scoring data
        if "f2p_passed" not in metadata or "p2p_passed" not in metadata:
            return None
        return metadata
    except (json.JSONDecodeError, OSError) as e:
        get_logger(__name__).warning(f"Failed to read metadata: {e}")
        return None

logger = get_logger(__name__)


@dataclass
class AgentRunResult:
    """Result from running an agent."""
    task_id: str
    model: str
    trial: int
    success: bool
    agent_diff: str
    changed_files: list[str]
    diff_stats: dict[str, int]
    run_id: Optional[str] = None  # UUID-based run ID for this execution
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "trial": self.trial,
            "success": self.success,
            "run_id": self.run_id,
            "agent_diff_length": len(self.agent_diff) if self.agent_diff else 0,
            "changed_files": self.changed_files,
            "diff_stats": self.diff_stats,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
        }


@dataclass
class E2EResult:
    """
    Complete result from running agent + scoring in the E2E pipeline.
    
    This is distinct from parser.E2EResult which contains only
    the test/scoring results. E2EResult includes agent execution info.
    """
    task_id: str
    model: str
    trial: int
    
    # Agent phase
    agent_success: bool
    agent_diff: str
    run_id: Optional[str] = None  # UUID-based run ID
    agent_error: Optional[str] = None
    agent_duration: float = 0.0
    
    # Scoring phase
    score: float = 0.0
    passed: bool = False
    f2p_passed: int = 0
    f2p_total: int = 0
    p2p_passed: int = 0
    p2p_total: int = 0
    test_exit_code: Optional[int] = None  # Exit code from test command execution
    scoring_error: Optional[str] = None
    scoring_duration: float = 0.0
    
    # Overall
    total_duration: float = 0.0
    timestamp: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "model": self.model,
            "trial": self.trial,
            "run_id": self.run_id,
            "agent_success": self.agent_success,
            "agent_diff_length": len(self.agent_diff) if self.agent_diff else 0,
            "agent_error": self.agent_error,
            "agent_duration": self.agent_duration,
            "score": self.score,
            "passed": self.passed,
            "f2p_passed": self.f2p_passed,
            "f2p_total": self.f2p_total,
            "p2p_passed": self.p2p_passed,
            "p2p_total": self.p2p_total,
            "test_exit_code": self.test_exit_code,
            "scoring_error": self.scoring_error,
            "scoring_duration": self.scoring_duration,
            "total_duration": self.total_duration,
            "timestamp": self.timestamp,
        }
    
    def to_detailed_dict(self) -> dict[str, Any]:
        """Include full agent_diff for detailed output."""
        result = self.to_dict()
        result["agent_diff"] = self.agent_diff
        return result


def run_agent_sync(
    task_id: str,
    model: str,
    trial: int = 1,
    time_limit: int = EVAL_DEFAULTS.time_limit,
    message_limit: int = EVAL_DEFAULTS.message_limit,
    log_dir: Optional[str] = None,
    custom_scorer: Any = None,
    max_retries: int = 2,
    skip_health_check: bool = False,
    reasoning: str = DEFAULT_REASONING_EFFORT,
) -> AgentRunResult:
    """
    Run an agent evaluation and capture the diff (synchronous).

    Uses inspect-ai to execute the agent and capture code changes.
    inspect_eval manages its own event loop, so this must be synchronous.

    Args:
        task_id: Task identifier
        model: Model name (short name like "claude-opus-4-5" or full name)
        trial: Trial number for this run
        time_limit: Maximum time for agent execution in seconds
        message_limit: Maximum number of messages for the agent
        log_dir: Directory for inspect-ai logs
        custom_scorer: Optional custom scorer to use instead of unified_scorer.
                      Must be a scorer function (created with @scorer decorator).
                      See module docstring for example.
        max_retries: Number of retries for transient failures (Docker, network)
        skip_health_check: If True, skip pre-flight health checks
        reasoning: Reasoning effort level (none, minimal, low, medium, high, xhigh)

    Returns:
        AgentRunResult with agent's diff and execution details
    """
    start_time = time.time()
    task_logger = get_task_logger(task_id, __name__)
    
    # Resolve model
    model_config = get_model_config(model)
    model_name = model_config.name
    
    # Run health checks unless skipped
    if not skip_health_check:
        task_logger.info("Running pre-flight health checks...")
        if not validate_health_checks(task_id=task_id, model=model):
            return AgentRunResult(
                task_id=task_id,
                model=model_name,
                trial=trial,
                success=False,
                agent_diff="",
                changed_files=[],
                diff_stats={},
                error="Health checks failed",
                duration_seconds=time.time() - start_time,
                timestamp=datetime.now().isoformat(),
            )
    
    if log_dir is None:
        log_dir = str(DEFAULT_LOG_DIR)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # Generate unique run ID for this execution
    run_id = generate_run_id()
    
    def _run_agent_inner() -> AgentRunResult:
        """Inner function for retry logic."""
        nonlocal start_time
        inner_start = time.time()
        
        # Load task
        task_dir = TASKS_DIR / task_id
        if not task_dir.exists():
            raise FileNotFoundError(f"Task directory not found: {task_dir}")
        
        task_config = load_task_config(task_id)
        
        # Load F2P/P2P from cache (for target display and metadata)
        f2p_tests, p2p_tests = get_f2p_for_task(task_id, auto_generate=False, verbose=False)
        if f2p_tests:
            task_config.fail_to_pass = f2p_tests
            task_config.pass_to_pass = p2p_tests
        
        # Load task.yaml
        task_yaml: dict[str, Any] = {}
        task_yaml_path = task_dir / "task.yaml"
        if task_yaml_path.exists():
            try:
                with open(task_yaml_path) as f:
                    task_yaml = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                task_logger.warning(f"Failed to parse task.yaml: {e}")
        
        # Get instruction
        instruction = task_yaml.get("instruction", "")
        if not instruction:
            problem_statement_path = task_dir / "problem_statement.md"
            if problem_statement_path.exists():
                try:
                    instruction = problem_statement_path.read_text(encoding="utf-8")
                except OSError as e:
                    task_logger.warning(f"Failed to read problem_statement.md: {e}")
                    instruction = f"Fix the bug described in task {task_id}"
            else:
                instruction = f"Fix the bug described in task {task_id}"
        
        # Build system prompt
        metadata: dict[str, Any] = {
            "task_yaml": task_yaml,
            "test_metadata": {
                "test_command": task_config.test_command,
                "test_framework": task_config.test_framework,
                "FAIL_TO_PASS": task_config.fail_to_pass,
                "PASS_TO_PASS": task_config.pass_to_pass,
            },
        }
        
        instructions = build_observability_prompt(
            task_dir=task_dir,
            task_id=task_id,
            task_metadata=metadata,
        )
        
        # Configure tools
        tools = [
            apply_patch(),
            bash(timeout=TIMEOUTS.docker_command),
            read_file(),
            search_files(),
            update_plan(),
        ]
        
        # Create agent
        agent = react(
            name="apex_observability_agent",
            prompt=AgentPrompt(
                instructions=instructions,
                assistant_prompt=None,
            ),
            tools=tools,
        )
        
        # Create sample with run_id for tracking
        sample = Sample(
            input=instruction,
            target=json.dumps(task_config.fail_to_pass),
            metadata={
                "task_id": task_id,
                "task_dir": str(task_dir),
                "run_id": run_id,
            },
        )
        
        # Get compose path
        compose_path = task_dir / "compose.yaml"
        if not compose_path.exists():
            compose_path = task_dir / "docker-compose.yaml"
        
        # Use custom scorer if provided, otherwise use unified_scorer (uses F2P cache)
        if custom_scorer is not None:
            scorer_to_use = custom_scorer
        else:
            scorer_to_use = unified_scorer()
        
        # Create task
        task = Task(
            dataset=MemoryDataset([sample]),
            solver=agent,
            scorer=scorer_to_use,
            sandbox=("docker", str(compose_path)),
            time_limit=time_limit,
            message_limit=message_limit,
            fail_on_error=False,
            name=f"{task_id}_{trial}",
        )
        
        task_logger.info(f"Starting agent execution (time_limit={time_limit}s, message_limit={message_limit})")
        
        # Build model_args based on provider/model
        # Qwen models need emulate_tools=True to parse Hermes-style <tool_call> tags from content
        model_args = {}
        if model_config.provider == "fireworks":
            model_args["emulate_tools"] = True
        
        # Build eval kwargs
        eval_kwargs = {
            "tasks": [task],
            "model": model_name,
            "model_args": model_args,
            "max_tasks": 1,
            "max_sandboxes": 1,
            "max_subprocesses": 4,
            "log_dir": log_dir,
        }

        # Apply reasoning config — pass both params and let inspect_ai
        # handle per-provider translation (Claude 4.6+ uses reasoning_effort
        # directly, older Claude uses reasoning_tokens, OpenAI/Google use
        # reasoning_effort). See https://inspect.aisi.org.uk/reasoning.html
        if reasoning and reasoning != "none":
            eval_kwargs["reasoning_effort"] = reasoning
            eval_kwargs["reasoning_tokens"] = ANTHROPIC_REASONING_TOKENS.get(reasoning, 16_384)

        # Add custom base URL if configured (for OpenAI-compatible endpoints like Cognition)
        if model_config.base_url:
            eval_kwargs["model_base_url"] = model_config.base_url
        
        # Run inspect_eval (synchronous - it has its own event loop)
        eval_results = inspect_eval(**eval_kwargs)
        
        duration = time.time() - inner_start
        
        # Check if the eval actually succeeded (no sample errors)
        eval_had_error = False
        error_msg: Optional[str] = None
        if eval_results:
            for result in eval_results:
                if hasattr(result, 'samples') and result.samples:
                    for sample in result.samples:
                        if hasattr(sample, 'error') and sample.error:
                            eval_had_error = True
                            error_msg = str(sample.error)
                            break

        # Kosmos trajectory writing (best-effort)
        # Writes <EVAL_OUTPUTS_DIR>/<task_id>/<run_id>/trial_<NN>/trajectory.jsonl
        # If the inspect-ai event shape differs from our adapter, the file is
        # still created (possibly empty) as a signal that the trial ran.
        try:
            from eval_runner.config import EVAL_OUTPUTS_DIR as _EVAL_OUTPUTS_DIR
            if eval_results:
                for result in eval_results:
                    if hasattr(result, 'samples') and result.samples:
                        for sample in result.samples:
                            try:
                                _events = _extract_events_from_inspect_sample(sample)
                                _trial_dir = _EVAL_OUTPUTS_DIR / task_id / run_id / f"trial_{trial:02d}"
                                _trial_dir.mkdir(parents=True, exist_ok=True)
                                normalize_inspect_events_to_trajectory(
                                    _events, _trial_dir / "trajectory.jsonl"
                                )
                            except Exception as _e:
                                task_logger.warning(f"[kosmos] Trajectory write failed: {_e}")
        except Exception as _e:
            task_logger.warning(f"[kosmos] Trajectory block setup failed: {_e}")

        # Read agent diff from eval_outputs using run_id
        # The scorer saves to: EVAL_OUTPUTS_DIR/<task_id>/<run_id>/
        agent_diff = ""
        changed_files: list[str] = []
        
        if eval_had_error:
            error_msg = error_msg or "Eval had errors (sandbox or execution failure)"
            task_logger.error(f"Agent execution failed: {error_msg}")
        else:
            # First, try to get the run directory by our run_id
            run_dir = get_run_dir_by_id(task_id, run_id)
            
            if run_dir:
                agent_diff = get_agent_diff_from_run(run_dir)
                
                # Try to read changed files from metadata
                metadata_file = run_dir / "metadata.json"
                if metadata_file.exists():
                    try:
                        run_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                        changed_files = run_metadata.get("changed_files", [])
                    except (OSError, json.JSONDecodeError) as e:
                        task_logger.warning(f"Failed to read metadata: {e}")
            else:
                # Fallback to latest run (for backwards compatibility)
                # This may get a different run in concurrent scenarios
                latest_run = get_latest_run_dir(task_id)
                if latest_run:
                    agent_diff = get_agent_diff_from_run(latest_run)
                    task_logger.warning(f"Could not find run by ID, using latest run: {latest_run.name}")
        
        return AgentRunResult(
            task_id=task_id,
            model=model_name,
            trial=trial,
            success=bool(agent_diff),
            agent_diff=agent_diff,
            changed_files=changed_files,
            diff_stats={
                "lines_added": agent_diff.count("\n+") if agent_diff else 0,
                "lines_removed": agent_diff.count("\n-") if agent_diff else 0,
                "files_changed": len(changed_files),
            },
            run_id=run_id,
            duration_seconds=duration,
            timestamp=datetime.now().isoformat(),
            error=error_msg,
        )
    
    try:
        def on_retry(e: Exception, attempt: int) -> None:
            task_logger.warning(f"Retry {attempt}/{max_retries} after error: {e}")
        
        return retry_with_backoff(
            _run_agent_inner,
            max_retries=max_retries,
            base_delay=5.0,
            max_delay=60.0,
            retryable_exceptions=TRANSIENT_EXCEPTIONS,
            on_retry=on_retry,
        )
        
    except Exception as e:
        duration = time.time() - start_time
        task_logger.error(f"Agent execution failed: {e}")
        return AgentRunResult(
            task_id=task_id,
            model=model_name,
            trial=trial,
            success=False,
            agent_diff="",
            changed_files=[],
            diff_stats={},
            run_id=run_id,
            error=str(e),
            duration_seconds=duration,
            timestamp=datetime.now().isoformat(),
        )


async def run_agent(
    task_id: str,
    model: str,
    trial: int = 1,
    time_limit: int = EVAL_DEFAULTS.time_limit,
    message_limit: int = EVAL_DEFAULTS.message_limit,
    log_dir: Optional[str] = None,
    reasoning: str = DEFAULT_REASONING_EFFORT,
) -> AgentRunResult:
    """
    Run an agent evaluation and capture the diff (async wrapper).

    Runs the synchronous inspect_eval in a thread pool to avoid event loop conflicts.
    """
    # Use asyncio.get_running_loop() instead of deprecated get_event_loop() (Python 3.12+)
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        result = await loop.run_in_executor(
            executor,
            lambda: run_agent_sync(task_id, model, trial, time_limit, message_limit, log_dir, reasoning=reasoning)
        )
    return result


async def run_evaluation(
    task_id: str,
    model: str = DEFAULT_MODEL,
    trial: int = 1,
    time_limit: int = EVAL_DEFAULTS.time_limit,
    message_limit: int = EVAL_DEFAULTS.message_limit,
    test_timeout: int = EVAL_DEFAULTS.test_timeout,
    log_dir: Optional[str] = None,
    skip_scoring: bool = False,
    verbose: bool = False,
    max_retries: int = 2,
    reasoning: str = DEFAULT_REASONING_EFFORT,
) -> E2EResult:
    """
    Run a complete evaluation: agent + scoring.

    Args:
        task_id: Task identifier
        model: Model name (short name or full name)
        trial: Trial number
        time_limit: Agent time limit in seconds
        message_limit: Agent message limit
        test_timeout: Test execution timeout
        log_dir: Directory for inspect-ai logs
        skip_scoring: If True, only run agent and skip scoring phase
        verbose: Print progress messages
        max_retries: Number of retries for transient failures
        reasoning: Reasoning effort level (none, minimal, low, medium, high, xhigh)
    """
    start_time = time.time()
    task_logger = get_task_logger(task_id, __name__)
    
    model_config = get_model_config(model)
    model_name = model_config.name
    
    if verbose:
        task_logger.info(f"Starting evaluation with {model_config.short_name}")
    
    # Phase 1: Run agent
    if verbose:
        task_logger.info("Running agent...")
    
    agent_result = await run_agent(
        task_id=task_id,
        model=model_name,
        trial=trial,
        time_limit=time_limit,
        message_limit=message_limit,
        log_dir=log_dir,
        reasoning=reasoning,
    )
    
    if verbose:
        status = "✓" if agent_result.success else "✗"
        task_logger.info(f"Agent {status} - {len(agent_result.agent_diff)} chars diff")
    
    # Always try to extract scoring from metadata (even if no diff)
    # This ensures we report accurate f2p_total/p2p_total
    scoring = extract_scoring_from_metadata(task_id, agent_result.run_id) if agent_result.run_id else None
    
    if not agent_result.success or not agent_result.agent_diff:
        return E2EResult(
            task_id=task_id,
            model=model_name,
            trial=trial,
            agent_success=False,
            agent_diff=agent_result.agent_diff,
            run_id=agent_result.run_id,
            agent_error=agent_result.error or "No diff produced",
            agent_duration=agent_result.duration_seconds,
            # Include scoring totals even when agent fails
            f2p_total=scoring.get("f2p_total", 0) if scoring else 0,
            p2p_total=scoring.get("p2p_total", 0) if scoring else 0,
            f2p_passed=scoring.get("f2p_passed", 0) if scoring else 0,
            p2p_passed=scoring.get("p2p_passed", 0) if scoring else 0,
            test_exit_code=scoring.get("test_exit_code") if scoring else None,
            total_duration=time.time() - start_time,
            timestamp=datetime.now().isoformat(),
        )
    
    # Phase 2: Score
    if skip_scoring:
        return E2EResult(
            task_id=task_id,
            model=model_name,
            trial=trial,
            agent_success=True,
            agent_diff=agent_result.agent_diff,
            run_id=agent_result.run_id,
            agent_duration=agent_result.duration_seconds,
            test_exit_code=None,
            total_duration=time.time() - start_time,
            timestamp=datetime.now().isoformat(),
        )
    
    # Phase 2: Use scoring extracted earlier (already done above)
    scoring_start = time.time()
    
    if verbose:
        task_logger.info("Using scoring from run metadata...")
    
    if not scoring:
        error_msg = f"No scoring metadata found for run {agent_result.run_id}"
        task_logger.error(error_msg)
        return E2EResult(
            task_id=task_id,
            model=model_name,
            trial=trial,
            agent_success=True,
            agent_diff=agent_result.agent_diff,
            run_id=agent_result.run_id,
            agent_duration=agent_result.duration_seconds,
            scoring_error=error_msg,
            total_duration=time.time() - start_time,
            timestamp=datetime.now().isoformat(),
        )
    
    passed = scoring.get("passed", False)
    if verbose:
        status = "✓ PASSED" if passed else "✗ FAILED"
        task_logger.info(f"{status} - F2P: {scoring['f2p_passed']}/{scoring['f2p_total']}, P2P: {scoring['p2p_passed']}/{scoring['p2p_total']}")
    
    return E2EResult(
        task_id=task_id,
        model=model_name,
        trial=trial,
        agent_success=True,
        agent_diff=agent_result.agent_diff,
        run_id=agent_result.run_id,
        agent_duration=agent_result.duration_seconds,
        score=1.0 if passed else 0.0,
        passed=passed,
        f2p_passed=scoring.get("f2p_passed", 0),
        f2p_total=scoring.get("f2p_total", 0),
        p2p_passed=scoring.get("p2p_passed", 0),
        p2p_total=scoring.get("p2p_total", 0),
        test_exit_code=scoring.get("test_exit_code"),
        scoring_duration=time.time() - scoring_start,
        total_duration=time.time() - start_time,
        timestamp=datetime.now().isoformat(),
    )


# Sync wrappers
def run_evaluation_sync(
    task_id: str,
    model: str = DEFAULT_MODEL,
    trial: int = 1,
    **kwargs: Any
) -> E2EResult:
    """Synchronous wrapper for run_evaluation."""
    return asyncio.run(run_evaluation(task_id, model, trial, **kwargs))
