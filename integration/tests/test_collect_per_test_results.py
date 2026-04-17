"""Test MultiStepRunner._collect_per_test_results helper."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_parses_pytest_per_test_lines(tmp_path, monkeypatch):
    from src.harness.multi_step_runner import MultiStepRunner

    runner = MultiStepRunner.__new__(MultiStepRunner)

    evaluation_result = {
        "test_output": (
            "=== test session starts ===\n"
            "tests/test_outputs.py::test_script_exists PASSED        [  2%]\n"
            "tests/test_outputs.py::test_script_runs_successfully PASSED [  5%]\n"
            "tests/test_outputs.py::test_active_customer_count FAILED [  7%]\n"
            "tests/test_outputs.py::test_s3_report_schema_valid ERROR [ 10%]\n"
            "FAILED tests/test_outputs.py::test_active_customer_count - AssertionError: expected 50 got 88\n"
            "=== 1 failed, 2 passed, 1 error in 3.2s ===\n"
        ),
        "passed": False,
    }

    task_context = MagicMock()
    task_context.task_dir = str(tmp_path)  # no test_layers.json → only pytest source

    results, durations, errors = runner._collect_per_test_results(
        evaluation_result=evaluation_result,
        task_context=task_context,
        trial_dir=None,
    )

    assert results["tests/test_outputs.py::test_script_exists"] == "PASSED"
    assert results["tests/test_outputs.py::test_script_runs_successfully"] == "PASSED"
    assert results["tests/test_outputs.py::test_active_customer_count"] == "FAILED"
    assert results["tests/test_outputs.py::test_s3_report_schema_valid"] == "ERROR"
    assert "expected 50 got 88" in errors.get("tests/test_outputs.py::test_active_customer_count", "")


def test_executes_bash_verifier_scripts(tmp_path):
    from src.harness.multi_step_runner import MultiStepRunner

    # Create a fake task dir with test_layers.json referencing a bash verifier
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    verifiers_dir = task_dir / "tests" / "verifiers"
    verifiers_dir.mkdir(parents=True)

    # A verifier that PASSES
    passing = verifiers_dir / "pass.sh"
    passing.write_text("#!/bin/bash\necho PASSED\nexit 0\n")
    passing.chmod(0o755)

    # A verifier that FAILS
    failing = verifiers_dir / "fail.sh"
    failing.write_text("#!/bin/bash\necho 'FAILED: no trajectory'\nexit 1\n")
    failing.chmod(0o755)

    (task_dir / "test_layers.json").write_text(json.dumps({
        "version": 1,
        "layers": [
            {"name": "Test", "tests": [
                "tests/verifiers/pass.sh",
                "tests/verifiers/fail.sh",
            ], "threshold": {"pass^k": 1.0}},
        ],
    }))

    trial_dir = tmp_path / "trial_01"
    trial_dir.mkdir()

    runner = MultiStepRunner.__new__(MultiStepRunner)

    task_context = MagicMock()
    task_context.task_dir = str(task_dir)

    results, durations, errors = runner._collect_per_test_results(
        evaluation_result={"test_output": "", "passed": False},
        task_context=task_context,
        trial_dir=trial_dir,
    )

    assert results["tests/verifiers/pass.sh"] == "PASSED"
    assert results["tests/verifiers/fail.sh"] == "FAILED"
    assert "FAILED: no trajectory" in errors.get("tests/verifiers/fail.sh", "")
    assert durations["tests/verifiers/pass.sh"] >= 0
