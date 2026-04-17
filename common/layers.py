"""LayerEvaluator: load test_layers.json, run tests, emit per-trial results."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class Layer:
    name: str
    tests: list[str]
    threshold: dict[str, float]
    description: str = ""


class LayerEvaluator:
    def __init__(
        self,
        task_dir: Path | str,
        f2p_tests: Sequence[str],
        p2p_tests: Sequence[str],
    ):
        self.task_dir = Path(task_dir)
        self.f2p_tests = list(f2p_tests)
        self.p2p_tests = list(p2p_tests)

    def load_layers(self) -> list[Layer]:
        path = self.task_dir / "test_layers.json"
        if not path.exists():
            return self._fallback_layers()
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"failed to parse test_layers.json: {exc}") from exc
        if "layers" not in doc:
            raise ValueError("test_layers.json missing 'layers' key")

        layers: list[Layer] = []
        for entry in doc["layers"]:
            tests = self._expand_tokens(entry["tests"])
            layers.append(
                Layer(
                    name=entry["name"],
                    description=entry.get("description", ""),
                    tests=tests,
                    threshold=entry["threshold"],
                )
            )
        return layers

    def _expand_tokens(self, tests: Sequence[str]) -> list[str]:
        expanded: list[str] = []
        for test in tests:
            if test == "@F2P":
                expanded.extend(self.f2p_tests)
            elif test == "@P2P":
                expanded.extend(self.p2p_tests)
            else:
                expanded.append(test)
        return expanded

    def _fallback_layers(self) -> list[Layer]:
        return [
            Layer(
                name="F2P",
                description="Fail-to-Pass tests (fallback when test_layers.json absent)",
                tests=list(self.f2p_tests),
                threshold={"pass^k": 1.0},
            ),
            Layer(
                name="P2P",
                description="Pass-to-Pass tests (fallback when test_layers.json absent)",
                tests=list(self.p2p_tests),
                threshold={"pass^k": 1.0},
            ),
        ]
