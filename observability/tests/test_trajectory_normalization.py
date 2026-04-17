"""Test inspect-ai transcript → trajectory.jsonl normalization."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_normalize_model_event_to_reasoning(tmp_path):
    from observability.eval_runner.runner import normalize_inspect_events_to_trajectory

    fake_events = [
        {
            "event": "model",
            "timestamp": "2026-04-16T00:00:00.000Z",
            "input_tokens": 100,
            "output_tokens": 20,
            "total_time_ms": 500,
            "cost_usd": 0.001,
            "output_text": "I will check Mattermost",
        },
        {
            "event": "tool",
            "timestamp": "2026-04-16T00:00:01.000Z",
            "tool": "bash",
            "args": {"cmd": "ls"},
            "call_id": "c_01",
            "status": "success",
            "exit_code": 0,
            "output": "file.txt\n",
        },
        {
            "event": "score",
            "timestamp": "2026-04-16T00:00:02.000Z",
            "value": "pass",
            "total_input_tokens": 100,
            "total_output_tokens": 20,
            "total_cost_usd": 0.001,
            "wall_time_s": 2.0,
        },
    ]

    out_path = tmp_path / "trajectory.jsonl"
    normalize_inspect_events_to_trajectory(fake_events, out_path)
    lines = [json.loads(l) for l in out_path.read_text().splitlines()]

    assert lines[0]["type"] == "reasoning"
    assert lines[0]["content"] == "I will check Mattermost"
    assert lines[0]["tokens_in"] == 100

    assert lines[1]["type"] == "tool_call"
    assert lines[1]["tool"] == "bash"

    assert lines[2]["type"] == "tool_result"
    assert lines[2]["call_id"] == "c_01"
    assert lines[2]["status"] == "success"

    assert lines[3]["type"] == "completion"
    assert lines[3]["signal"] == "task_complete"


def test_normalize_handles_empty_events(tmp_path):
    from observability.eval_runner.runner import normalize_inspect_events_to_trajectory
    out_path = tmp_path / "trajectory.jsonl"
    normalize_inspect_events_to_trajectory([], out_path)
    # File should still be created (empty)
    assert out_path.exists()
    assert out_path.read_text() == ""


def test_normalize_score_fail_produces_error_signal(tmp_path):
    from observability.eval_runner.runner import normalize_inspect_events_to_trajectory
    fake_events = [{
        "event": "score",
        "timestamp": "t",
        "value": "fail",
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "wall_time_s": 0.0,
    }]
    out_path = tmp_path / "trajectory.jsonl"
    normalize_inspect_events_to_trajectory(fake_events, out_path)
    line = json.loads(out_path.read_text().strip())
    assert line["signal"] == "error"
