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
    n_trials: int = typer.Option(3, "--n-trials", "-n", help="Number of trials per task-model"),
    timeout: int = typer.Option(900, "--timeout", help="Timeout per trial in seconds"),
    max_workers: int = typer.Option(4, "--max-workers", "-w", help="Maximum parallel workers"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="Maximum steps per trial"),
    todo_tool_enabled: bool = typer.Option(False, "--todo-tool-enabled", help="Enable todo tool"),
    reasoning_effort: Optional[str] = typer.Option(None, "--reasoning-effort", help="Reasoning effort: low, medium, high (auto-detected for supported models)"),
    runs_dir: Path = typer.Option(Path("runs"), "--runs-dir", "-r", help="Results directory"),
    tasks_dir: Path = typer.Option(Path("tasks"), "--tasks-dir", "-d", help="Tasks directory"),
):
    """Run parallel experiments across multiple tasks and models."""
    
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
            str(n_trials),
            str(len(model_list) * n_trials),
        )
    
    console.print(table)
    console.print(f"\n[bold]Total runs to execute:[/bold] {len(task_list) * len(model_list) * n_trials}")
    console.print(f"[bold]Max parallel workers:[/bold] {max_workers}")
    console.print(f"[bold]Timeout per trial:[/bold] {timeout}s\n")
    
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"{experiment_id}_{task_list[0]}_{model_list[0]}_trial01_{timestamp}"
        
        config = EvaluationConfig(
            run_id=run_id,
            task_id=task_list[0],
            model=model_list[0],
            timeout=timeout,
            runs_dir=runs_dir,
            tasks_dir=tasks_dir,
            max_steps=max_steps,
            todo_tool_enabled=todo_tool_enabled,
            reasoning_effort=reasoning_effort,
            max_trials=n_trials,
        )
        
        console.print("[dim]Starting evaluation executor...[/dim]")
        executor = EvaluationExecutor(max_workers=max_workers)
        console.print("[dim]Running evaluation...[/dim]")
        result = executor.execute_run(config)
        console.print("[dim]Evaluation complete, processing results...[/dim]")
        
        experiment_dir = runs_dir / f'experiment_{experiment_id}'
        experiment_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "experiment_id": experiment_id,
            "tasks": task_list,
            "models": model_list,
            "n_trials": n_trials,
            "timeout": timeout,
            "created_at": datetime.now().isoformat(),
        }
        with open(experiment_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        trials = result.trials if hasattr(result, 'trials') else []
        successful = sum(1 for t in trials if str(t.status) == "completed")
        failed = len(trials) - successful
        
        results_data = {
            "experiment_id": experiment_id,
            "total_runs": len(trials),
            "successful_runs": successful,
            "failed_runs": failed,
            "success_rate": successful / len(trials) if trials else 0.0,
            "experiment_duration": sum(t.execution_time for t in trials) if trials else 0.0,
            "results": {
                f"{task_list[0]}_{model_list[0]}_trial01": result.model_dump() if hasattr(result, 'model_dump') else str(result)
            },
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
