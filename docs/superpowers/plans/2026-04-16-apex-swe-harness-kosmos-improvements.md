# apex-swe-harness Kosmos Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `apex-swe-harness` with per-run JSONL trajectory output, task-defined test layer groupings with pass@k/pass^k thresholds, state-level verifiers, trial aggregation with `eval_summary.md`, and distractor seeding conventions — all behind additive, backward-compatible changes.

**Architecture:** A new `common/` package (sibling to `integration/` and `observability/`) provides three modules — `trajectory.py`, `layers.py`, `trials.py` — that both sub-harnesses import via a `sys.path` prepend (no packaging overhead). Each sub-harness keeps its own venv, dispatch mechanism, and per-turn log format; the new code is bolted on as instrumentation, not a rewrite.

**Tech Stack:** Python 3.12, pytest, existing harness dependencies (LiteLLM for integration, inspect-ai for observability). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-16-apex-swe-harness-kosmos-improvements-design.md`

---

## Ground rules for every task

1. **TDD:** write the failing test first, verify it fails for the right reason, then write the minimal code to make it pass, then verify it passes.
2. **Run tests from the integration venv:** `cd integration && venv/bin/pytest ../common/tests/<specific_test>.py -v`. The integration venv already has pytest. Observability tests run from its own venv when invoked there.
3. **Commit after each green chunk** using the commit message shown in the final step of each task. No amending; new commit per step.
4. **Absolute paths from the repo root** (`/Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/`) in all file references below.
5. **Preserve existing behavior:** if `test_layers.json` or `hints.json` is absent, the harness behaves exactly as it does today. Unit tests must verify this.

---

## File Structure

**New files (under `common/`):**

```
common/
├── __init__.py                     # empty marker
├── schemas.py                      # TypedDicts for trajectory events, layer results, trial results
├── trajectory.py                   # TrajectoryWriter — append-only JSONL writer with envelope validation
├── layers.py                       # LayerEvaluator — loads test_layers.json, runs tests, emits per-trial results.json
├── trials.py                       # Aggregator — reads trial_NN/results.json, emits eval_summary.{md,json}
├── path_utils.py                   # Repo root discovery + sys.path helper, used by both sub-harnesses
├── pytest.ini                      # pytest config for common tests
└── tests/
    ├── __init__.py
    ├── conftest.py                 # shared fixtures: tmp_runs_dir, fake_trajectory, fake_results_json
    ├── test_schemas.py
    ├── test_trajectory.py
    ├── test_layers.py
    ├── test_trials.py
    ├── test_path_utils.py
    └── fixtures/
        ├── test_layers_basic.json
        ├── test_layers_with_tokens.json
        ├── sample_trajectory.jsonl
        └── sample_results_trial_01.json
```

**Modified files (integration):**

- `integration/src/main.py:49-51` — rename flags with deprecation shim
- `integration/src/main.py` (new block at end of dispatch) — post-dispatch aggregation call
- `integration/src/harness/multi_step_runner.py` — emit trajectory events at XML-parse points
- `integration/src/harness/evaluator.py` — swap flat F2P/P2P evaluation for LayerEvaluator
- `integration/README.md` — flag-rename and `trial_01/` path notes

**Modified files (observability):**

- `observability/run_e2e.py:620` — rename `--parallel` → `--workers` with deprecation shim
- `observability/run_e2e.py` (new block at end of batch dispatch) — post-dispatch aggregation call
- `observability/eval_runner/runner.py` — normalize inspect-ai transcript into trajectory events
- `observability/eval_runner/inspect_scorer.py` — swap F2P/P2P check for LayerEvaluator
- `observability/README.md` — flag-rename and `trial_01/` path notes

**Task-authoring docs:**

- `tasks/README.md` (new at repo root, or update existing nearest equivalent) — layer/verifier/distractor conventions; `hints.json` reservation

---

## Task 1: Scaffold `common/` package and wire up test runner

**Files:**
- Create: `common/__init__.py`
- Create: `common/pytest.ini`
- Create: `common/tests/__init__.py`
- Create: `common/tests/conftest.py`
- Create: `common/tests/test_sanity.py`

- [ ] **Step 1: Create the package skeleton**

Create `common/__init__.py` with this exact content:

```python
"""Shared instrumentation for integration and observability sub-harnesses."""
```

Create `common/tests/__init__.py` as an empty file (0 bytes).

Create `common/pytest.ini` with this content:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 2: Write a sanity test that verifies the package is importable**

Create `common/tests/test_sanity.py` with:

```python
import importlib


def test_common_package_importable():
    module = importlib.import_module("common")
    assert module.__doc__ is not None
