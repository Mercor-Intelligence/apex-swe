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
