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