```

Create `common/tests/conftest.py` with:

```python
"""Shared pytest fixtures for common tests."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
```

- [ ] **Step 3: Run the test and verify it passes**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_sanity.py -v`

Expected: `1 passed` with `test_common_package_importable` PASSED.

If you get `ModuleNotFoundError: No module named 'common'`, verify `conftest.py` exists at `common/tests/conftest.py` and the path calculation resolves to the `apex-swe-harness/` directory.

- [ ] **Step 4: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/
git commit -m "common: scaffold package with pytest sanity test

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Define schemas in `common/schemas.py`

**Files:**
- Create: `common/schemas.py`
- Create: `common/tests/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

Create `common/tests/test_schemas.py` with:

```python
"""Tests for common.schemas type definitions and validators."""
import pytest

from common import schemas


class TestEventTypes:
    def test_event_types_constant_lists_all_four(self):
        assert set(schemas.EVENT_TYPES) == {"reasoning", "tool_call", "tool_result", "completion"}

    def test_completion_signals_constant(self):
        assert set(schemas.COMPLETION_SIGNALS) == {"task_complete", "timeout", "max_steps", "error"}


class TestValidateEvent:
    def test_valid_reasoning_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "reasoning",
            "content": "plan...",
            "tokens_in": 100,
            "tokens_out": 20,
            "latency_ms": 500,
            "cost_usd": 0.002,
        }
        schemas.validate_event(event)  # no raise

    def test_valid_tool_call_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "tool_call",
            "tool": "bash",
            "args": {"cmd": "ls"},
            "call_id": "c_01",
        }
        schemas.validate_event(event)

    def test_valid_tool_result_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "tool_result",
            "call_id": "c_01",
            "status": "success",
            "exit_code": 0,
            "stdout_bytes": 100,
            "content": "ok",
        }
        schemas.validate_event(event)

    def test_valid_completion_event_passes(self):
        event = {
            "step": 12,
            "ts": "2026-04-16T14:28:44.771Z",
            "type": "completion",
            "signal": "task_complete",
            "total_tokens_in": 1000,
            "total_tokens_out": 200,
            "total_cost_usd": 0.1,
            "wall_time_s": 100,
        }
        schemas.validate_event(event)

    def test_missing_envelope_field_raises(self):
        event = {"type": "reasoning", "content": "x"}  # missing step, ts
        with pytest.raises(schemas.SchemaError, match="step"):
            schemas.validate_event(event)

    def test_unknown_type_raises(self):
        event = {"step": 1, "ts": "x", "type": "bogus"}
        with pytest.raises(schemas.SchemaError, match="bogus"):
            schemas.validate_event(event)

    def test_type_specific_missing_field_raises(self):
        event = {"step": 1, "ts": "x", "type": "tool_call", "tool": "bash"}  # missing args, call_id
        with pytest.raises(schemas.SchemaError, match="call_id"):
            schemas.validate_event(event)

    def test_invalid_completion_signal_raises(self):
        event = {
            "step": 1,
            "ts": "x",
            "type": "completion",
            "signal": "bogus",
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost_usd": 0.0,
            "wall_time_s": 0,
        }
        with pytest.raises(schemas.SchemaError, match="signal"):
            schemas.validate_event(event)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_schemas.py -v`

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'common.schemas'` or similar.

- [ ] **Step 3: Write the implementation**

Create `common/schemas.py` with:

```python
"""Schema definitions and validators for trajectory events, layer results, and trial results."""
from __future__ import annotations

EVENT_TYPES = ("reasoning", "tool_call", "tool_result", "completion")
COMPLETION_SIGNALS = ("task_complete", "timeout", "max_steps", "error")

_ENVELOPE_FIELDS = ("step", "ts", "type")

_TYPE_REQUIRED_FIELDS = {
    "reasoning": ("content", "tokens_in", "tokens_out", "latency_ms", "cost_usd"),
    "tool_call": ("tool", "args", "call_id"),
    "tool_result": ("call_id", "status", "exit_code", "stdout_bytes", "content"),
    "completion": ("signal", "total_tokens_in", "total_tokens_out", "total_cost_usd", "wall_time_s"),
}


class SchemaError(ValueError):
    """Raised when a trajectory event fails validation."""


def validate_event(event: dict) -> None:
    """Validate a trajectory event dict. Raises SchemaError on failure."""
    for field in _ENVELOPE_FIELDS:
        if field not in event:
            raise SchemaError(f"missing required envelope field: {field!r}")
    event_type = event["type"]
    if event_type not in EVENT_TYPES:
        raise SchemaError(f"unknown event type: {event_type!r} (valid: {EVENT_TYPES})")
    for field in _TYPE_REQUIRED_FIELDS[event_type]:
        if field not in event:
            raise SchemaError(f"missing field {field!r} for event type {event_type!r}")
    if event_type == "completion" and event["signal"] not in COMPLETION_SIGNALS:
        raise SchemaError(
            f"invalid completion signal: {event['signal']!r} (valid: {COMPLETION_SIGNALS})"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_schemas.py -v`

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/schemas.py common/tests/test_schemas.py
git commit -m "common: add schemas module with trajectory event validators

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `TrajectoryWriter` in `common/trajectory.py`

**Files:**
- Create: `common/trajectory.py`
- Create: `common/tests/test_trajectory.py`

- [ ] **Step 1: Write the failing tests**

Create `common/tests/test_trajectory.py` with:

```python
"""Tests for TrajectoryWriter."""
import json
from pathlib import Path

import pytest

from common.trajectory import TrajectoryWriter
from common.schemas import SchemaError


class TestTrajectoryWriter:
    def test_writes_jsonl_one_event_per_line(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        writer = TrajectoryWriter(path)
        writer.write(
            step=1,
            ts="2026-04-16T14:22:08.123Z",
            type="reasoning",
            content="plan",
            tokens_in=10,
            tokens_out=5,
            latency_ms=100,
            cost_usd=0.001,
        )
        writer.write(
            step=1,
            ts="2026-04-16T14:22:09.000Z",
            type="tool_call",
            tool="bash",
            args={"cmd": "ls"},
            call_id="c_01",
        )
        writer.close()

        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "reasoning"
        assert json.loads(lines[1])["type"] == "tool_call"

    def test_truncates_tool_result_content_and_records_original_size(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        writer = TrajectoryWriter(path, max_content_bytes=100)
        big_content = "x" * 5000
        writer.write(
            step=1,
            ts="t",
            type="tool_result",
            call_id="c_01",
            status="success",
            exit_code=0,
            stdout_bytes=5000,
            content=big_content,
        )
        writer.close()

        event = json.loads(path.read_text().splitlines()[0])
        assert event["stdout_bytes"] == 5000
        assert len(event["content"]) < 5000
        assert event["content"].endswith("...[truncated]")

    def test_rejects_invalid_event(self, tmp_path):
        writer = TrajectoryWriter(tmp_path / "trajectory.jsonl")
        with pytest.raises(SchemaError):
            writer.write(step=1, ts="t", type="bogus")
        writer.close()

    def test_context_manager_closes_file(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        with TrajectoryWriter(path) as writer:
            writer.write(
                step=1,
                ts="t",
                type="reasoning",
                content="x",
                tokens_in=0,
                tokens_out=0,
                latency_ms=0,
                cost_usd=0.0,
            )
        # File should exist and contain exactly one line
        assert len(path.read_text().splitlines()) == 1

    def test_appends_to_existing_file(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        with TrajectoryWriter(path) as w1:
            w1.write(
                step=1, ts="t", type="reasoning", content="a",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        with TrajectoryWriter(path) as w2:
            w2.write(
                step=2, ts="t", type="reasoning", content="b",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        assert len(path.read_text().splitlines()) == 2

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "trajectory.jsonl"
        with TrajectoryWriter(path) as writer:
            writer.write(
                step=1, ts="t", type="reasoning", content="x",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        assert path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trajectory.py -v`

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'common.trajectory'`.

- [ ] **Step 3: Write the implementation**

Create `common/trajectory.py` with:

```python
"""TrajectoryWriter: append-only JSONL writer with schema validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from common.schemas import validate_event

DEFAULT_MAX_CONTENT_BYTES = 16 * 1024
_TRUNCATION_SUFFIX = "...[truncated]"


class TrajectoryWriter:
    def __init__(self, path: Path | str, max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES):
        self.path = Path(path)
        self.max_content_bytes = max_content_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, **event) -> None:
        if event.get("type") == "tool_result":
            content = event.get("content", "")
            if isinstance(content, str) and len(content) > self.max_content_bytes:
                keep = self.max_content_bytes - len(_TRUNCATION_SUFFIX)
                event["content"] = content[:keep] + _TRUNCATION_SUFFIX
        validate_event(event)
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "TrajectoryWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trajectory.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/trajectory.py common/tests/test_trajectory.py
git commit -m "common: add TrajectoryWriter for JSONL event output

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement `LayerEvaluator` — load `test_layers.json` with fallback

**Files:**
- Create: `common/layers.py`
- Create: `common/tests/test_layers.py`
- Create: `common/tests/fixtures/test_layers_basic.json`
- Create: `common/tests/fixtures/test_layers_with_tokens.json`

- [ ] **Step 1: Create fixture files**

Create `common/tests/fixtures/test_layers_basic.json`:

```json
{
  "version": 1,
  "layers": [
    {
      "name": "Gate",
      "description": "Basic setup invariants",
      "tests": ["tests/verifiers/script_exists.sh"],
      "threshold": { "pass^k": 1.0 }
    },
    {
      "name": "Functional",
      "description": "Core feature tests",
      "tests": ["tests/test_filters.py::test_active", "tests/test_filters.py::test_dedup"],
      "threshold": { "pass@k": 0.80 }
    }
  ]
}
```

Create `common/tests/fixtures/test_layers_with_tokens.json`:

```json
{
  "version": 1,
  "layers": [
    { "name": "Functional", "tests": ["@F2P"], "threshold": { "pass^k": 1.0 } },
    { "name": "Regression", "tests": ["@P2P"], "threshold": { "pass^k": 1.0 } }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `common/tests/test_layers.py` with:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py -v`

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'common.layers'`.

- [ ] **Step 4: Write the implementation**

Create `common/layers.py` with:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py -v`

Expected: all 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/layers.py common/tests/test_layers.py common/tests/fixtures/
git commit -m "common: add LayerEvaluator.load_layers with @F2P/@P2P token expansion

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `LayerEvaluator` — evaluate layers against test results

**Files:**
- Modify: `common/layers.py`
- Modify: `common/tests/test_layers.py`

Note: This task assumes the caller has already produced a `dict[str, str]` mapping test_id → "PASSED"/"FAILED"/"ERROR". Actually running test scripts is delegated to the sub-harness's existing evaluator (see Task 8). This task implements the pure bookkeeping logic.

- [ ] **Step 1: Write the failing tests (append to test_layers.py)**

Append to `common/tests/test_layers.py`:

```python


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py::TestEvaluate -v`

Expected: all 5 tests FAIL with `AttributeError: 'LayerEvaluator' object has no attribute 'evaluate'`.

- [ ] **Step 3: Implement `evaluate` in `common/layers.py`**

Append to `common/layers.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py -v`

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/layers.py common/tests/test_layers.py
git commit -m "common: add LayerEvaluator.evaluate for per-layer result aggregation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `LayerEvaluator` — write `results.json` for a trial

**Files:**
- Modify: `common/layers.py`
- Modify: `common/tests/test_layers.py`

- [ ] **Step 1: Write the failing tests**

Append to `common/tests/test_layers.py`:

