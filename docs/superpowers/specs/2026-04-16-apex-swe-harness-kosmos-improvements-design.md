# apex-swe-harness — Kosmos Evaluation Improvements

**Status:** Design approved, pending implementation plan
**Date:** 2026-04-16
**Branch:** `kosmos-harness-improvements`
**Owner:** Jo Kerrick

## Context

Project Kosmos is a Mercor × GDM benchmark for frontier AI models on real-world SWE tasks with programmatically verifiable evaluation. The existing `apex-swe-harness` — two sub-harnesses (`integration/` with a custom XML ReAct loop and `observability/` with `inspect-ai`'s `react()`) — already supports Docker Compose + live MCP services (Zammad, Mattermost, Plane, EspoCRM, Medusa, Grafana, Prometheus, S3), F2P/P2P scoring, 20+ test-framework parsers, multi-model execution, and parallel runs.

This design extends the harness with evaluation instrumentation required by Kosmos while preserving all existing behavior.

## Goals

Add four capabilities (a fifth is deferred):

1. **Per-run JSONL trajectory file** — one event per line, shared envelope across both sub-harnesses, capturing reasoning, tool calls, results, completion, plus cost/latency/token metadata.
2. **Task-defined test layer groupings** — optional `test_layers.json` per task that groups existing test IDs into named layers (e.g., Gate, Context, Functional, Regression) with per-layer pass@k / pass^k thresholds. Harness has zero hardcoded knowledge of layer names.
3. **State-level verifiers** — layers can include bash-script verifiers that assert on trajectory content (a specific tool was called, an API was hit) and MCP service state (an email was sent, a ticket was closed, a record was updated), in addition to existing repo-state test scripts. All three verifier types share the same test-ID surface so they slot into layers uniformly.
4. **pass@k / pass^k aggregation** — trials per `(model, task)` are aggregated into a human-readable `eval_summary.md` and machine-readable `eval_summary.json`, with per-test failure visibility and per-layer total pass counts.
5. **Distractor / noise data seeding** — plausible-but-stale records (outdated files, resolved tickets, off-topic conversations) baked into existing task seed scripts.
6. **Hint injection** — DEFERRED. Reserve `tasks/<task_id>/hints.json` filename; document placeholder only.

## Non-goals

- Model-grader / LLM-as-judge scoring (deferred — current Kosmos tasks are programmatically verifiable)
- Tool-output envelope standardization (`{status, summary, next_actions, artifacts}`) — would bias eval signal
- Replacing existing parallel-dispatch mechanisms (preserve them, wrap aggregation on top)
- Cross-model / cross-task sweep config file (per-invocation sufficient for now)
- Trajectory visualizer (JSONL is consumable via `jq`/pandas today)
- Cost budget kill-switch (record cost but do not cap)

## Design

### Repository layout

```
apex-swe-harness/
├── common/                          # NEW — shared by both sub-harnesses
│   ├── __init__.py
│   ├── trajectory.py                # TrajectoryWriter: shared JSONL envelope
│   ├── layers.py                    # LayerEvaluator: load test_layers.json, run tests, emit per-layer results.json
│   └── trials.py                    # Post-dispatch aggregator: pass@k / pass^k, eval_summary.{md,json}
├── integration/
│   └── src/harness/
│       ├── multi_step_runner.py     # +TrajectoryWriter
│       └── evaluator.py             # +LayerEvaluator
├── observability/
│   └── eval_runner/
│       ├── runner.py                # +TrajectoryWriter (normalize inspect-ai transcript)
│       └── inspect_scorer.py        # +LayerEvaluator
└── tasks/<task_id>/
    ├── test_layers.json             # NEW optional
    ├── tests/verifiers/*.sh         # NEW bash verifiers (trajectory + service-state)
    └── seed.sh                      # EXTENDED with distractors in-place
```

Each sub-harness has its own venv. `common/` is added to `sys.path` from each runner — no packaging overhead.

### Run output layout

Existing per-turn artifacts are preserved exactly as today. Each harness has its own native turn log format; the new `trajectory.jsonl` is a normalized view written alongside, not a replacement:

```
runs/
└── 20260416_143022_claude-opus-4-7_crm_debug/              # experiment_id = timestamp_model_task
    ├── trial_01/
    │   ├── trajectory.jsonl                                # NEW — normalized per-turn events
    │   ├── results.json                                    # NEW — per-layer, per-test results
    │   │
    │   ├── agent-logs/                                     # EXISTING — integration harness only
    │   │   ├── episode-1/
    │   │   │   ├── prompt.txt                              # full prompt sent to LLM this turn
    │   │   │   ├── response.json                           # parsed LLM response (XML, tool calls)
    │   │   │   └── debug.json                              # debug metadata
    │   │   ├── episode-2/…
    │   │   └── episode-N/
    │   │
    │   └── *.eval                                          # EXISTING — observability harness only (inspect-ai transcript)
    │
    ├── trial_02/…
    ├── trial_N/
    ├── eval_summary.md                                     # NEW — aggregate human-readable
    └── eval_summary.json                                   # NEW — aggregate machine-readable
```

**Episodes / turns are still visible** through two paths:

- `trajectory.jsonl` — normalized event stream (new, cross-harness)
- Native per-turn artifacts — `agent-logs/episode-N/` for integration, `*.eval` for observability (unchanged, existing)

When `--trials 1` (single trial), `trial_01/` is still written; the aggregate `eval_summary.*` files are still produced for consistency.

### Trajectory JSONL schema

One event per line. Shared envelope across both sub-harnesses: `step`, `ts`, `type`. Each `type` extends with its own fields:

```jsonl
{"step": 1, "ts": "2026-04-16T14:22:08.123Z", "type": "reasoning", "content": "I need to check Mattermost for context before filtering...", "tokens_in": 4821, "tokens_out": 312, "latency_ms": 1840, "cost_usd": 0.0142}
{"step": 1, "ts": "2026-04-16T14:22:11.008Z", "type": "tool_call", "tool": "bash", "args": {"cmd": "curl -s mattermost:8065/api/v4/posts"}, "call_id": "c_01"}
{"step": 1, "ts": "2026-04-16T14:22:11.489Z", "type": "tool_result", "call_id": "c_01", "status": "success", "exit_code": 0, "stdout_bytes": 18422, "content": "...truncated..."}
{"step": 2, "ts": "2026-04-16T14:22:13.112Z", "type": "reasoning", "content": "...", "tokens_in": 8104, "tokens_out": 478, "latency_ms": 2210, "cost_usd": 0.0267}
{"step": 12, "ts": "2026-04-16T14:28:44.771Z", "type": "completion", "signal": "task_complete", "total_tokens_in": 51203, "total_tokens_out": 4812, "total_cost_usd": 0.3821, "wall_time_s": 396}
```

**Event types:**

| Type | Required fields | Meaning |
|---|---|---|
| `reasoning` | `content`, `tokens_in`, `tokens_out`, `latency_ms`, `cost_usd` | Model deliberation / plan output |
| `tool_call` | `tool`, `args`, `call_id` | Tool invocation request |
| `tool_result` | `call_id`, `status`, `exit_code`, `stdout_bytes`, `content` | Tool response (content truncated to 16 KB default) |
| `completion` | `signal`, `total_tokens_in`, `total_tokens_out`, `total_cost_usd`, `wall_time_s` | Run terminated; `signal` ∈ {task_complete, timeout, max_steps, error} |

**Harness-specific fields** may be added as extensions beneath a reserved `ext` key, e.g., `"ext": {"inspect_event_id": "..."}`. Consumers that don't care about them ignore the key.

**Sources:**
- **Integration harness**: `multi_step_runner.py` emits events at existing XML-parse points. Token/cost/latency metadata comes from LiteLLM response objects (already available, just not persisted).
- **Observability harness**: `runner.py` iterates inspect-ai's transcript after the run completes and emits matching events. Mapping: `ModelEvent` → `reasoning`, `ToolEvent` → `tool_call` + `tool_result`, `ScoreEvent` → `completion`.

### `test_layers.json` schema

One per task. Lives at `tasks/<task_id>/test_layers.json`. Optional — tasks without it fall back to a synthetic two-layer structure.

```json
{
  "version": 1,
  "layers": [
    {
      "name": "Gate",
      "description": "Basic setup invariants — must always pass",
      "tests": [
        "tests/verifiers/script_exists.sh",
        "tests/verifiers/script_runs.sh"
      ],
      "threshold": { "pass^k": 1.0 }
    },
    {
      "name": "Context",
      "description": "Agent queried the right MCP services",
      "tests": [
        "tests/verifiers/queried_mattermost.sh",
        "tests/verifiers/read_plane_issue.sh",
        "tests/verifiers/read_zammad_ticket.sh"
      ],
      "threshold": { "pass@k": 0.80 }
    },
    {
      "name": "Functional",
      "description": "Core F2P tests from golden patch",
      "tests": [
        "tests/test_filters.py::test_active",
        "tests/test_filters.py::test_dedup"
      ],
      "threshold": { "pass@k": 0.80 }
    },
    {
      "name": "Regression",
      "description": "P2P tests — zero regressions allowed",
      "tests": ["@P2P"],
      "threshold": { "pass^k": 1.0 }
    }
  ]
}
```

**Test ID conventions:**

| Pattern | Interpretation |
|---|---|
| `tests/.../*.sh` | Bash script; executed directly; `PASSED` / `FAILED` grepped from stdout |
| `tests/…::nodename` | Pytest-style node ID; run via existing evaluator test-framework parsers |
| `@F2P`, `@P2P` | Expands to the task's existing F2P / P2P lists |

**Threshold semantics:**

| Threshold | Meaning | Typical use |
|---|---|---|
| `pass@k: X` | Pass rate across k trials must be ≥ X | Capability tests (`0.80` typical) |
| `pass^k: 1.0` | All k trials must pass this layer | Regression / gate layers |

Harness computes both values on every layer for reporting, but only the declared threshold determines verdict.

**Fallback when file absent:**

```json
{
  "version": 1,
  "layers": [
    { "name": "F2P", "tests": ["@F2P"], "threshold": { "pass^k": 1.0 } },
    { "name": "P2P", "tests": ["@P2P"], "threshold": { "pass^k": 1.0 } }
  ]
}
```

This preserves existing task behavior unchanged.

### Per-trial `results.json` schema

Written by `LayerEvaluator` after tests complete. Captures per-test detail so failures are diagnosable:

```json
{
  "trial": 1,
  "task": "crm_debug",
  "model": "claude-opus-4-7",
  "wall_time_s": 396,
  "total_cost_usd": 0.3821,
  "total_tokens_in": 51203,
  "total_tokens_out": 4812,
  "completion_signal": "task_complete",
  "layers": [
    {
      "name": "Functional",
      "layer_passed": false,
      "pass_count": 1,
      "total_count": 2,
      "tests": [
        {"id": "tests/test_filters.py::test_active", "status": "PASSED", "duration_ms": 210},
        {"id": "tests/test_filters.py::test_dedup",  "status": "FAILED", "duration_ms": 185, "error": "AssertionError: expected 42, got 45"}
      ]
    }
  ]
}
```

### Trial aggregation and `eval_summary.md`

`common/trials.py` runs as a post-dispatch step: after all trials finish (sequentially or in parallel per existing harness mechanisms), it reads each `trial_NN/results.json` and produces aggregate artifacts.

**Per-layer aggregation (across N trials):**

- `pass@k` = 1 if at least one trial passed the layer, else 0
- `pass^k` = 1 if all trials passed the layer, else 0
- `pass_rate` = (trials where layer passed) / N
- `tests_passed_total` = sum of `pass_count` across all N trials
- `tests_total` = sum of `total_count` across all N trials (= N × tests-in-layer, assuming stable layer definitions)
- Verdict: compare against the layer's declared threshold

**Holistic aggregation:**

- `pass@k_holistic` = 1 if any trial passed every layer
- `pass^k_holistic` = 1 if every trial passed every layer
- Total cost, total wall-time, retries-per-trial (derived from trajectory: count of `tool_result.status != "success"` events)

**`eval_summary.md` format:**

```markdown
# Eval Summary — crm_debug

**Model:** claude-opus-4-7
**Trials:** 3
**Date:** 2026-04-16 14:30:22

## Overall
- pass@3: PASS (1/1 at-least-one-success)
- pass^3: FAIL (2/3 all-trials-success)

## Per-Layer Results

| Layer       | Threshold   | Tests Passed (all trials) | Trial 1 | Trial 2 | Trial 3 | pass@k | pass^k | Verdict |
|-------------|-------------|---------------------------|---------|---------|---------|--------|--------|---------|
| Gate        | pass^k=1.0  | 6/6                       | 2/2     | 2/2     | 2/2     | 1.00   | 1.00   | PASS    |
| Context     | pass@k≥0.80 | 8/9                       | 2/3     | 3/3     | 3/3     | 1.00   | 0.67   | PASS    |
| Functional  | pass@k≥0.80 | 7/9                       | 3/3     | 3/3     | 1/3     | 1.00   | 0.67   | FAIL    |
| Regression  | pass^k=1.0  | 44/45                     | 15/15   | 15/15   | 14/15   | 1.00   | 0.67   | FAIL    |

The "Tests Passed (all trials)" column shows total test-case passes summed across every trial for that layer, so you can quickly see e.g. "23/30 Context tests passed across 3 trials" — useful for spotting layers where failures are scattered vs. concentrated.

## Cost & Latency
- Total cost: $1.23
- Avg cost per trial: $0.41
- Avg wall time per trial: 6m 36s
- Total tool retries: 4 (1.33 per trial)

## Failed Tests

### Trial 3
- `tests/test_filters.py::test_dedup` (Functional) — AssertionError: expected 42, got 45
- `tests/verifiers/queried_mattermost.sh` (Context) — exit 1

## Trial Details
- [Trial 1](trial_01/trajectory.jsonl) — full pass
- [Trial 2](trial_02/trajectory.jsonl) — full pass
- [Trial 3](trial_03/trajectory.jsonl) — failed at Functional + Regression
```

`eval_summary.json` contains the same data in machine-readable form for downstream tooling.

### Verifier types

Four verifier categories share the same bash-script surface (no new infrastructure — the existing test runner already executes shell scripts):

| Type | What it checks | Example |
|---|---|---|
| **Repo-state** (existing) | Files written, tests pass | `pytest` run in task repo |
| **Trajectory** (new) | Agent called expected tools | `jq -e 'select(.type=="tool_call" and ...)' trajectory.jsonl` |
| **Service-state** (new) | MCP service state changed correctly | `curl mattermost/api/... \| jq -e ...` |

**Task-author discipline for verifier scripts:**
- Emit `PASSED` / `FAILED` as the last non-empty stdout line
- Exit 0 on pass, non-zero on fail (both signals checked; `PASSED` line is authoritative)
- Read `trajectory.jsonl` from the current working directory (evaluator `cd`s to the trial directory before invoking)

### Distractor seeding

Baked into existing task `seed.sh` scripts. Categories:

| Type | Service | Example |
|---|---|---|
| Outdated files | S3, local filesystem | Stale spec doc dated 6 months ago, contradicting current state |
| Resolved issues | Plane, Zammad | Closed tickets for related-but-different already-fixed bugs |
| Off-topic conversations | Mattermost | Channel messages about adjacent work (holiday party, unrelated feature) |
| Archived dashboards | Grafana | Old dashboard with similar name, referencing dead metrics |
| Inactive users | EspoCRM, Plane | Users with matching names/titles to active ones |

**Task-author quality rules:**
- Must be *plausible* — obviously-wrong distractors filter immediately and add no signal
- Must be *dated* or *flagged* — agent can theoretically identify staleness via timestamps or archive flags
- Must not *block* task completion — passing the task never requires using distractor data

No harness-level code changes. Documented in `tasks/README.md`.

### CLI surface (unified across both sub-harnesses)

| Flag | Meaning | Current integration | Current observability |
|---|---|---|---|
| `--trials N` | Trials per (model, task) | rename from `--n-trials` | matches |
| `--workers W` | Parallel worker count | rename from `--max-workers` | rename from `--parallel` |
| `--task <id>` | Single task | unchanged | unchanged |
| `--model <name>` | Model identifier | unchanged | unchanged |
| `--output <dir>` | Output directory root | audit during implementation | audit during implementation |

Rename includes a deprecation shim accepting old flag names for one release, with a stderr warning. Implementation must audit `--output` (and any other existing flags not listed above) in both harnesses and unify any mismatches before shipping.

### Integration points

| File | Change | Approx. lines |
|---|---|---|
| `common/trajectory.py` | NEW — TrajectoryWriter class, shared envelope validation | ~80 |
| `common/layers.py` | NEW — LayerEvaluator: load test_layers.json, expand `@F2P`/`@P2P`, dispatch tests, emit results.json | ~120 |
| `common/trials.py` | NEW — Read trial_NN/results.json, compute pass@k/pass^k, write eval_summary.{md,json} | ~120 |
| `integration/src/harness/multi_step_runner.py` | Add TrajectoryWriter; emit events at existing XML-parse points | ~40 |
| `integration/src/harness/evaluator.py` | Replace flat F2P/P2P with LayerEvaluator; keep existing framework parsers | ~60 |
| `integration/src/main.py` (or CLI entry) | Flag rename, deprecation shim, post-dispatch aggregation call | ~30 |
| `observability/eval_runner/runner.py` | Normalize inspect-ai transcript → TrajectoryWriter events | ~60 |
| `observability/eval_runner/inspect_scorer.py` | Invoke LayerEvaluator | ~30 |
| `observability/run_e2e.py` (or CLI entry) | Flag rename, deprecation shim, post-dispatch aggregation call | ~30 |
| `tasks/README.md` | Document layer/verifier/distractor conventions | +~100 |

**Total new code:** ~320 lines in `common/`, ~250 lines wire-up in existing files. No existing behavior changes when `test_layers.json` is absent and `--trials 1` is used.

### Reserved for future: hint injection

`tasks/<task_id>/hints.json` is a reserved filename. `multi_step_runner.py` and `runner.py` check for its presence; no-op when absent. Documented in `tasks/README.md` so task authors don't repurpose the filename.

## Risks

- **Inspect-ai transcript normalization** — inspect-ai's event model is not 1:1 with our envelope. Must verify the `ModelEvent` / `ToolEvent` / `ScoreEvent` → `reasoning` / `tool_call` / `tool_result` / `completion` mapping against real transcripts before declaring done.
- **Parallel aggregation timing** — `common/trials.py` must run *after* all workers have written their `results.json`. Both harnesses already write per-trial outputs; aggregation hooks into the existing "batch complete" callback (or runs from the CLI entry point after the dispatch loop returns).
- **Flag rename deprecation** — existing CI or scripts using `--n-trials` / `--max-workers` / `--parallel` must keep working. Deprecation shim with stderr warning is required for one release before hard-removing old names.
- **Cost metadata availability** — relies on LiteLLM and inspect-ai exposing tokens/cost/latency on every response. Must verify on all current models in the matrix (26+ integration models, observability model set).
- **Output path change** — `trial_01/` wrapper directory is introduced even for single-trial runs so path structure is uniform. Existing consumers reading `runs/<id>/results.json` directly must update to `runs/<id>/trial_01/results.json`. Must be called out in release notes alongside flag renames.

## Out of scope for v1

- Hint injection (reserve filename only)
- Model-grader / LLM-as-judge
- Tool output envelope standardization
- Cross-model / cross-task sweep config file
- Trajectory visualizer
- Cost budget kill-switch

## Implementation discipline

Real LLM evaluation runs are expensive and slow (single Kosmos task can cost several dollars and run for 10+ minutes per trial). Debugging harness bugs by running real LLM evaluations has an unacceptably long feedback loop. The implementation therefore commits to:

- **Test-driven development** (`superpowers:test-driven-development` skill) — each new module in `common/` (`trajectory.py`, `layers.py`, `trials.py`) is specified by failing unit tests before implementation. Tests use fixtures with fake trajectory events, synthetic test results, and in-memory file writes — no real LLM calls in the unit test loop.
- **Integration tests with mocked models** — the wire-up in `multi_step_runner.py` and `runner.py` is validated against recorded model responses and a fake tool executor, not live models.
- **One real-model smoke test per harness** — a single known-good `(model, task)` run executed end-to-end as a final gate before declaring done. This catches "my mocks were wrong" without requiring full matrix runs.
- **Commits after each logical chunk** — green tests + passing checks are committed before moving to the next piece, so any regression has a narrow bisect window.

## Versioning and rollback

- Work lives on branch `kosmos-harness-improvements` off `main`
- Commits are made after each logical chunk (new module, integration point, etc.) so any single change can be reverted without losing the rest
- `test_layers.json` and `hints.json` are optional; removing them at any point falls back to existing F2P/P2P behavior
