"""Tests for trial aggregation."""
import json
import shutil
from pathlib import Path

from common.trials import aggregate_trials, write_eval_summary

FIXTURES = Path(__file__).parent / "fixtures"


def _populate_run_dir(run_dir: Path, trial_files: list[str]) -> None:
    for i, f in enumerate(trial_files, start=1):
        trial_dir = run_dir / f"trial_{i:02d}"
        trial_dir.mkdir(parents=True)
        shutil.copy(FIXTURES / f, trial_dir / "results.json")


class TestAggregateTrials:
    def test_computes_per_layer_pass_at_k_and_pass_power_k(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)

        gate = next(l for l in agg["layers"] if l["name"] == "Gate")
        assert gate["pass_at_k"] == 1.0
        assert gate["pass_power_k"] == 1.0
        assert gate["pass_rate"] == 1.0

        functional = next(l for l in agg["layers"] if l["name"] == "Functional")
        assert functional["pass_at_k"] == 1.0    # trials 1 and 2 passed
        assert functional["pass_power_k"] == 0.0 # trial 3 failed
        assert abs(functional["pass_rate"] - 2/3) < 1e-9

    def test_tests_passed_total_sums_across_trials(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        functional = next(l for l in agg["layers"] if l["name"] == "Functional")
        assert functional["tests_passed_total"] == 5   # 2 + 2 + 1
        assert functional["tests_total"] == 6          # 2 * 3 trials

    def test_per_layer_verdict_uses_declared_threshold(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        gate = next(l for l in agg["layers"] if l["name"] == "Gate")
        assert gate["verdict"] == "PASS"  # pass^k=1.0 threshold, met
        functional = next(l for l in agg["layers"] if l["name"] == "Functional")
        # Functional threshold is pass@k≥0.80 — but only 2/3 trials passed, rate=0.667 < 0.80
        assert functional["verdict"] == "FAIL"

    def test_holistic_metrics(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        # Trials 1 and 2 passed every layer → pass@k holistic = 1.0
        # Trial 3 failed Functional → pass^k holistic = 0.0
        assert agg["holistic"]["pass_at_k"] == 1.0
        assert agg["holistic"]["pass_power_k"] == 0.0

    def test_aggregate_cost_and_timing(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        assert abs(agg["total_cost_usd"] - (0.5 + 0.45 + 0.55)) < 1e-9
        assert agg["trial_count"] == 3
        assert agg["avg_wall_time_s"] == (100 + 110 + 120) / 3

    def test_single_trial_run(self, tmp_path):
        _populate_run_dir(tmp_path, ["sample_results_trial_01.json"])
        agg = aggregate_trials(tmp_path)
        assert agg["trial_count"] == 1
        # All metrics should still be computable
        gate = next(l for l in agg["layers"] if l["name"] == "Gate")
        assert gate["pass_at_k"] == 1.0
        assert gate["pass_power_k"] == 1.0

    def test_empty_run_dir_raises(self, tmp_path):
        import pytest
        with pytest.raises(ValueError, match="no trial_"):
            aggregate_trials(tmp_path)


from common.trials import write_eval_summary


class TestWriteEvalSummary:
    def test_writes_markdown_and_json(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        write_eval_summary(tmp_path, agg)

        md_path = tmp_path / "eval_summary.md"
        json_path = tmp_path / "eval_summary.json"
        assert md_path.exists()
        assert json_path.exists()

    def test_markdown_contains_per_layer_verdicts(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        write_eval_summary(tmp_path, agg)
        content = (tmp_path / "eval_summary.md").read_text()

        assert "# Eval Summary" in content
        assert "crm_debug" in content
        assert "claude-opus-4-7" in content
        assert "Gate" in content
        assert "Functional" in content
        assert "5/6" in content  # Functional tests_passed_total / tests_total
        assert "PASS" in content
        assert "FAIL" in content

    def test_markdown_contains_failed_tests_section(self, tmp_path):
        _populate_run_dir(tmp_path, [
            "sample_results_trial_01.json",
            "sample_results_trial_02.json",
            "sample_results_trial_03.json",
        ])
        agg = aggregate_trials(tmp_path)
        write_eval_summary(tmp_path, agg)
        content = (tmp_path / "eval_summary.md").read_text()
        assert "## Failed Tests" in content
        assert "Trial 3" in content
        assert "t2" in content
        assert "boom" in content

    def test_json_matches_aggregate_shape(self, tmp_path):
        _populate_run_dir(tmp_path, ["sample_results_trial_01.json"])
        agg = aggregate_trials(tmp_path)
        write_eval_summary(tmp_path, agg)
        loaded = json.loads((tmp_path / "eval_summary.json").read_text())
        assert loaded["task"] == agg["task"]
        assert loaded["trial_count"] == agg["trial_count"]
        assert len(loaded["layers"]) == len(agg["layers"])