```python


class TestWriteResultsJson:
    def test_write_results_creates_well_formed_json(self, tmp_path):
        ev = LayerEvaluator(task_dir=tmp_path, f2p_tests=[], p2p_tests=[])
        evaluated = [
            {
                "name": "Gate",
                "description": "",
                "threshold": {"pass^k": 1.0},
                "tests": [{"id": "a.sh", "status": "PASSED", "duration_ms": 10}],
                "pass_count": 1,
                "total_count": 1,
                "layer_passed": True,
            }
        ]
        out_path = tmp_path / "results.json"
        ev.write_results(
            out_path,
            trial=1,
            task="crm_debug",
            model="claude-opus-4-7",
            wall_time_s=100,
            total_cost_usd=0.5,
            total_tokens_in=1000,
            total_tokens_out=200,
            completion_signal="task_complete",
            layers=evaluated,
        )

        data = json.loads(out_path.read_text())
        assert data["trial"] == 1
        assert data["task"] == "crm_debug"
        assert data["model"] == "claude-opus-4-7"
        assert data["completion_signal"] == "task_complete"
        assert data["layers"] == evaluated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py::TestWriteResultsJson -v`

Expected: FAIL with `AttributeError: … 'write_results'`.

- [ ] **Step 3: Implement `write_results` in `common/layers.py`**

Append to `common/layers.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_layers.py -v`

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/layers.py common/tests/test_layers.py
git commit -m "common: add LayerEvaluator.write_results for per-trial results.json

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Trial aggregation — pass@k, pass^k, per-layer totals

**Files:**
- Create: `common/trials.py`
- Create: `common/tests/test_trials.py`
- Create: `common/tests/fixtures/sample_results_trial_01.json`
- Create: `common/tests/fixtures/sample_results_trial_02.json`
- Create: `common/tests/fixtures/sample_results_trial_03.json`

- [ ] **Step 1: Create fixture files**

Create `common/tests/fixtures/sample_results_trial_01.json`:

```json
{
  "trial": 1,
  "task": "crm_debug",
  "model": "claude-opus-4-7",
  "wall_time_s": 100,
  "total_cost_usd": 0.5,
  "total_tokens_in": 1000,
  "total_tokens_out": 200,
  "completion_signal": "task_complete",
  "layers": [
    {
      "name": "Gate",
      "description": "",
      "threshold": {"pass^k": 1.0},
      "tests": [{"id": "a.sh", "status": "PASSED", "duration_ms": 10}],
      "pass_count": 1,
      "total_count": 1,
      "layer_passed": true
    },
    {
      "name": "Functional",
      "description": "",
      "threshold": {"pass@k": 0.80},
      "tests": [
        {"id": "t1", "status": "PASSED", "duration_ms": 20},
        {"id": "t2", "status": "PASSED", "duration_ms": 30}
      ],
      "pass_count": 2,
      "total_count": 2,
      "layer_passed": true
    }
  ]
}
```

Create `common/tests/fixtures/sample_results_trial_02.json` (identical to trial_01 but with trial field = 2):

```json
{
  "trial": 2,
  "task": "crm_debug",
  "model": "claude-opus-4-7",
  "wall_time_s": 110,
  "total_cost_usd": 0.45,
  "total_tokens_in": 1100,
  "total_tokens_out": 210,
  "completion_signal": "task_complete",
  "layers": [
    {
      "name": "Gate",
      "description": "",
      "threshold": {"pass^k": 1.0},
      "tests": [{"id": "a.sh", "status": "PASSED", "duration_ms": 10}],
      "pass_count": 1,
      "total_count": 1,
      "layer_passed": true
    },
    {
      "name": "Functional",
      "description": "",
      "threshold": {"pass@k": 0.80},
      "tests": [
        {"id": "t1", "status": "PASSED", "duration_ms": 20},
        {"id": "t2", "status": "PASSED", "duration_ms": 30}
      ],
      "pass_count": 2,
      "total_count": 2,
      "layer_passed": true
    }
  ]
}
```

Create `common/tests/fixtures/sample_results_trial_03.json` — same structure but trial 3 has the Functional layer fail:

```json
{
  "trial": 3,
  "task": "crm_debug",
  "model": "claude-opus-4-7",
  "wall_time_s": 120,
  "total_cost_usd": 0.55,
  "total_tokens_in": 1200,
  "total_tokens_out": 220,
  "completion_signal": "task_complete",
  "layers": [
    {
      "name": "Gate",
      "description": "",
      "threshold": {"pass^k": 1.0},
      "tests": [{"id": "a.sh", "status": "PASSED", "duration_ms": 10}],
      "pass_count": 1,
      "total_count": 1,
      "layer_passed": true
    },
    {
      "name": "Functional",
      "description": "",
      "threshold": {"pass@k": 0.80},
      "tests": [
        {"id": "t1", "status": "PASSED", "duration_ms": 20},
        {"id": "t2", "status": "FAILED", "duration_ms": 30, "error": "boom"}
      ],
      "pass_count": 1,
      "total_count": 2,
      "layer_passed": false
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `common/tests/test_trials.py` with:

```python
"""Tests for trial aggregation."""
import json
import shutil
from pathlib import Path

from common.trials import aggregate_trials

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trials.py -v`

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'common.trials'`.

- [ ] **Step 4: Write the implementation**

Create `common/trials.py` with:

```python
"""Trial aggregation: pass@k, pass^k, per-layer totals, holistic metrics."""
from __future__ import annotations

import json
from pathlib import Path


def aggregate_trials(run_dir: Path | str) -> dict:
    """Read trial_NN/results.json files from run_dir and produce aggregated metrics."""
    run_dir = Path(run_dir)
    trial_dirs = sorted(d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("trial_"))
    if not trial_dirs:
        raise ValueError(f"no trial_* directories found under {run_dir}")

    trials: list[dict] = []
    for d in trial_dirs:
        path = d / "results.json"
        if not path.exists():
            raise ValueError(f"missing results.json in {d}")
        trials.append(json.loads(path.read_text()))

    # Per-layer aggregation
    layer_names = [l["name"] for l in trials[0]["layers"]]
    layers_agg: list[dict] = []
    for name in layer_names:
        per_trial = [next(l for l in t["layers"] if l["name"] == name) for t in trials]
        pass_count_trials = sum(1 for l in per_trial if l["layer_passed"])
        n = len(trials)
        pass_at_k = 1.0 if pass_count_trials >= 1 else 0.0
        pass_power_k = 1.0 if pass_count_trials == n else 0.0
        pass_rate = pass_count_trials / n

        threshold = per_trial[0]["threshold"]
        verdict = _verdict(threshold, pass_at_k, pass_power_k, pass_rate)

        tests_passed_total = sum(l["pass_count"] for l in per_trial)
        tests_total = sum(l["total_count"] for l in per_trial)

        layers_agg.append({
            "name": name,
            "description": per_trial[0].get("description", ""),
            "threshold": threshold,
            "pass_at_k": pass_at_k,
            "pass_power_k": pass_power_k,
            "pass_rate": pass_rate,
            "tests_passed_total": tests_passed_total,
            "tests_total": tests_total,
            "verdict": verdict,
            "per_trial": [
                {"trial": t["trial"], "layer_passed": l["layer_passed"],
                 "pass_count": l["pass_count"], "total_count": l["total_count"]}
                for t, l in zip(trials, per_trial)
            ],
        })

    holistic_pass_at_k = 1.0 if any(
        all(l["layer_passed"] for l in t["layers"]) for t in trials
    ) else 0.0
    holistic_pass_power_k = 1.0 if all(
        all(l["layer_passed"] for l in t["layers"]) for t in trials
    ) else 0.0

    return {
        "task": trials[0]["task"],
        "model": trials[0]["model"],
        "trial_count": len(trials),
        "total_cost_usd": sum(t["total_cost_usd"] for t in trials),
        "total_tokens_in": sum(t["total_tokens_in"] for t in trials),
        "total_tokens_out": sum(t["total_tokens_out"] for t in trials),
        "avg_wall_time_s": sum(t["wall_time_s"] for t in trials) / len(trials),
        "layers": layers_agg,
        "holistic": {
            "pass_at_k": holistic_pass_at_k,
            "pass_power_k": holistic_pass_power_k,
        },
        "trials": trials,
    }


def _verdict(threshold: dict, pass_at_k: float, pass_power_k: float, pass_rate: float) -> str:
    if "pass^k" in threshold:
        return "PASS" if pass_power_k >= threshold["pass^k"] else "FAIL"
    if "pass@k" in threshold:
        return "PASS" if pass_rate >= threshold["pass@k"] else "FAIL"
    raise ValueError(f"unknown threshold: {threshold}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trials.py -v`

