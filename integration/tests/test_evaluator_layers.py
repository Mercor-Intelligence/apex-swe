"""Test that TaskEvaluator produces per-trial results.json with layer breakdown."""
import json
import sys
from pathlib import Path

# Ensure common/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_evaluator_write_layer_results_creates_json_with_fallback(tmp_path):
    """With no test_layers.json present, uses F2P/P2P fallback layers."""
    from src.harness.evaluator import TaskEvaluator

    task_dir = tmp_path / "task"
    task_dir.mkdir()

    trial_dir = tmp_path / "trial_01"

    ev = TaskEvaluator()
    ev.write_layer_results(
        task_dir=task_dir,
        trial_dir=trial_dir,
        trial=1,
        task="test_task",
        model="test-model",
        wall_time_s=5.0,
        total_cost_usd=0.01,
        total_tokens_in=100,
        total_tokens_out=20,
        completion_signal="task_complete",
        f2p_tests=["tests/test_a.py::t1"],
        p2p_tests=["tests/test_b.py::t2"],
        test_results={"tests/test_a.py::t1": "PASSED", "tests/test_b.py::t2": "PASSED"},
        test_durations_ms={"tests/test_a.py::t1": 10, "tests/test_b.py::t2": 20},
        test_errors={},
    )

    out = trial_dir / "results.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["trial"] == 1
    assert data["task"] == "test_task"
    assert data["model"] == "test-model"
    assert data["completion_signal"] == "task_complete"
    assert len(data["layers"]) == 2
    layer_names = [l["name"] for l in data["layers"]]
    assert layer_names == ["F2P", "P2P"]
    assert data["layers"][0]["layer_passed"] is True
    assert data["layers"][1]["layer_passed"] is True


def test_evaluator_write_layer_results_uses_test_layers_json(tmp_path):
    """If test_layers.json is present in task_dir, it's used instead of fallback."""
    from src.harness.evaluator import TaskEvaluator

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "test_layers.json").write_text(json.dumps({
        "version": 1,
        "layers": [
            {
                "name": "Gate",
                "tests": ["tests/verifiers/g.sh"],
                "threshold": {"pass^k": 1.0},
            },
            {
                "name": "Functional",
                "tests": ["@F2P"],
                "threshold": {"pass@k": 0.80},
            },
        ]
    }))

    trial_dir = tmp_path / "trial_01"

    ev = TaskEvaluator()
    ev.write_layer_results(
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
        f2p_tests=["tests/test_a.py::t1", "tests/test_a.py::t2"],
        p2p_tests=[],
        test_results={
            "tests/verifiers/g.sh": "PASSED",
            "tests/test_a.py::t1": "PASSED",
            "tests/test_a.py::t2": "FAILED",
        },
        test_durations_ms={},
        test_errors={"tests/test_a.py::t2": "expected 1 got 2"},
    )

    data = json.loads((trial_dir / "results.json").read_text())
    assert [l["name"] for l in data["layers"]] == ["Gate", "Functional"]
    gate_layer = data["layers"][0]
    assert gate_layer["layer_passed"] is True
    assert gate_layer["pass_count"] == 1
    functional_layer = data["layers"][1]
    assert functional_layer["layer_passed"] is False  # t2 failed
    assert functional_layer["pass_count"] == 1
    assert functional_layer["total_count"] == 2


def test_evaluator_write_layer_results_missing_test_marked_error(tmp_path):
    """Tests referenced in layers but not in test_results are marked ERROR."""
    from src.harness.evaluator import TaskEvaluator

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "test_layers.json").write_text(json.dumps({
        "version": 1,
        "layers": [
            {
                "name": "Gate",
                "tests": ["tests/verifiers/missing.sh"],
                "threshold": {"pass^k": 1.0},
            },
        ]
    }))

    trial_dir = tmp_path / "trial_01"
    ev = TaskEvaluator()
    ev.write_layer_results(
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
        f2p_tests=[],
        p2p_tests=[],
        test_results={},  # Empty — referenced test has no result
        test_durations_ms={},
        test_errors={},
    )

    data = json.loads((trial_dir / "results.json").read_text())
    test = data["layers"][0]["tests"][0]
    assert test["status"] == "ERROR"
