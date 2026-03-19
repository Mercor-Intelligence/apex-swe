#!/usr/bin/env python3
"""
Run E2E evaluation (agent + scoring) for observability tasks.

Single Task:
    python run_e2e.py --task <task_id> --model <model_name>

Multiple Tasks (Parallel):
    python run_e2e.py --tasks task1 task2 --model <model> --parallel 4
    python run_e2e.py --tasks-file tasks.txt --model <model> --parallel 6
    python run_e2e.py --all --model <model> --parallel 4

Examples:
    # Single task
    python run_e2e.py --task crankyoldgit-irremoteesp8266-1733-1734-observability --model claude-opus-4-5
    
    # Multiple tasks in parallel
    python run_e2e.py --tasks task1 task2 task3 --model claude-opus-4-5 --parallel 4
    
    # All tasks with 3 trials each
    python run_e2e.py --all --model claude-opus-4-5 --trials 3 --parallel 6
    
    # Resume interrupted run
    python run_e2e.py --all --model claude-opus-4-5 --output results/ --resume

Environment:
    API keys can be set via environment variables or in a .env file at project root.
    See env.example for available variables.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# NOTE: This worker must be defined at module scope so it can be pickled
# by multiprocessing when using the "spawn" start method.
def _run_evaluation_worker(
    pipe,
    task_id: str,
    model: str,
    trial: int,
    time_limit: int,
    message_limit: int,
    max_retries: int,
    start_time: float,
) -> None:
    """Run a single evaluation in a child process and send result over pipe."""
    from eval_runner import run_evaluation_sync

    try:
        result = run_evaluation_sync(
            task_id=task_id,
            model=model,
            trial=trial,
            time_limit=time_limit,
            message_limit=message_limit,
            verbose=False,
            max_retries=max_retries,
        )
        pipe.send(
            dict(
                task_id=task_id,
                model=model,
                trial=trial,
                success=result.agent_success,
                passed=result.passed,
                f2p_passed=result.f2p_passed,
                f2p_total=result.f2p_total,
                p2p_passed=result.p2p_passed,
                p2p_total=result.p2p_total,
                test_exit_code=result.test_exit_code,
                agent_duration=result.agent_duration,
                scoring_duration=result.scoring_duration,
                total_duration=result.total_duration,
                error=result.agent_error or result.scoring_error,
                run_id=result.run_id,
            )
        )
    except Exception as e:
        elapsed = time.time() - start_time
        pipe.send(asdict(CLIResult.failure(
            task_id=task_id,
            model=model,
            trial=trial,
            elapsed=elapsed,
            error=str(e),
        )))

# Add paths - run_e2e.py is now at observability/ root alongside eval_runner, parser, etc.
OBSERVABILITY_DIR = Path(__file__).parent
sys.path.insert(0, str(OBSERVABILITY_DIR))

# Note: .env loading is handled by eval_runner.config on import


@dataclass
class CLIResult:
    """Result for a single E2E run (CLI output format).
    
    Note: This is distinct from eval_runner.E2EResult which contains
    full execution details. CLIResult is a simplified view for CLI output.
    """
    task_id: str
    model: str
    trial: int
    success: bool
    passed: bool
    f2p_passed: int
    f2p_total: int
    p2p_passed: int
    p2p_total: int
    test_exit_code: int
    agent_duration: float
    scoring_duration: float
    total_duration: float
    error: str | None = None
    run_id: str | None = None

    @classmethod
    def failure(
        cls,
        task_id: str,
        model: str,
        trial: int,
        elapsed: float,
        error: str,
    ) -> CLIResult:
        """Create a CLIResult representing a failed run."""
        return cls(
            task_id=task_id,
            model=model,
            trial=trial,
            success=False,
            passed=False,
            f2p_passed=0,
            f2p_total=0,
            p2p_passed=0,
            p2p_total=0,
            test_exit_code=-1,
            agent_duration=elapsed,
            scoring_duration=0,
            total_duration=elapsed,
            error=error,
        )


def run_single_e2e(
    task_id: str,
    model: str,
    trial: int,
    time_limit: int,
    message_limit: int,
    max_retries: int,
    run_timeout: int | None = None,
) -> CLIResult:
    """Run a single E2E evaluation (for parallel execution)."""
    from eval_runner import run_evaluation_sync
    
    start_time = time.time()
    
    try:
        if run_timeout:
            parent_conn, child_conn = mp.Pipe(False)
            ctx = mp.get_context("spawn")
            proc = ctx.Process(
                target=_run_evaluation_worker,
                args=(
                    child_conn,
                    task_id,
                    model,
                    trial,
                    time_limit,
                    message_limit,
                    max_retries,
                    start_time,
                ),
            )
            proc.start()
            proc.join(timeout=run_timeout)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
                return CLIResult.failure(
                    task_id=task_id,
                    model=model,
                    trial=trial,
                    elapsed=time.time() - start_time,
                    error=f"Run timeout exceeded ({run_timeout}s)",
                )
            if parent_conn.poll():
                return CLIResult(**parent_conn.recv())
            return CLIResult.failure(
                task_id=task_id,
                model=model,
                trial=trial,
                elapsed=time.time() - start_time,
                error="Run ended without result",
            )

        # No per-run timeout: call directly
        result = run_evaluation_sync(
            task_id=task_id,
            model=model,
            trial=trial,
            time_limit=time_limit,
            message_limit=message_limit,
            verbose=False,
            max_retries=max_retries,
        )
        return CLIResult(
            task_id=task_id,
            model=model,
            trial=trial,
            success=result.agent_success,
            passed=result.passed,
            f2p_passed=result.f2p_passed,
            f2p_total=result.f2p_total,
            p2p_passed=result.p2p_passed,
            p2p_total=result.p2p_total,
            test_exit_code=result.test_exit_code,
            agent_duration=result.agent_duration,
            scoring_duration=result.scoring_duration,
            total_duration=result.total_duration,
            error=result.agent_error or result.scoring_error,
            run_id=result.run_id,
        )
    except Exception as e:
        return CLIResult.failure(
            task_id=task_id,
            model=model,
            trial=trial,
            elapsed=time.time() - start_time,
            error=str(e),
        )


def load_completed_runs(output_dir: Path) -> set[tuple[str, str, int]]:
    """Load completed (task_id, model, trial) tuples from previous results."""
    completed = set()
    results_file = output_dir / "results.json"
    
    if results_file.exists():
        try:
            with open(results_file) as f:
                data = json.load(f)
            for entry in data.get("results", []):
                key = (entry["task_id"], entry["model"], entry["trial"])
                completed.add(key)
        except (json.JSONDecodeError, KeyError):
            pass
    
    return completed


def save_results(output_dir: Path, results: list[CLIResult], model: str) -> None:
    """Save results to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    result_dicts = [asdict(r) for r in results]
    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    
    data = {
        "generated_at": datetime.now().isoformat(),
        "model": model,
        "total_runs": total_count,
        "passed_count": passed_count,
        "pass_rate": passed_count / total_count if total_count > 0 else 0,
        "results": result_dicts,
    }
    
    results_file = output_dir / "results.json"
    # Write atomically so partial/interrupted runs don't leave a corrupted JSON file.
    tmp_file = output_dir / "results.json.tmp"
    with open(tmp_file, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, results_file)