Expected: all 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/trials.py common/tests/test_trials.py common/tests/fixtures/
git commit -m "common: add aggregate_trials for pass@k/pass^k computation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Trial aggregation — `eval_summary.md` and `eval_summary.json` writers

**Files:**
- Modify: `common/trials.py`
- Modify: `common/tests/test_trials.py`

- [ ] **Step 1: Write the failing tests**

Append to `common/tests/test_trials.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trials.py::TestWriteEvalSummary -v`

Expected: FAIL with `ImportError: cannot import name 'write_eval_summary'`.

- [ ] **Step 3: Write the implementation**

Append to `common/trials.py`:

```python
def write_eval_summary(run_dir: Path | str, agg: dict) -> None:
    run_dir = Path(run_dir)
    (run_dir / "eval_summary.json").write_text(json.dumps(agg, indent=2) + "\n")
    (run_dir / "eval_summary.md").write_text(_render_markdown(agg))


def _render_markdown(agg: dict) -> str:
    k = agg["trial_count"]
    lines: list[str] = []
    lines.append(f"# Eval Summary — {agg['task']}")
    lines.append("")
    lines.append(f"**Model:** {agg['model']}")
    lines.append(f"**Trials:** {k}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- pass@{k}: {_verdict_text(agg['holistic']['pass_at_k'])}")
    lines.append(f"- pass^{k}: {_verdict_text(agg['holistic']['pass_power_k'])}")
    lines.append("")

    lines.append("## Per-Layer Results")
    lines.append("")
    header = (
        "| Layer | Threshold | Tests Passed (all trials) | "
        + " | ".join(f"Trial {i}" for i in range(1, k + 1))
        + f" | pass@k | pass^k | Verdict |"
    )
    sep = "|" + "|".join("---" for _ in range(4 + k + 2)) + "|"
    lines.append(header)
    lines.append(sep)
    for layer in agg["layers"]:
        tests_total_col = f"{layer['tests_passed_total']}/{layer['tests_total']}"
        trial_cells = []
        for pt in layer["per_trial"]:
            trial_cells.append(f"{pt['pass_count']}/{pt['total_count']}")
        threshold_text = _threshold_text(layer["threshold"])
        row = (
            f"| {layer['name']} | {threshold_text} | {tests_total_col} | "
            + " | ".join(trial_cells)
            + f" | {layer['pass_at_k']:.2f} | {layer['pass_power_k']:.2f} | {layer['verdict']} |"
        )
        lines.append(row)
    lines.append("")

    lines.append("## Cost & Latency")
    lines.append(f"- Total cost: ${agg['total_cost_usd']:.2f}")
    lines.append(f"- Avg cost per trial: ${agg['total_cost_usd']/k:.2f}")
    lines.append(f"- Avg wall time per trial: {agg['avg_wall_time_s']:.0f}s")
    lines.append("")

    lines.append("## Failed Tests")
    any_failed = False
    for trial in agg["trials"]:
        failures = []
        for layer in trial["layers"]:
            for t in layer["tests"]:
                if t["status"] != "PASSED":
                    err = t.get("error", "")
                    failures.append(f"- `{t['id']}` ({layer['name']}) — {err}")
        if failures:
            any_failed = True
            lines.append("")
            lines.append(f"### Trial {trial['trial']}")
            lines.extend(failures)
    if not any_failed:
        lines.append("")
        lines.append("_No failed tests across all trials._")
    lines.append("")

    return "\n".join(lines)


def _verdict_text(value: float) -> str:
    return "PASS" if value == 1.0 else "FAIL"


def _threshold_text(threshold: dict) -> str:
    if "pass^k" in threshold:
        return f"pass^k={threshold['pass^k']}"
    if "pass@k" in threshold:
        return f"pass@k≥{threshold['pass@k']}"
    return str(threshold)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_trials.py -v`

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/trials.py common/tests/test_trials.py
git commit -m "common: add eval_summary.{md,json} writers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `common/path_utils.py` — sys.path helper for sub-harnesses

**Files:**
- Create: `common/path_utils.py`
- Create: `common/tests/test_path_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `common/tests/test_path_utils.py`:

```python
"""Tests for sys.path helper."""
import sys
from pathlib import Path

from common.path_utils import prepend_repo_root_to_path, repo_root


class TestPathUtils:
    def test_repo_root_returns_apex_swe_harness_dir(self):
        root = repo_root()
        assert root.name == "apex-swe-harness"
        assert (root / "integration").is_dir()
        assert (root / "observability").is_dir()
        assert (root / "common").is_dir()

    def test_prepend_idempotent(self):
        root = repo_root()
        prepend_repo_root_to_path()
        count_first = sum(1 for p in sys.path if p == str(root))
        prepend_repo_root_to_path()
        count_second = sum(1 for p in sys.path if p == str(root))
        assert count_first == count_second == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_path_utils.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'common.path_utils'`.

- [ ] **Step 3: Write the implementation**

Create `common/path_utils.py`:

```python
"""Helpers for locating the apex-swe-harness repo root and wiring up sys.path."""
from __future__ import annotations

import sys
from pathlib import Path


def repo_root() -> Path:
    """Return the absolute path to the apex-swe-harness repo root."""
    # This file lives at <repo>/common/path_utils.py
    return Path(__file__).resolve().parent.parent


def prepend_repo_root_to_path() -> None:
    """Prepend the repo root to sys.path if not already present."""
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest ../common/tests/test_path_utils.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add common/path_utils.py common/tests/test_path_utils.py
git commit -m "common: add path_utils for sys.path wiring

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Integration — wire `TrajectoryWriter` into `multi_step_runner.py`

**Files:**
- Modify: `integration/src/harness/multi_step_runner.py`
- Create: `integration/tests/test_trajectory_emission.py`

Before starting, open `integration/src/harness/multi_step_runner.py` and identify:
- The main step loop where a single ReAct iteration runs
- The point where the LLM response is parsed (XML tags: `<analysis>`, `<plan>`, `<commands>`, `<task_complete>`)
- The point where tool commands are executed
- The point where the loop exits

The concrete line numbers vary — use Grep/Read to find them before editing.

