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

    def evaluate(
        self,
        layers: Sequence[Layer],
        results: dict[str, str],
        durations_ms: dict[str, int],
        errors: dict[str, str],
    ) -> list[dict]:
        """Produce per-layer result records.

        results: test_id -> "PASSED" | "FAILED" | "ERROR" (missing keys treated as ERROR)
        durations_ms: test_id -> duration (missing keys default to 0)
        errors: test_id -> error text for non-PASSED tests
        """
        output: list[dict] = []
        for layer in layers:
            test_records: list[dict] = []
            pass_count = 0
            for test_id in layer.tests:
                status = results.get(test_id, "ERROR")
                record = {
                    "id": test_id,
                    "status": status,
                    "duration_ms": durations_ms.get(test_id, 0),
                }
                if status != "PASSED" and test_id in errors:
                    record["error"] = errors[test_id]
                if status != "PASSED" and "error" not in record and status == "ERROR":
                    record["error"] = "no result recorded for this test"
                if status == "PASSED":
                    pass_count += 1
                test_records.append(record)
            output.append({
                "name": layer.name,
                "description": layer.description,
                "threshold": layer.threshold,
                "tests": test_records,
                "pass_count": pass_count,
                "total_count": len(layer.tests),
                "layer_passed": pass_count == len(layer.tests),
            })
        return output

    def write_results(
        self,
        path: Path | str,
        *,
        trial: int,
        task: str,
        model: str,
        wall_time_s: float,
        total_cost_usd: float,
        total_tokens_in: int,
        total_tokens_out: int,
        completion_signal: str,
        layers: list[dict],
    ) -> None:
        out = {
            "trial": trial,
            "task": task,
            "model": model,
            "wall_time_s": wall_time_s,
            "total_cost_usd": total_cost_usd,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "completion_signal": completion_signal,
            "layers": layers,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2) + "\n")