def run_single_mode(args, logger, all_tasks) -> int:
    """Run single task mode (detailed output)."""
    from eval_runner import (
        run_agent_sync,
        run_evaluation_sync,
        validate_health_checks,
        MODELS,
    )
    
    # Validate task
    if args.task not in all_tasks:
        logger.error(f"Task '{args.task}' not found")
        logger.info(f"Available tasks ({len(all_tasks)} total):")
        for t in sorted(all_tasks)[:10]:
            logger.info(f"  - {t}")
        logger.info("  ...")
        return 1
    
    # Validate model
    if args.model not in MODELS:
        logger.error(f"Model '{args.model}' not found")
        logger.info(f"Available models: {list(MODELS.keys())}")
        return 1
    
    logger.info("=" * 60)
    logger.info("E2E Evaluation")
    logger.info("=" * 60)
    logger.info(f"Task:    {args.task}")
    logger.info(f"Model:   {args.model}")
    logger.info(f"Trial:   {args.trial}")
    logger.info(f"Timeout: {args.time_limit}s")
    logger.info("=" * 60)
    
    # Run health checks
    if not args.skip_health_check:
        logger.info("\nRunning pre-flight health checks...")
        if not validate_health_checks(task_id=args.task, model=args.model):
            logger.error("Health checks failed. Use --skip-health-check to bypass.")
            return 1
        logger.info("Health checks passed.\n")
    
    output_data: dict[str, Any] = {}
    
    if args.agent_only:
        # Run agent only
        logger.info("[1/1] Running agent...")
        result = run_agent_sync(
            task_id=args.task,
            model=args.model,
            trial=args.trial,
            time_limit=args.time_limit,
            message_limit=args.message_limit,
            max_retries=args.max_retries,
            skip_health_check=True,
        )
        
        logger.info(f"\nAgent Result:")
        logger.info(f"  Success: {result.success}")
        logger.info(f"  Run ID: {result.run_id}")
        logger.info(f"  Diff length: {len(result.agent_diff)} chars")
        logger.info(f"  Changed files: {len(result.changed_files)}")
        logger.info(f"  Duration: {result.duration_seconds:.1f}s")
        if result.error:
            logger.error(f"  Error: {result.error}")
        
        output_data = result.to_dict()
        output_data["agent_diff"] = result.agent_diff
        success = result.success
        
    else:
        # Run full E2E (agent + scoring)
        logger.info("[1/2] Running agent...")
        result = run_evaluation_sync(
            task_id=args.task,
            model=args.model,
            trial=args.trial,
            time_limit=args.time_limit,
            message_limit=args.message_limit,
            verbose=args.verbose,
            max_retries=args.max_retries,
        )
        
        logger.info(f"[2/2] Scoring complete!")
        logger.info(f"\nResults:")
        logger.info(f"  Agent Success: {result.agent_success}")
        logger.info(f"  Run ID: {result.run_id}")
        logger.info(f"  Score: {result.score}")
        logger.info(f"  Test Exit Code: {result.test_exit_code}")
        logger.info(f"  Passed: {result.passed}")
        logger.info(f"  F2P: {result.f2p_passed}/{result.f2p_total}")
        logger.info(f"  P2P: {result.p2p_passed}/{result.p2p_total}")
        logger.info(f"  Agent Duration: {result.agent_duration:.1f}s")
        logger.info(f"  Scoring Duration: {result.scoring_duration:.1f}s")
        logger.info(f"  Total Duration: {result.total_duration:.1f}s")
        if result.agent_error:
            logger.error(f"  Agent Error: {result.agent_error}")
        if result.scoring_error:
            logger.error(f"  Scoring Error: {result.scoring_error}")
        
        output_data = result.to_dict()
        success = result.passed
    
    # Save output
    if args.output:
        try:
            output_path = Path(args.output)
            if output_path.suffix == ".json":
                with open(output_path, "w") as f:
                    json.dump(output_data, f, indent=2)
            else:
                output_path.mkdir(parents=True, exist_ok=True)
                with open(output_path / "result.json", "w") as f:
                    json.dump(output_data, f, indent=2)
            logger.info(f"\nResults saved to: {args.output}")
        except OSError as e:
            logger.error(f"Failed to save results: {e}")
    
    logger.info("\n" + "=" * 60)
    status = "✅ PASSED" if success else "❌ FAILED"
    logger.info(f"Final Status: {status}")
    logger.info("=" * 60)
    
    return 0 if success else 1