- [ ] **Step 1: Identify the integration points**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "def run\|response\|task_complete\|command\|step_num" integration/src/harness/multi_step_runner.py | head -40`

Record the line numbers where:
- The main run loop begins (a `while` or `for` over steps)
- LLM responses are parsed
- Tool/command execution happens
- The loop terminates (task_complete, timeout, max steps)

- [ ] **Step 2: Write the failing integration test**

Create `integration/tests/__init__.py` as an empty file if it doesn't exist.

Create `integration/tests/test_trajectory_emission.py` with:

```python
"""Test that MultiStepRunner emits trajectory events when configured with a writer."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make common/ importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.trajectory import TrajectoryWriter


def test_trajectory_writer_receives_reasoning_tool_call_result_completion(tmp_path, monkeypatch):
    """Run MultiStepRunner with a mocked LLM; verify events land in trajectory.jsonl."""
    traj_path = tmp_path / "trajectory.jsonl"

    # This test validates the wiring: replace the LLM client and tool executor with
    # fakes that produce a single reasoning step, a single bash tool call, a fake
    # result, and a task_complete signal.
    # See integration/src/harness/multi_step_runner.py for the injection points.

    from src.harness.multi_step_runner import MultiStepRunner

    # This test exercises the emission helpers directly without instantiating
    # MultiStepRunner through its normal __init__ (which requires a live config).
    # The helpers themselves are pure — they just call self.trajectory_writer.write.
    runner = MultiStepRunner.__new__(MultiStepRunner)
    writer = TrajectoryWriter(traj_path)
    runner.trajectory_writer = writer

    # Directly exercise the emission helpers (unit-level)
    runner._emit_reasoning(step=1, content="plan", tokens_in=10, tokens_out=5,
                            latency_ms=100, cost_usd=0.001,
                            ts="2026-04-16T00:00:00.000Z")
    runner._emit_tool_call(step=1, tool="bash", args={"cmd": "ls"},
                            call_id="c_01", ts="2026-04-16T00:00:01.000Z")
    runner._emit_tool_result(step=1, call_id="c_01", status="success",
                              exit_code=0, stdout_bytes=10, content="ok",
                              ts="2026-04-16T00:00:02.000Z")
    runner._emit_completion(step=2, signal="task_complete",
                             total_tokens_in=10, total_tokens_out=5,
                             total_cost_usd=0.001, wall_time_s=5.0,
                             ts="2026-04-16T00:00:03.000Z")
    writer.close()

    events = [json.loads(l) for l in traj_path.read_text().splitlines()]
    assert [e["type"] for e in events] == ["reasoning", "tool_call", "tool_result", "completion"]
    assert events[1]["tool"] == "bash"
    assert events[1]["args"] == {"cmd": "ls"}
    assert events[3]["signal"] == "task_complete"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/test_trajectory_emission.py -v`

Expected: FAIL with `AttributeError: … '_emit_reasoning'` (and friends).

- [ ] **Step 4: Implement emission helpers in `multi_step_runner.py`**

Add at the top of `integration/src/harness/multi_step_runner.py` (after existing imports):

```python
import sys
from pathlib import Path

# Wire common/ into sys.path for import. Safe to run multiple times.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.trajectory import TrajectoryWriter  # noqa: E402
```

Add the following methods to the `MultiStepRunner` class (place them as a new block near the end of the class body, before any private helpers but after `__init__`):

```python
    def _emit_reasoning(self, *, step: int, content: str, tokens_in: int,
                        tokens_out: int, latency_ms: int, cost_usd: float,
                        ts: str) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step, ts=ts, type="reasoning", content=content,
            tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=latency_ms, cost_usd=cost_usd,
        )

    def _emit_tool_call(self, *, step: int, tool: str, args: dict,
                        call_id: str, ts: str) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step, ts=ts, type="tool_call",
            tool=tool, args=args, call_id=call_id,
        )

    def _emit_tool_result(self, *, step: int, call_id: str, status: str,
                          exit_code: int, stdout_bytes: int, content: str,
                          ts: str) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step, ts=ts, type="tool_result", call_id=call_id,
            status=status, exit_code=exit_code,
            stdout_bytes=stdout_bytes, content=content,
        )

    def _emit_completion(self, *, step: int, signal: str,
                         total_tokens_in: int, total_tokens_out: int,
                         total_cost_usd: float, wall_time_s: float,
                         ts: str) -> None:
        if self.trajectory_writer is None:
            return
        self.trajectory_writer.write(
            step=step, ts=ts, type="completion", signal=signal,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_cost_usd=total_cost_usd,
            wall_time_s=wall_time_s,
        )
```

Update `__init__` to accept an optional `trajectory_writer`. Find the existing `__init__` signature and add `trajectory_writer: "TrajectoryWriter | None" = None` as a new keyword-only parameter. Assign `self.trajectory_writer = trajectory_writer`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/test_trajectory_emission.py -v`

Expected: test PASSES.

- [ ] **Step 6: Wire emission into the actual step loop**

Find the step loop in `multi_step_runner.py` (search for the main iteration — e.g., `for step_num in range` or `while`).

At each emission point, add the emit call. Exact hook points:

- **After the LLM response is received and parsed**: call `self._emit_reasoning(...)` with the parsed analysis/plan content. Use LiteLLM's response metadata for tokens/cost/latency — these are on the `response` object (e.g., `response.usage.prompt_tokens`, `response._hidden_params['response_cost']`, `response._response_ms`).
- **For each tool command parsed out of `<commands>`**: call `self._emit_tool_call(...)` before execution with a fresh `call_id = f"c_{uuid4().hex[:8]}"`.
- **After each tool command returns**: call `self._emit_tool_result(...)` with the same `call_id`.
- **After the loop exits** (task_complete / timeout / max_steps): call `self._emit_completion(...)` with accumulated totals.

Use `datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")` for `ts`.

**Do not rename any existing variables or change control flow.** Only add emission calls.

- [ ] **Step 7: Run full integration test suite**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/ -v`

Expected: all tests pass (including new trajectory test).

- [ ] **Step 8: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add integration/src/harness/multi_step_runner.py integration/tests/
git commit -m "integration: wire TrajectoryWriter into MultiStepRunner step loop

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Integration — swap flat F2P/P2P for `LayerEvaluator` in `evaluator.py`

**Files:**
- Modify: `integration/src/harness/evaluator.py`
- Create: `integration/tests/test_evaluator_layers.py`

**Note on bash verifier scripts:** The existing integration evaluator runs the task's main test script (e.g., `run_tests.sh`) and parses PASSED/FAILED per test ID. Task authors are responsible for ensuring that bash verifier scripts listed in `test_layers.json` (e.g., `tests/verifiers/queried_mattermost.sh`) are invoked from their main test script, so their results appear in the same test-id map. No harness code change is required for this — it's a task-authoring convention (documented in Task 18). If a specific task has verifier scripts that the main test runner doesn't know about, those test IDs will appear as `ERROR` in the results (missing keys default to ERROR per Task 5's `evaluate` method), which is correct behavior.

- [ ] **Step 1: Read the current evaluate_execution signature**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "def evaluate_execution\|def evaluate_run\|def evaluate_process\|return {" integration/src/harness/evaluator.py | head -20`

Note the method that currently returns F2P/P2P pass counts — that's the target for extension.

- [ ] **Step 2: Write the failing test**

Create `integration/tests/test_evaluator_layers.py`:

```python
"""Test that evaluator uses LayerEvaluator when test_layers.json is present."""
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_evaluator_writes_results_json_with_layers(tmp_path, monkeypatch):
    """
    Given a task directory with test_layers.json and a fake test-run output,
    the evaluator should produce a per-trial results.json with layer entries.
    """
    # Arrange: task dir with test_layers.json
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "test_layers.json").write_text(json.dumps({
        "version": 1,
        "layers": [
            {"name": "F2P", "tests": ["@F2P"], "threshold": {"pass^k": 1.0}},
            {"name": "P2P", "tests": ["@P2P"], "threshold": {"pass^k": 1.0}},
        ]
    }))

    from common.layers import LayerEvaluator

    ev = LayerEvaluator(
        task_dir=task_dir,
        f2p_tests=["tests/test_a.py::t1"],
        p2p_tests=["tests/test_b.py::t2"],
    )
    layers = ev.load_layers()
    evaluated = ev.evaluate(
        layers,
        results={"tests/test_a.py::t1": "PASSED", "tests/test_b.py::t2": "PASSED"},
        durations_ms={"tests/test_a.py::t1": 10, "tests/test_b.py::t2": 20},
        errors={},
    )
    out = tmp_path / "trial_01" / "results.json"
    ev.write_results(out, trial=1, task="t", model="m", wall_time_s=1.0,
                     total_cost_usd=0.0, total_tokens_in=0, total_tokens_out=0,
                     completion_signal="task_complete", layers=evaluated)

    data = json.loads(out.read_text())
    assert len(data["layers"]) == 2
    assert data["layers"][0]["layer_passed"] is True
```

- [ ] **Step 3: Run the test**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/test_evaluator_layers.py -v`

Expected: PASS (this test validates the common layer logic wires through — no integration code change needed yet).

- [ ] **Step 4: Add a new method `write_layer_results` to `Evaluator` in evaluator.py**

Add to `integration/src/harness/evaluator.py` (near the existing `evaluate_execution` method):

```python
    def write_layer_results(
        self,
        task_dir: "Path",
        trial_dir: "Path",
        *,
        trial: int,
        task: str,
        model: str,
        wall_time_s: float,
        total_cost_usd: float,
        total_tokens_in: int,
        total_tokens_out: int,
        completion_signal: str,
        f2p_tests: "list[str]",
        p2p_tests: "list[str]",
        test_results: "dict[str, str]",
        test_durations_ms: "dict[str, int]",
        test_errors: "dict[str, str]",
    ) -> None:
        """Produce trial_dir/results.json using LayerEvaluator.

        If task_dir/test_layers.json exists, uses it; otherwise falls back
        to F2P/P2P layers.
        """
        import sys
        from pathlib import Path as _Path
        _REPO = _Path(__file__).resolve().parent.parent.parent.parent
        if str(_REPO) not in sys.path:
            sys.path.insert(0, str(_REPO))
        from common.layers import LayerEvaluator

        evaluator = LayerEvaluator(
            task_dir=task_dir,
            f2p_tests=f2p_tests,
            p2p_tests=p2p_tests,
        )
        layers = evaluator.load_layers()
        evaluated = evaluator.evaluate(
            layers, test_results, test_durations_ms, test_errors,
        )
        evaluator.write_results(
            trial_dir / "results.json",
            trial=trial, task=task, model=model,
            wall_time_s=wall_time_s,
            total_cost_usd=total_cost_usd,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            completion_signal=completion_signal,
            layers=evaluated,
        )
```

- [ ] **Step 5: Find the place where results are currently written and call `write_layer_results` alongside (don't replace yet)**

Grep for where existing results are written:

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "results\.json\|evaluation\.json\|save\|write.*result" integration/src/harness/evaluator.py integration/src/main.py | head -20`

Locate the evaluation-complete point and add a call to `write_layer_results` in addition to the existing output (to preserve backward compatibility for now).

At that point in the code, gather the needed args. The existing evaluator already knows F2P/P2P sets and per-test results — wire them into the new call. Pass `trial_dir = run_dir / f"trial_{trial:02d}"`.

- [ ] **Step 6: Run tests**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/ -v`

Expected: all pass (preexisting + new evaluator_layers test).

- [ ] **Step 7: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add integration/src/harness/evaluator.py integration/tests/test_evaluator_layers.py
git commit -m "integration: add Evaluator.write_layer_results using LayerEvaluator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Integration — rename CLI flags with deprecation shim

**Files:**
- Modify: `integration/src/main.py`

- [ ] **Step 1: Read the current typer flag definitions**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "n_trials\|max_workers\|--n-trials\|--max-workers" integration/src/main.py`

Identify the lines where `--n-trials` and `--max-workers` are declared (lines ~49-51 per earlier grep).

- [ ] **Step 2: Apply the rename with deprecation shim**

Change the option declarations:

**Before:**
```python
n_trials: int = typer.Option(3, "--n-trials", "-n", help="Number of trials per task-model"),
...
max_workers: int = typer.Option(4, "--max-workers", "-w", help="Maximum parallel workers"),
```

**After:**
```python
trials: int = typer.Option(3, "--trials", "-n", "--n-trials",
                            help="Number of trials per task-model (formerly --n-trials)"),
...
workers: int = typer.Option(4, "--workers", "-w", "--max-workers",
                             help="Maximum parallel workers (formerly --max-workers)"),
```

Then inside the function body, add deprecation warnings:

```python
import sys as _sys
# Detect legacy flag usage from argv
if any(a == "--n-trials" or a.startswith("--n-trials=") for a in _sys.argv):
    print("[DEPRECATED] --n-trials will be removed in a future release; "
          "use --trials instead.", file=_sys.stderr)
if any(a == "--max-workers" or a.startswith("--max-workers=") for a in _sys.argv):
    print("[DEPRECATED] --max-workers will be removed in a future release; "
          "use --workers instead.", file=_sys.stderr)
```

Within the function body, replace every usage of `n_trials` with `trials` and `max_workers` with `workers`.

- [ ] **Step 3: Verify by running with both old and new flags**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/python -m src.main --help 2>&1 | head -40`

Expected: help text shows both `--trials` and `--n-trials` as equivalent (typer lists them together).

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/python -m src.main --trials 1 --workers 1 --help 2>&1 | head -5`

Expected: no argparse/typer error.

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/python -m src.main --n-trials 1 --max-workers 1 --help 2>&1 | head -5`

Expected: no error, and `[DEPRECATED]` messages printed to stderr.

- [ ] **Step 4: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add integration/src/main.py
git commit -m "integration: rename --n-trials→--trials, --max-workers→--workers

Backward-compatible: old flag names still accepted with stderr deprecation
warning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Integration — wire post-dispatch aggregation call

**Files:**
- Modify: `integration/src/main.py`

- [ ] **Step 1: Read where the current batch run writes final outputs**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "ThreadPoolExecutor\|concurrent\|final\|save\|output_dir\|results\.json" integration/src/main.py | head -20`

Identify the point where all trials have returned (typically after `as_completed()` or after the main trial loop).

- [ ] **Step 2: Add aggregation call at end of dispatch**

Identify the local variable that holds the per-run output directory — call it `<RUN_DIR_VAR>`. From the grep in Step 1, this is the variable passed to `output_dir=`, `results_dir=`, or equivalent when writing trial outputs. In `integration/src/main.py`, the relevant variable is likely `run_dir`, `output_path`, or similar — identified by the pattern `trial_{i}` path construction or the `--output` argument usage.

Just before returning from the main CLI function (after the trial-dispatch loop finishes), add (substituting `<RUN_DIR_VAR>` with the identified variable):

```python
# Post-dispatch aggregation — produce eval_summary.{md,json}
import sys as _sys
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in _sys.path:
    _sys.path.insert(0, str(_REPO))
from common.trials import aggregate_trials, write_eval_summary

try:
    agg = aggregate_trials(<RUN_DIR_VAR>)
    write_eval_summary(<RUN_DIR_VAR>, agg)
    print(f"[eval] Wrote {<RUN_DIR_VAR>/'eval_summary.md'}", file=_sys.stderr)
except ValueError as exc:
    print(f"[eval] Could not aggregate: {exc}", file=_sys.stderr)
```

- [ ] **Step 3: Smoke test with an existing fake task**

If the integration suite has a dry-run mode, invoke it with `--trials 1 --workers 1` and verify `trial_01/`, `eval_summary.md`, `eval_summary.json` all appear in the run dir.

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration && venv/bin/pytest tests/ -v`

Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add integration/src/main.py
git commit -m "integration: call aggregate_trials + write_eval_summary post-dispatch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Observability — rename `--parallel` → `--workers` with deprecation shim

**Files:**
- Modify: `observability/run_e2e.py:620`

- [ ] **Step 1: Update argparse declaration**

Locate line 620 (`--parallel` declaration).

**Before:**
```python
parser.add_argument("--parallel", "-p", type=int, default=1, help="Number of parallel workers (default: 1)")
```

**After:**
```python
parser.add_argument("--workers", "--parallel", "-p", type=int, default=1,
                    dest="workers",
                    help="Number of parallel workers (default: 1). Formerly --parallel.")
```

- [ ] **Step 2: Rename all references to `args.parallel` to `args.workers`**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "args\.parallel\|\.parallel" observability/run_e2e.py`

Replace all occurrences with `args.workers`.

- [ ] **Step 3: Add deprecation warning if `--parallel` is in argv**

After `args = parser.parse_args()`:

```python
if any(a == "--parallel" or a.startswith("--parallel=") for a in sys.argv):
    print("[DEPRECATED] --parallel will be removed in a future release; "
          "use --workers instead.", file=sys.stderr)
```

- [ ] **Step 4: Verify with --help**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/python run_e2e.py --help 2>&1 | grep -E "workers|parallel"`

Expected: shows `--workers` (with `--parallel` as alias in help line).

- [ ] **Step 5: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add observability/run_e2e.py
git commit -m "observability: rename --parallel→--workers with deprecation shim

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Observability — normalize inspect-ai transcript into `trajectory.jsonl`

**Files:**
- Modify: `observability/eval_runner/runner.py`
- Create: `observability/tests/test_trajectory_normalization.py`

- [ ] **Step 1: Read how inspect-ai transcripts are accessed**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "ModelEvent\|ToolEvent\|ScoreEvent\|eval_log\|read_eval_log\|transcript" observability/eval_runner/runner.py | head -30`

- [ ] **Step 2: Write the failing test**

Create `observability/tests/__init__.py` (empty) and `observability/tests/test_trajectory_normalization.py`:

```python
"""Test inspect-ai transcript → trajectory.jsonl normalization."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/pytest tests/test_trajectory_normalization.py -v`

