"""Tests for LayerEvaluator."""
import json
import shutil
from pathlib import Path

import pytest

from common.layers import LayerEvaluator, Layer

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadLayers:
    def test_loads_basic_layers_file(self, tmp_path):
        shutil.copy(FIXTURES / "test_layers_basic.json", tmp_path / "test_layers.json")
        evaluator = LayerEvaluator(task_dir=tmp_path, f2p_tests=[], p2p_tests=[])
        layers = evaluator.load_layers()

        assert len(layers) == 2
        assert layers[0].name == "Gate"
        assert layers[0].threshold == {"pass^k": 1.0}
        assert layers[0].tests == ["tests/verifiers/script_exists.sh"]
        assert layers[1].name == "Functional"
        assert layers[1].threshold == {"pass@k": 0.80}

    def test_expands_f2p_p2p_tokens(self, tmp_path):
        shutil.copy(FIXTURES / "test_layers_with_tokens.json", tmp_path / "test_layers.json")
        evaluator = LayerEvaluator(
            task_dir=tmp_path,
            f2p_tests=["tests/test_a.py::test_1", "tests/test_a.py::test_2"],
            p2p_tests=["tests/test_b.py::test_3"],
        )
        layers = evaluator.load_layers()
        assert layers[0].tests == ["tests/test_a.py::test_1", "tests/test_a.py::test_2"]
        assert layers[1].tests == ["tests/test_b.py::test_3"]

    def test_fallback_when_file_absent(self, tmp_path):
        evaluator = LayerEvaluator(
            task_dir=tmp_path,
            f2p_tests=["tests/test_a.py::t1"],
            p2p_tests=["tests/test_b.py::t2"],
        )
        layers = evaluator.load_layers()
        assert len(layers) == 2
        assert layers[0].name == "F2P"
        assert layers[0].tests == ["tests/test_a.py::t1"]
        assert layers[0].threshold == {"pass^k": 1.0}
        assert layers[1].name == "P2P"
        assert layers[1].tests == ["tests/test_b.py::t2"]
        assert layers[1].threshold == {"pass^k": 1.0}

    def test_invalid_json_raises(self, tmp_path):
        (tmp_path / "test_layers.json").write_text("not json {")
        evaluator = LayerEvaluator(task_dir=tmp_path, f2p_tests=[], p2p_tests=[])
        with pytest.raises(ValueError, match="test_layers.json"):
            evaluator.load_layers()

    def test_missing_layers_key_raises(self, tmp_path):
        (tmp_path / "test_layers.json").write_text(json.dumps({"version": 1}))
        evaluator = LayerEvaluator(task_dir=tmp_path, f2p_tests=[], p2p_tests=[])
        with pytest.raises(ValueError, match="layers"):
            evaluator.load_layers()


class TestLayerDataclass:
    def test_layer_holds_name_tests_threshold_description(self):
        layer = Layer(
            name="Gate",
            description="basic",
            tests=["a.sh", "b.sh"],
            threshold={"pass^k": 1.0},
        )
        assert layer.name == "Gate"
        assert layer.description == "basic"
        assert layer.tests == ["a.sh", "b.sh"]
        assert layer.threshold == {"pass^k": 1.0}


class TestEvaluate:
    def _make(self, tmp_path):
        return LayerEvaluator(task_dir=tmp_path, f2p_tests=[], p2p_tests=[])

    def test_evaluate_returns_layer_passed_true_when_all_tests_pass(self, tmp_path):
        ev = self._make(tmp_path)
        layers = [Layer(name="L", tests=["t1", "t2"], threshold={"pass^k": 1.0})]
        results = {"t1": "PASSED", "t2": "PASSED"}
        evaluated = ev.evaluate(layers, results, durations_ms={"t1": 10, "t2": 20}, errors={})
        assert evaluated[0]["layer_passed"] is True
        assert evaluated[0]["pass_count"] == 2
        assert evaluated[0]["total_count"] == 2

    def test_evaluate_returns_layer_passed_false_when_any_test_fails(self, tmp_path):
        ev = self._make(tmp_path)
        layers = [Layer(name="L", tests=["t1", "t2"], threshold={"pass^k": 1.0})]
        results = {"t1": "PASSED", "t2": "FAILED"}
        evaluated = ev.evaluate(
            layers, results, durations_ms={"t1": 10, "t2": 20},
            errors={"t2": "AssertionError: nope"},
        )
        assert evaluated[0]["layer_passed"] is False
        assert evaluated[0]["pass_count"] == 1

    def test_evaluate_records_per_test_status_duration_and_error(self, tmp_path):
        ev = self._make(tmp_path)
        layers = [Layer(name="L", tests=["t1"], threshold={"pass^k": 1.0})]
        evaluated = ev.evaluate(
            layers, {"t1": "FAILED"}, durations_ms={"t1": 42},
            errors={"t1": "boom"},
        )
        test = evaluated[0]["tests"][0]
        assert test == {"id": "t1", "status": "FAILED", "duration_ms": 42, "error": "boom"}

    def test_evaluate_omits_error_field_when_test_passed(self, tmp_path):
        ev = self._make(tmp_path)
        layers = [Layer(name="L", tests=["t1"], threshold={"pass^k": 1.0})]
        evaluated = ev.evaluate(layers, {"t1": "PASSED"}, durations_ms={"t1": 5}, errors={})
        assert "error" not in evaluated[0]["tests"][0]

    def test_evaluate_missing_result_marks_test_as_error(self, tmp_path):
        ev = self._make(tmp_path)
        layers = [Layer(name="L", tests=["t_missing"], threshold={"pass^k": 1.0})]
        evaluated = ev.evaluate(layers, {}, durations_ms={}, errors={})
        assert evaluated[0]["tests"][0]["status"] == "ERROR"
        assert evaluated[0]["layer_passed"] is False
