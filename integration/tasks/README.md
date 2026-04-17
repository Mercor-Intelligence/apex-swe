# Task Authoring — Kosmos Evaluation Conventions

This document describes task-authoring conventions for the apex-swe-harness Kosmos evaluation layer. Tasks that don't follow these conventions continue to work using the existing F2P/P2P scoring.

## `test_layers.json` (optional)

Place at `<task_id>/test_layers.json` to group tests into evaluation layers with per-layer thresholds. If absent, the harness falls back to flat F2P/P2P layers.

### Schema

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

### Threshold types

- `"pass^k": 1.0` — all k trials must pass this layer (strict)
- `"pass@k": 0.80` — pass rate across k trials must be ≥ 0.80 (tolerant)

### Special tokens

- `@F2P` expands to the task's Fail-to-Pass test list
- `@P2P` expands to the task's Pass-to-Pass test list

## State-level verifiers

Verifier scripts live under `<task_id>/tests/verifiers/*.sh`. Three types:

1. **Repo-state** — run `pytest` or similar against the agent's code changes.
2. **Trajectory** — assert on `trajectory.jsonl` to verify the agent took certain actions. Example:
   ```bash
   #!/bin/bash
   jq -e 'select(.type=="tool_call" and .tool=="bash" and (.args.cmd | contains("mattermost")))' trajectory.jsonl > /dev/null \
     && echo "PASSED" || echo "FAILED"
   ```
3. **Service-state** — assert on MCP service state. Example:
   ```bash
   #!/bin/bash
   curl -s mattermost:8065/api/v4/posts \
     | jq -e '.[] | select(.message | contains("migration complete"))' > /dev/null \
     && echo "PASSED" || echo "FAILED"
   ```

### Rules for verifier scripts

- Emit `PASSED` or `FAILED` as the last non-empty stdout line.
- Exit 0 on pass, non-zero on fail (both signals checked; `PASSED`/`FAILED` line is authoritative).
- Read `trajectory.jsonl` from the current working directory (evaluator `cd`s to trial dir before invoking).

## Distractor data seeding

Bake distractor data directly into existing task seed scripts (`seed.sh` or similar). Categories:

- **Outdated files** — stale spec docs (dated 6+ months ago), old README revisions with superseded instructions
- **Resolved issues** — closed Plane/Zammad tickets describing related-but-different fixed bugs
- **Off-topic conversations** — Mattermost channel messages about adjacent work (unrelated features, holiday party)
- **Archived dashboards** — Grafana dashboards with similar names referencing dead metrics
- **Inactive users** — EspoCRM/Plane users with matching titles to active ones

### Quality rules

- **Plausible** — obviously-wrong distractors filter immediately and add no signal
- **Dated or flagged** — agent should be able to identify staleness via timestamps or archive markers
- **Non-blocking** — passing the task should never require using distractor data

## `hints.json` (reserved, not yet implemented)

The filename `<task_id>/hints.json` is reserved for future hint injection. Do not repurpose this filename.