Expected: FAIL with `ImportError: cannot import name 'normalize_inspect_events_to_trajectory'`.

- [ ] **Step 4: Implement normalize helper in runner.py**

At the top of `observability/eval_runner/runner.py`, ensure common/ is importable:

```python
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.trajectory import TrajectoryWriter  # noqa: E402
```

Add the normalization function at module level (not inside a class):

```python
def normalize_inspect_events_to_trajectory(events, out_path):
    """Convert a sequence of inspect-ai event dicts into a trajectory.jsonl.

    Event dicts are expected to have at least an 'event' type discriminator.
    Unknown event types are skipped. A final 'score' event is mapped to a
    completion marker.
    """
    writer = TrajectoryWriter(out_path)
    try:
        step = 0
        for evt in events:
            kind = evt.get("event")
            ts = evt.get("timestamp", "")
            if kind == "model":
                step += 1
                writer.write(
                    step=step, ts=ts, type="reasoning",
                    content=evt.get("output_text", ""),
                    tokens_in=evt.get("input_tokens", 0),
                    tokens_out=evt.get("output_tokens", 0),
                    latency_ms=evt.get("total_time_ms", 0),
                    cost_usd=evt.get("cost_usd", 0.0),
                )
            elif kind == "tool":
                writer.write(
                    step=step, ts=ts, type="tool_call",
                    tool=evt["tool"], args=evt.get("args", {}),
                    call_id=evt["call_id"],
                )
                writer.write(
                    step=step, ts=ts, type="tool_result",
                    call_id=evt["call_id"],
                    status=evt.get("status", "success"),
                    exit_code=evt.get("exit_code", 0),
                    stdout_bytes=len(evt.get("output", "").encode("utf-8")),
                    content=evt.get("output", ""),
                )
            elif kind == "score":
                signal = "task_complete" if evt.get("value") == "pass" else "error"
                writer.write(
                    step=step + 1, ts=ts, type="completion",
                    signal=signal,
                    total_tokens_in=evt.get("total_input_tokens", 0),
                    total_tokens_out=evt.get("total_output_tokens", 0),
                    total_cost_usd=evt.get("total_cost_usd", 0.0),
                    wall_time_s=evt.get("wall_time_s", 0.0),
                )
    finally:
        writer.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/pytest tests/test_trajectory_normalization.py -v`

