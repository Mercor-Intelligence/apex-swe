"""Test that MultiStepRunner emission helpers write to the TrajectoryWriter."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.trajectory import TrajectoryWriter


def test_emission_helpers_write_correct_event_types(tmp_path):
    """Exercise the four _emit_* helpers directly; verify JSONL events."""
    from src.harness.multi_step_runner import MultiStepRunner

    traj_path = tmp_path / "trajectory.jsonl"
    writer = TrajectoryWriter(traj_path)

    # Create a MultiStepRunner without going through __init__ (avoids needing a live LLM).
    runner = MultiStepRunner.__new__(MultiStepRunner)
    runner.trajectory_writer = writer

    runner._emit_reasoning(step=1, content="plan", tokens_in=10, tokens_out=5,
                            latency_ms=100, cost_usd=0.001,
                            ts="2026-04-16T00:00:00.000Z")
    runner._emit_tool_call(step=1, tool="bash", args={"cmd": "ls"},
                            call_id="c_01", ts="2026-04-16T00:00:01.000Z")
    runner._emit_tool_result(step=1, call_id="c_01", status="success",
                              exit_code=0, stdout_bytes=10, content="ok",
                              ts="2026-04-16T00:00:02.000Z")
    runner._emit_completion(step=2, signal="task_complete",
                             total_tokens_in=10, total_tokens_out=5,
                             total_cost_usd=0.001, wall_time_s=5.0,
                             ts="2026-04-16T00:00:03.000Z")
    writer.close()

    events = [json.loads(l) for l in traj_path.read_text().splitlines()]
    assert [e["type"] for e in events] == ["reasoning", "tool_call", "tool_result", "completion"]
    assert events[1]["tool"] == "bash"
    assert events[1]["args"] == {"cmd": "ls"}
    assert events[3]["signal"] == "task_complete"


def test_emission_helpers_noop_when_writer_is_none():
    """If trajectory_writer is None, helpers should not raise."""
    from src.harness.multi_step_runner import MultiStepRunner

    runner = MultiStepRunner.__new__(MultiStepRunner)
    runner.trajectory_writer = None

    runner._emit_reasoning(step=1, content="x", tokens_in=0, tokens_out=0,
                           latency_ms=0, cost_usd=0.0, ts="t")
    runner._emit_tool_call(step=1, tool="bash", args={}, call_id="c", ts="t")
    runner._emit_tool_result(step=1, call_id="c", status="success", exit_code=0,
                             stdout_bytes=0, content="", ts="t")
    runner._emit_completion(step=1, signal="task_complete", total_tokens_in=0,
                            total_tokens_out=0, total_cost_usd=0.0, wall_time_s=0.0,
                            ts="t")
    # No assertion needed — success = no exception raised