def run_parallel_mode(args, all_tasks) -> int:
    """Run parallel mode for multiple tasks."""
    from eval_runner import MODELS
    
    # Validate model
    if args.model not in MODELS:
        print(f"Error: Model '{args.model}' not found")
        print(f"Available models: {list(MODELS.keys())}")
        return 1
    
    # Get task list
    if args.tasks:
        task_ids = args.tasks
    elif args.tasks_file:
        with open(args.tasks_file) as f:
            task_ids = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    else:
        task_ids = sorted(all_tasks)
    
    # Validate tasks
    invalid_tasks = [t for t in task_ids if t not in all_tasks]
    if invalid_tasks:
        print(f"Error: Invalid task IDs: {invalid_tasks[:5]}...")
        return 1
    
    # Build work items
    work_items = [
        (task_id, args.model, trial)
        for task_id in task_ids
        for trial in range(1, args.trials + 1)
    ]
    
    # Handle resume
    output_dir = Path(args.output) if args.output else Path("results")
    completed = set()
    results: list[CLIResult] = []
    
    if args.resume:
        completed = load_completed_runs(output_dir)
        results_file = output_dir / "results.json"
        if results_file.exists():
            with open(results_file) as f:
                data = json.load(f)
            for entry in data.get("results", []):
                results.append(CLIResult(**entry))
        
        work_items = [w for w in work_items if w not in completed]
        print(f"Resuming: {len(completed)} completed, {len(work_items)} remaining")
    
    if not work_items:
        print("No work items to process.")
        return 0
    
    print("=" * 70)
    print("E2E Parallel Evaluation")
    print("=" * 70)
    print(f"Model:      {args.model}")
    print(f"Tasks:      {len(task_ids)}")
    print(f"Trials:     {args.trials}")
    print(f"Total runs: {len(work_items)}")
    print(f"Workers:    {args.parallel}")
    print(f"Output:     {output_dir}")
    print("=" * 70)
    
    start_time = time.time()
    completed_count = 0
    passed_count = sum(1 for r in results if r.passed)
    
    # Run in parallel
    with ProcessPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(
                run_single_e2e,
                task_id,
                model,
                trial,
                args.time_limit,
                args.message_limit,
                args.max_retries,
                args.run_timeout,
            ): (task_id, model, trial)
            for task_id, model, trial in work_items
        }
        
        for future in as_completed(futures):
            task_id, model, trial = futures[future]
            completed_count += 1
            
            try:
                result = future.result()
                results.append(result)
                
                if result.passed:
                    passed_count += 1
                    status = "✅ PASSED"
                else:
                    status = "❌ FAILED"
                
                elapsed = time.time() - start_time
                # Rate in tasks per hour, ETA in minutes
                rate = (completed_count / elapsed) * 3600 if elapsed > 0 else 0
                remaining = len(work_items) - completed_count
                eta = (remaining / rate) * 60 if rate > 0 else float('inf')
                
                eta_str = f"{eta:.0f}min" if eta != float('inf') else "calculating..."
                print(
                    f"[{completed_count}/{len(work_items)}] {task_id} T{trial}: {status} "
                    f"(F2P: {result.f2p_passed}/{result.f2p_total}, "
                    f"P2P: {result.p2p_passed}/{result.p2p_total}) "
                    f"[{result.total_duration:.0f}s] "
                    f"ETA: {eta_str}"
                )
                
                if result.error and args.verbose:
                    print(f"    Error: {result.error[:100]}...")
                
            except Exception as e:
                print(f"[{completed_count}/{len(work_items)}] {task_id} T{trial}: ❌ ERROR: {e}")
            
            # Save incrementally
            save_results(output_dir, results, args.model)
    
    # Final summary
    total_elapsed = time.time() - start_time
    total_runs = len(results)
    pass_rate = passed_count / total_runs if total_runs > 0 else 0
    
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total runs:   {total_runs}")
    print(f"Passed:       {passed_count}")
    print(f"Failed:       {total_runs - passed_count}")
    print(f"Pass rate:    {pass_rate:.1%}")
    print(f"Total time:   {total_elapsed/60:.1f} minutes")
    print(f"Results:      {output_dir}/results.json")
    print("=" * 70)
    
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run E2E evaluation for observability tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single task
  python run_e2e.py --task my-task --model claude-opus-4-5
  
  # Multiple tasks (parallel)
  python run_e2e.py --tasks task1 task2 --model claude-opus-4-5 --parallel 4
  
  # All tasks
  python run_e2e.py --all --model claude-opus-4-5 --parallel 6
  
  # Resume interrupted run
  python run_e2e.py --all --model claude-opus-4-5 --resume
        """
    )
    
    # Task selection (mutually exclusive)
    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Single task ID to evaluate")
    task_group.add_argument("--tasks", nargs="+", help="Multiple task IDs to evaluate")
    task_group.add_argument("--tasks-file", help="File with task IDs (one per line)")
    task_group.add_argument("--all", action="store_true", help="Run all available tasks")
    
    # Common options
    parser.add_argument("--model", default="claude-opus-4-5", help="Model to use (default: claude-opus-4-5)")
    parser.add_argument("--trial", type=int, default=1, help="Trial number (single mode)")
    parser.add_argument("--trials", type=int, default=1, help="Number of trials per task (parallel mode)")
    parser.add_argument("--time-limit", type=int, default=60*60, help="Time limit in seconds (default: 3600)")
    parser.add_argument("--message-limit", type=int, default=250, help="Message limit for agent (default: 250)")
    parser.add_argument("--max-retries", type=int, default=2, help="Retries for transient failures (default: 2)")
    parser.add_argument(
        "--run-timeout",
        type=int,
        default=None,
        help="Per-run timeout in seconds (parallel mode). If exceeded, the run is terminated and recorded as failed.",
    )
    parser.add_argument("--output", "-o", help="Output file/directory for results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--debug", action="store_true", help="Debug output (more verbose)")
    
    # Single task mode options
    parser.add_argument("--agent-only", action="store_true", help="Only run agent, skip scoring (single mode)")
    parser.add_argument("--skip-health-check", action="store_true", help="Skip pre-flight health checks")
    
    # Parallel mode options
    parser.add_argument("--parallel", "-p", type=int, default=1, help="Number of parallel workers (default: 1)")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (parallel mode)")
    
    args = parser.parse_args()
    
    # Import eval_runner
    from eval_runner import get_all_task_ids, get_logger, set_log_level
    
    # Set log level
    if args.debug:
        set_log_level("DEBUG")
    elif args.verbose:
        set_log_level("INFO")
    
    logger = get_logger("run_e2e")
    all_tasks = get_all_task_ids()
    
    # Determine mode: single vs parallel
    is_single_mode = args.task is not None and args.parallel == 1
    
    if is_single_mode:
        exit_code = run_single_mode(args, logger, all_tasks)
    else:
        # Convert single task to list for parallel mode
        if args.task:
            args.tasks = [args.task]
        exit_code = run_parallel_mode(args, all_tasks)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