Expected: test PASSES.

- [ ] **Step 6: Wire the normalizer into the real eval flow**

Find where inspect-ai eval logs are read post-run in `runner.py`. For each completed eval log, call `normalize_inspect_events_to_trajectory(log_events, trial_dir / "trajectory.jsonl")`.

The actual inspect-ai transcript access may look like `inspect_ai.log.read_eval_log(path).samples[0].events`. The shape of `events` may differ from our fake — adapt the normalizer's key lookups to match the real shape. Re-run the unit test with realistic fake data to validate before shipping.

- [ ] **Step 7: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add observability/eval_runner/runner.py observability/tests/
git commit -m "observability: normalize inspect-ai transcript to trajectory.jsonl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Observability — swap F2P/P2P check for `LayerEvaluator` in `inspect_scorer.py`

**Files:**
- Modify: `observability/eval_runner/inspect_scorer.py`
- Create: `observability/tests/test_scorer_layers.py`

- [ ] **Step 1: Read current scorer**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "def score\|@scorer\|f2p\|p2p\|pass_to_pass\|fail_to_pass" observability/eval_runner/inspect_scorer.py | head -20`

- [ ] **Step 2: Write failing test**

Create `observability/tests/test_scorer_layers.py`:

```python
"""Test scorer produces results.json with layer breakdown."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/pytest tests/test_scorer_layers.py -v`

Expected: FAIL with ImportError.

- [ ] **Step 4: Implement `write_layer_results_for_trial` in `inspect_scorer.py`**

Add to the top of `observability/eval_runner/inspect_scorer.py`:

```python
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.layers import LayerEvaluator  # noqa: E402
```

Add a module-level function:

```python
def write_layer_results_for_trial(
    *,
    task_dir,
    trial_dir,
    trial,
    task,
    model,
    wall_time_s,
    total_cost_usd,
    total_tokens_in,
    total_tokens_out,
    completion_signal,
    f2p_tests,
    p2p_tests,
    test_results,
    test_durations_ms,
    test_errors,
):
    evaluator = LayerEvaluator(
        task_dir=task_dir,
        f2p_tests=f2p_tests,
        p2p_tests=p2p_tests,
    )
    layers = evaluator.load_layers()
    evaluated = evaluator.evaluate(
        layers, test_results, test_durations_ms, test_errors,
    )
    evaluator.write_results(
        trial_dir / "results.json",
        trial=trial, task=task, model=model,
        wall_time_s=wall_time_s,
        total_cost_usd=total_cost_usd,
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        completion_signal=completion_signal,
        layers=evaluated,
    )
```

- [ ] **Step 5: Wire it into the existing scorer body**

Find the place in the existing scorer where F2P/P2P results are summarized (grep for `PASSED\|FAILED\|score`). At that point, gather:

- `task_dir` from the eval log's task metadata
- `trial_dir` = the output dir for this sample (inspect-ai exposes per-sample output paths)
- Per-test results from the inspect-ai log's subtests
- F2P/P2P test lists from the task's `f2p_cache/` or similar

Call `write_layer_results_for_trial(...)`. Leave the existing summary output in place for now (additive).

- [ ] **Step 6: Run tests**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/pytest tests/ -v`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add observability/eval_runner/inspect_scorer.py observability/tests/test_scorer_layers.py
git commit -m "observability: add write_layer_results_for_trial in inspect_scorer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Observability — post-dispatch aggregation call

**Files:**
- Modify: `observability/run_e2e.py`

- [ ] **Step 1: Find the end of the batch dispatch**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && grep -n "as_completed\|ThreadPool\|asyncio\.gather\|return\|main" observability/run_e2e.py | tail -30`

Find the point where all workers have returned.

- [ ] **Step 2: Add aggregation call**

Identify the variable holding the per-run output directory — call it `<RUN_DIR_VAR>`. In `observability/run_e2e.py`, this is typically derived from `args.output` (e.g., `Path(args.output)` or similar). Look for the location where per-trial paths are constructed with `trial_{i}` or equivalent.

Just before the CLI function returns (after all workers complete), add (substituting `<RUN_DIR_VAR>`):

```python
# Post-dispatch aggregation
import sys as _sys
from pathlib import Path as _Path
_REPO = _Path(__file__).resolve().parent.parent
if str(_REPO) not in _sys.path:
    _sys.path.insert(0, str(_REPO))
from common.trials import aggregate_trials, write_eval_summary

try:
    agg = aggregate_trials(<RUN_DIR_VAR>)
    write_eval_summary(<RUN_DIR_VAR>, agg)
    print(f"[eval] Wrote {<RUN_DIR_VAR>/'eval_summary.md'}", file=_sys.stderr)
except ValueError as exc:
    print(f"[eval] Could not aggregate: {exc}", file=_sys.stderr)
```

- [ ] **Step 3: Smoke test**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability && venv/bin/pytest tests/ -v`

Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add observability/run_e2e.py
git commit -m "observability: call aggregate_trials + write_eval_summary post-dispatch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Document task-authoring conventions

**Files:**
- Create or extend: `integration/tasks/README.md` AND `observability/tasks/README.md` (one per sub-harness since they have separate tasks dirs)

- [ ] **Step 1: Check which README files exist**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && ls integration/tasks/README.md observability/tasks/README.md 2>&1`

- [ ] **Step 2: Create or append to each file with these sections**

For each existing README, append (or create fresh with) this content:

````markdown

## Kosmos Evaluation Conventions

### `test_layers.json` (optional)

Place at `<task_id>/test_layers.json` to group tests into evaluation layers with per-layer thresholds. If absent, the harness falls back to flat F2P/P2P layers.

Schema:

```json
{
  "version": 1,
  "layers": [
    {
      "name": "<layer_name>",
      "description": "<free-text description>",
      "tests": [
        "tests/verifiers/script_name.sh",
        "tests/test_file.py::test_name",
        "@F2P",
        "@P2P"
      ],
      "threshold": { "pass^k": 1.0 }
    }
  ]
}
```

**Threshold types:**
- `"pass^k": 1.0` — all k trials must pass this layer (strict)
- `"pass@k": 0.80` — pass rate across k trials must be ≥ 0.80 (tolerant)

**Special tokens:**
- `@F2P` expands to the task's Fail-to-Pass test list
- `@P2P` expands to the task's Pass-to-Pass test list

### State-level verifiers

Verifier scripts live under `<task_id>/tests/verifiers/*.sh`. Three types:

1. **Repo-state** — run `pytest` or similar against the agent's code changes.
2. **Trajectory** — assert on `trajectory.jsonl` to verify the agent took certain actions. Example:
   ```bash
   #!/bin/bash
   jq -e 'select(.type=="tool_call" and .tool=="bash" and (.args.cmd | contains("mattermost")))' trajectory.jsonl > /dev/null && echo "PASSED" || echo "FAILED"
   ```
3. **Service-state** — assert on MCP service state. Example:
   ```bash
   #!/bin/bash
   curl -s mattermost:8065/api/v4/posts | jq -e '.[] | select(.message | contains("migration complete"))' > /dev/null && echo "PASSED" || echo "FAILED"
   ```

**Rules for verifier scripts:**
- Emit `PASSED` or `FAILED` as the last non-empty stdout line.
- Exit 0 on pass, non-zero on fail (both signals checked; `PASSED`/`FAILED` line is authoritative).
- Read `trajectory.jsonl` from the current working directory (evaluator `cd`s to trial dir before invoking).

### Distractor data seeding

Bake distractor data directly into existing task seed scripts (`seed.sh` or similar). Categories:

- **Outdated files** — stale spec docs (dated 6+ months ago), old README revisions with superseded instructions
- **Resolved issues** — closed Plane/Zammad tickets describing related-but-different fixed bugs
- **Off-topic conversations** — Mattermost channel messages about adjacent work (unrelated features, holiday party)
- **Archived dashboards** — Grafana dashboards with similar names referencing dead metrics
- **Inactive users** — EspoCRM/Plane users with matching titles to active ones

**Quality rules:**
- **Plausible** — obviously-wrong distractors filter immediately and add no signal
- **Dated or flagged** — agent should be able to identify staleness via timestamps or archive markers
- **Non-blocking** — passing the task should never require using distractor data

### `hints.json` (reserved, not yet implemented)

The filename `<task_id>/hints.json` is reserved for future hint injection. Do not repurpose this filename.
````

- [ ] **Step 3: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add integration/tasks/README.md observability/tasks/README.md
git commit -m "docs(tasks): document test_layers.json, verifiers, distractors, hints reservation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: Add an example `test_layers.json` to one existing task

**Files:**
- Create: `<path_to_one_existing_task>/test_layers.json`

- [ ] **Step 1: Pick a small existing task with F2P/P2P already defined**

Run: `cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness && ls observability/tasks/ | head -5 && ls integration/tasks/ | head -5`

Pick the smallest/simplest task with existing `f2p_cache/*.json` entries. Call it `<task_id>`.

- [ ] **Step 2: Create `test_layers.json` using `@F2P`/`@P2P` tokens**

Create a `test_layers.json` at the chosen task's directory:

```json
{
  "version": 1,
  "layers": [
    {
      "name": "F2P",
      "description": "Fail-to-Pass tests from golden patch",
      "tests": ["@F2P"],
      "threshold": { "pass^k": 1.0 }
    },
    {
      "name": "P2P",
      "description": "Pass-to-Pass tests — no regressions allowed",
      "tests": ["@P2P"],
      "threshold": { "pass^k": 1.0 }
    }
  ]
}
```

This replicates the fallback behavior explicitly, providing a template task authors can extend with Gate/Context/Trajectory layers.

- [ ] **Step 3: Commit**

Substitute `<TASK_DIR>` with the task directory path chosen in Step 1 (e.g., `observability/tasks/git-bug-git-bug-132-449-observability/test_layers.json`):

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add <TASK_DIR>/test_layers.json
git commit -m "tasks: add example test_layers.json replicating fallback behavior

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 20: Update top-level READMEs with migration notes

**Files:**
- Modify: `README.md` (top level)
- Modify: `integration/README.md`
- Modify: `observability/README.md`

- [ ] **Step 1: Append migration section to each README**

Append to each of the three README files:

````markdown

## Kosmos Evaluation Additions — Migration Notes

This revision adds per-run JSONL trajectories, task-defined test layer groupings, pass@k/pass^k aggregation, and distractor seeding conventions. Backward-compatible with one intentional path change.

### Flag renames (deprecation shim in place for one release)

| Old (deprecated) | New | Sub-harness |
|---|---|---|
| `--n-trials` | `--trials` | integration |
| `--max-workers` | `--workers` | integration |
| `--parallel` | `--workers` | observability |

Old flags emit `[DEPRECATED]` to stderr but still work.

### Path layout change

Per-trial outputs are always under `runs/<id>/trial_NN/`, even for single-trial runs. Consumers reading `runs/<id>/results.json` directly must update to `runs/<id>/trial_01/results.json`.

### Optional task-level files

- `<task_dir>/test_layers.json` — group tests into evaluation layers. If absent, falls back to flat F2P/P2P. See `tasks/README.md` for schema.
- `<task_dir>/hints.json` — RESERVED for future hint injection. Do not repurpose.

### New outputs

Every run produces:

- `runs/<id>/trial_NN/trajectory.jsonl` — one-event-per-line JSONL of reasoning/tool_call/tool_result/completion
- `runs/<id>/trial_NN/results.json` — per-layer, per-test result breakdown
- `runs/<id>/eval_summary.md` — human-readable aggregate across all trials
- `runs/<id>/eval_summary.json` — machine-readable aggregate

Existing native per-turn artifacts are preserved:
- Integration: `agent-logs/episode-N/{prompt.txt,response.json,debug.json}`
- Observability: `*.eval` inspect-ai transcripts
````

- [ ] **Step 2: Commit**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness
git add README.md integration/README.md observability/README.md
git commit -m "docs: add Kosmos migration notes (flag renames, path change, new outputs)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 21: Final smoke test — run both harnesses end-to-end with a mocked model

**Files:** (smoke test only — no new code)

- [ ] **Step 1: Integration smoke test**

Pick the simplest integration task (e.g., a small existing demo task). Run:

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/integration
venv/bin/python -m src.main \
  --task <smallest_task_id> \
  --model <fake_or_cheapest_model> \
  --trials 2 \
  --workers 1 \
  --output /tmp/kosmos_smoke_integration
```

Expected artifacts under `/tmp/kosmos_smoke_integration/`:
- `trial_01/trajectory.jsonl` non-empty, events of all 4 types present
- `trial_01/results.json` with `layers` array
- `trial_02/trajectory.jsonl` non-empty
- `eval_summary.md` with per-layer table and pass@k/pass^k columns
- `eval_summary.json` with same data in JSON form

Verify with:

```bash
jq 'map(.type) | unique' /tmp/kosmos_smoke_integration/trial_01/trajectory.jsonl
cat /tmp/kosmos_smoke_integration/eval_summary.md
```

- [ ] **Step 2: Observability smoke test**

```bash
cd /Users/jokerrick/GDM_RealWorld/src/apex-swe-harness/observability
venv/bin/python run_e2e.py \
  --task <smallest_task_id> \
  --model <fake_or_cheapest_model> \
  --trials 2 \
  --workers 1 \
  --output /tmp/kosmos_smoke_observability
```

Same expectations as integration.

- [ ] **Step 3: Record smoke test results in the PR / branch description**

Note any rough edges discovered (event fields missing from inspect-ai transcript, LiteLLM metadata unavailable for a model, etc.) for follow-up. If anything fails, fix it via a new task before merging.

- [ ] **Step 4: Final commit (only if changes were needed)**

Only commit if fixes were required during the smoke test. If smoke tests pass clean, no commit needed for this task.

---

## Completion checklist

Before declaring done, verify:

- [ ] All new unit tests pass: `cd integration && venv/bin/pytest ../common/tests/ -v` (should be ~40+ tests green)
- [ ] Integration unit tests pass: `cd integration && venv/bin/pytest tests/ -v`
- [ ] Observability unit tests pass: `cd observability && venv/bin/pytest tests/ -v`
- [ ] Both smoke tests produce `trajectory.jsonl`, `results.json`, `eval_summary.md`, `eval_summary.json` with sensible contents
- [ ] Running a task without `test_layers.json` still works (fallback layers produced)
- [ ] Running with legacy flag names (`--n-trials`, `--max-workers`, `--parallel`) still works and emits deprecation warnings
- [ ] `integration/tasks/README.md` and `observability/tasks/README.md` document layer/verifier/distractor/hints conventions
- [ ] All three top-level READMEs have migration notes
- [ ] No uncommitted changes outside the plan's scope

## Out of scope for this plan

Per the approved spec, these are explicitly deferred:

- Hint injection (only the `hints.json` reserved filename is documented)
- Model-grader / LLM-as-judge scoring
- Tool output envelope standardization
- Cross-model / cross-task sweep config
- Trajectory visualizer
- Cost budget kill-switch
