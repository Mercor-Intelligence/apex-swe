"""Update plan tool for tracking task progress."""

from typing import Any

from inspect_ai.tool import tool
from inspect_ai.util import store


@tool
def update_plan():
    """Update the task plan with steps and their statuses to track progress."""

    async def execute(steps: list[dict[str, Any]]) -> str:
        """Update the task plan with steps and their statuses.

        Args:
            steps (list): List of step objects with description and status keys. Each step should have description (what this step does) and status (one of pending, in_progress, completed). Example: [{"description": "Query Loki logs", "status": "completed"}]

        Returns:
            Formatted plan showing all steps and their statuses.
        """
        if not steps:
            return "No steps provided. Provide a list of step objects with 'description' and 'status' fields."

        # Validate and normalize steps
        valid_statuses = {"pending", "in_progress", "completed"}
        normalized_steps = []

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue

            description = step.get("description", f"Step {i + 1}")
            status = step.get("status", "pending").lower()

            if status not in valid_statuses:
                status = "pending"

            normalized_steps.append({
                "description": description,
                "status": status,
            })

        # Store the plan in the sample store for potential use by scorers
        store().set("task_plan", normalized_steps)

        # Format the plan for display
        status_icons = {
            "completed": "✓",
            "in_progress": "→",
            "pending": "○",
        }

        lines = ["## Task Plan\n"]
        for i, step in enumerate(normalized_steps, 1):
            icon = status_icons.get(step["status"], "○")
            lines.append(f"{i}. [{icon}] {step['description']} ({step['status']})")

        # Add summary
        completed = sum(1 for s in normalized_steps if s["status"] == "completed")
        in_progress = sum(1 for s in normalized_steps if s["status"] == "in_progress")
        pending = sum(1 for s in normalized_steps if s["status"] == "pending")

        lines.append(f"\nProgress: {completed} completed, {in_progress} in progress, {pending} pending")

        return "\n".join(lines)

    return execute

