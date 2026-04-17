"""Test that Kosmos artifacts are produced when run_single_trial uses the wiring.

This is a lightweight wire-up test: it stubs in a fake task context and
verifies trajectory.jsonl and results.json land in the expected trial dir.
Full-integration (docker + real LLM) is out of scope here.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.trajectory import TrajectoryWriter


def test_trajectory_and_results_written_to_trial_dir(tmp_path):
    """Given a trial_dir, TrajectoryWriter + TaskEvaluator.write_layer_results produce both files."""
    from src.harness.evaluator import TaskEvaluator

    trial_dir = tmp_path / "trial_01"
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    # Write a trajectory
    traj_path = trial_dir / "trajectory.jsonl"
    with TrajectoryWriter(traj_path) as w:
        w.write(
            step=1, ts="2026-04-16T00:00:00.000Z", type="reasoning",
            content="plan", tokens_in=10, tokens_out=5, latency_ms=100, cost_usd=0.001,
        )
        w.write(
            step=1, ts="2026-04-16T00:00:01.000Z", type="completion",
            signal="task_complete", total_tokens_in=10, total_tokens_out=5,
            total_cost_usd=0.001, wall_time_s=1.0,
        )
    assert traj_path.exists()

    # Write per-trial results.json
    ev = TaskEvaluator()
    ev.write_layer_results(
        task_dir=task_dir, trial_dir=trial_dir,
        trial=1, task="t", model="m",
        wall_time_s=1.0, total_cost_usd=0.001,
        total_tokens_in=10, total_tokens_out=5,
        completion_signal="task_complete",
        f2p_tests=["a::t1"], p2p_tests=["b::t2"],
        test_results={"a::t1": "PASSED", "b::t2": "PASSED"},
        test_durations_ms={}, test_errors={},
    )
    res_path = trial_dir / "results.json"
    assert res_path.exists()
    res = json.loads(res_path.read_text())
    assert res["trial"] == 1
    assert len(res["layers"]) == 2


def test_aggregate_runs_on_multi_trial_dir(tmp_path):
    """aggregate_trials + write_eval_summary produce eval_summary.{md,json} from populated trial dirs."""
    from src.harness.evaluator import TaskEvaluator
    from common.trials import aggregate_trials, write_eval_summary

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    ev = TaskEvaluator()
    for i in (1, 2):
        ev.write_layer_results(
            task_dir=task_dir,
            trial_dir=tmp_path / f"trial_{i:02d}",
            trial=i, task="t", model="m",
            wall_time_s=1.0, total_cost_usd=0.0,
            total_tokens_in=0, total_tokens_out=0,
            completion_signal="task_complete",
            f2p_tests=["a::t1"], p2p_tests=[],
            test_results={"a::t1": "PASSED"},
            test_durations_ms={}, test_errors={},
        )

    agg = aggregate_trials(tmp_path)
    assert agg["trial_count"] == 2
    write_eval_summary(tmp_path, agg)
    assert (tmp_path / "eval_summary.md").exists()
    assert (tmp_path / "eval_summary.json").exists()
