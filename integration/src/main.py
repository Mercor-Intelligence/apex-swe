#!/usr/bin/env python3
"""APEX SWE Harness - Main CLI Entry Point.

Simple command-line interface for running experiments.
"""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

# Add the integration directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.harness.executor import EvaluationExecutor
from src.harness.data_models import ModelType, EvaluationConfig

app = typer.Typer(
    no_args_is_help=True,
    help="APEX SWE Harness - Evaluate AI models on software engineering tasks"
)
console = Console()


def create_table(title: str, columns: list[tuple[str, str]]) -> Table:
    """Create a styled table."""
    table = Table(title=title, show_header=True, header_style="bold magenta")
    for col_name, col_style in columns:
        table.add_column(col_name, style=col_style)
    return table


@app.command(name="run")
def run_experiment(
    experiment_id: str = typer.Argument(..., help="Unique experiment identifier"),
    tasks: str = typer.Option(..., "--tasks", "-t", help="Comma-separated list of task IDs"),
    models: str = typer.Option(
        "claude-sonnet-4-20250514",
        "--models",
        "-m",
        help="Comma-separated list of models"
    ),
    trials: int = typer.Option(3, "--trials", "-n", "--n-trials", help="Number of trials per task-model (formerly --n-trials)"),
    timeout: int = typer.Option(900, "--timeout", help="Timeout per trial in seconds"),
    workers: int = typer.Option(4, "--workers", "-w", "--max-workers", help="Maximum parallel workers (formerly --max-workers)"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="Maximum steps per trial"),
    todo_tool_enabled: bool = typer.Option(False, "--todo-tool-enabled", help="Enable todo tool"),
    reasoning_effort: Optional[str] = typer.Option(None, "--reasoning-effort", help="Reasoning effort: low, medium, high (auto-detected for supported models)"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r", help="Results directory"),
    tasks_dir: Path = typer.Option(Path("tasks"), "--tasks-dir", "-d", help="Tasks directory"),
):
    """Run parallel experiments across multiple tasks and models."""

    import sys as _sys
    if any(a == "--n-trials" or a.startswith("--n-trials=") for a in _sys.argv):
        print("[DEPRECATED] --n-trials will be removed in a future release; "
              "use --trials instead.", file=_sys.stderr)
    if any(a == "--max-workers" or a.startswith("--max-workers=") for a in _sys.argv):
        print("[DEPRECATED] --max-workers will be removed in a future release; "
              "use --workers instead.", file=_sys.stderr)

    task_list = [t.strip() for t in tasks.split(",")]
    model_list = [m.strip() for m in models.split(",")]
    
    console.print(f"\n[bold]Starting experiment:[/bold] {experiment_id}\n")
    
    table = create_table(
        "Execution Plan",
        [
            ("Task", "cyan"),
            ("Models", "green"),
            ("Trials\nPer Model", "yellow"),
            ("Total\n Runs", "magenta"),
        ],
    )
    
    for task in task_list:
        table.add_row(
            task,
            ", ".join(model_list),
            str(trials),
            str(len(model_list) * trials),
        )
    
    console.print(table)
    console.print(f"\n[bold]Total runs to execute:[/bold] {len(task_list) * len(model_list) * trials}")
    console.print(f"[bold]Max parallel workers:[/bold] {workers}")
    console.print(f"[bold]Timeout per trial:[/bold] {timeout}s\n")
    
    try:
        experiment_dir = runs_dir / f'experiment_{experiment_id}'
        experiment_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "experiment_id": experiment_id,
            "tasks": task_list,
            "models": model_list,
            "n_trials": trials,
            "timeout": timeout,
            "created_at": datetime.now().isoformat(),
        }
        with open(experiment_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        executor = EvaluationExecutor(max_workers=workers)
        all_trials = []
        all_results = {}

        for task_id in task_list:
            for model in model_list:
                console.print(f"\n[bold cyan]Running task:[/bold cyan] {task_id} with {model}")

                task_dir = tasks_dir / task_id
                if not (task_dir / "task.yaml").exists():
                    console.print(f"[red]Skipping {task_id}: task.yaml not found[/red]")
                    continue

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                run_id = f"{experiment_id}_{task_id}_{model}_trial01_{timestamp}"

                config = EvaluationConfig(
                    run_id=run_id,
                    task_id=task_id,
                    model=model,
                    timeout=timeout,
                    runs_dir=runs_dir,
                    tasks_dir=tasks_dir,
                    max_steps=max_steps,
                    todo_tool_enabled=todo_tool_enabled,
                    reasoning_effort=reasoning_effort,
                    max_trials=trials,
                )

                result = executor.execute_run(config)

                trials = result.trials if hasattr(result, 'trials') else []
                all_trials.extend(trials)

                result_key = f"{task_id}_{model}"
                all_results[result_key] = (
                    result.model_dump() if hasattr(result, 'model_dump') else str(result)
                )

                task_successful = sum(
                    1
                    for t in trials
                    if t.status.value == "completed"
                    and t.metadata
                    and t.metadata.get("test_passed", False)
                )
                console.print(
                    f"  [dim]Task {task_id}: {task_successful}/{len(trials)} trials passed[/dim]"
                )

        successful = sum(
            1
            for t in all_trials
            if t.status.value == "completed" and t.metadata and t.metadata.get("test_passed", False)
        )
        failed = len(all_trials) - successful

        results_data = {
            "experiment_id": experiment_id,
            "total_runs": len(all_trials),
            "successful_runs": successful,
            "failed_runs": failed,
            "success_rate": successful / len(all_trials) if all_trials else 0.0,
            "experiment_duration": sum(t.execution_time for t in all_trials) if all_trials else 0.0,
            "results": all_results,
            "completed_at": datetime.now().isoformat(),
        }
        
        with open(experiment_dir / "results.json", "w") as f:
            json.dump(results_data, f, indent=4, default=str)
        
        console.print(f"\n\n[bold green]Experiment completed:[/bold green] {experiment_id}")
        console.print(f"[bold]Total runs:[/bold] {results_data['total_runs']}")
        console.print(f"[bold]Successful:[/bold] {results_data['successful_runs']}")
        console.print(f"[bold]Failed:[/bold] {results_data['failed_runs']}")
        console.print(f"[bold]Success rate:[/bold] {results_data['success_rate']:.1%}")
        console.print(f"[bold]Duration:[/bold] {results_data['experiment_duration']:.2f}s")
        console.print(f"\n[bold]Results saved to:[/bold] {experiment_dir}\n")
        
    except KeyboardInterrupt:
        console.print("\n\n[bold yellow]Experiment interrupted by user[/bold yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n\n[bold red]Error:[/bold red] {e}")
        console.print(f"\n[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


@app.command(name="list-models")
def list_models():
    """List available AI models."""
    console.print("\n[bold]Available Models:[/bold]\n")
    
    models_by_provider = {}
    for model in ModelType:
        if model.name.startswith("_"):
            continue
        provider = model.value.split("/")[0] if "/" in model.value else model.value.split("-")[0]
        if provider not in models_by_provider:
            models_by_provider[provider] = []
        models_by_provider[provider].append(model.value)
    
    for provider, model_list in sorted(models_by_provider.items()):
        console.print(f"[bold cyan]{provider.upper()}[/bold cyan]")
        for model in sorted(model_list):
            console.print(f"  • {model}")
        console.print()


@app.command(name="list-tasks")
def list_tasks(
    tasks_dir: Path = typer.Option(Path("tasks"), "--tasks-dir", "-d", help="Tasks directory")
):
    """List available tasks."""
    console.print(f"\n[bold]Available Tasks in {tasks_dir}:[/bold]\n")
    
    if not tasks_dir.exists():
        console.print(f"[red]Tasks directory not found: {tasks_dir}[/red]")
        return
    
    tasks = sorted([d.name for d in tasks_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    
    for task in tasks:
        task_yaml = tasks_dir / task / "task.yaml"
        if task_yaml.exists():
            console.print(f"  [green]✓[/green] {task}")
        else:
            console.print(f"  [yellow]?[/yellow] {task} [dim](no task.yaml)[/dim]")
    
    console.print(f"\n[bold]Total:[/bold] {len(tasks)} tasks\n")


def cli():
    """CLI entry point."""
    app()


if __name__ == "__main__":
    cli()
