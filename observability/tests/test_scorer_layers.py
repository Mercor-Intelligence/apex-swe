"""Test that write_layer_results_for_trial produces results.json with layer breakdown."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_scorer_writes_results_with_layers(tmp_path):
    from observability.eval_runner.inspect_scorer import write_layer_results_for_trial

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "test_layers.json").write_text(json.dumps({
        "version": 1,
        "layers": [
            {"name": "F2P", "tests": ["@F2P"], "threshold": {"pass^k": 1.0}},
            {"name": "P2P", "tests": ["@P2P"], "threshold": {"pass^k": 1.0}},
        ]
    }))

    trial_dir = tmp_path / "trial_01"
    write_layer_results_for_trial(
        task_dir=task_dir,
        trial_dir=trial_dir,
        trial=1,
        task="t",
        model="m",
        wall_time_s=1.0,
        total_cost_usd=0.0,
        total_tokens_in=0,
        total_tokens_out=0,
        completion_signal="task_complete",
        f2p_tests=["a::t1"],
        p2p_tests=["b::t2"],
        test_results={"a::t1": "PASSED", "b::t2": "PASSED"},
        test_durations_ms={"a::t1": 10, "b::t2": 20},
        test_errors={},
    )

    data = json.loads((trial_dir / "results.json").read_text())
    assert data["layers"][0]["layer_passed"] is True
    assert data["layers"][1]["layer_passed"] is True


def test_scorer_fallback_without_test_layers_json(tmp_path):
    from observability.eval_runner.inspect_scorer import write_layer_results_for_trial

    task_dir = tmp_path / "task"
    task_dir.mkdir()  # no test_layers.json

    trial_dir = tmp_path / "trial_01"
    write_layer_results_for_trial(
        task_dir=task_dir,
        trial_dir=trial_dir,
        trial=1,
        task="t",
        model="m",
        wall_time_s=1.0,
        total_cost_usd=0.0,
        total_tokens_in=0,
        total_tokens_out=0,
        completion_signal="task_complete",
        f2p_tests=["a::t1"],
        p2p_tests=["b::t2"],
        test_results={"a::t1": "PASSED", "b::t2": "FAILED"},
        test_durations_ms={},
        test_errors={"b::t2": "oops"},
    )

    data = json.loads((trial_dir / "results.json").read_text())
    # fallback: F2P and P2P layers synthesized
    assert [l["name"] for l in data["layers"]] == ["F2P", "P2P"]
    assert data["layers"][0]["layer_passed"] is True
    assert data["layers"][1]["layer_passed"] is False
