"""Todo management tool."""

from datetime import datetime
from typing import Any

from .tool import Tool


class TodoTool(Tool):
    """Manage an in-memory list of todo tasks for the current run."""

    def __init__(self):
        """Initialize the todo tool with in-memory storage."""
        self._tasks: list[dict[str, Any]] = []
        self._next_id: int = 1
        self._valid_statuses = {"todo", "inprogress", "done"}

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return "Manage todo tasks (add, list, update_status, delete, bulk_add)"

    def execute(self, action: str, **kwargs) -> dict[str, Any]:
        """Execute a todo action.

        Supported actions:
        - add(title, status='todo')
        - bulk_add(tasks=[{title, status?}, ...])
        - list()
        - update_status(id? or title?, status)
        - delete(id or title)
        """
        try:
            if action == "add":
                title = (kwargs.get("title") or "").strip()
                status = (kwargs.get("status") or "todo").strip().lower()
                if not title:
                    return {"success": False, "error": "Missing parameter: title"}
                if status not in self._valid_statuses:
                    return {"success": False, "error": f"Invalid status: {status}"}
                task = self._create_task(title, status)
                self._tasks.append(task)
                return {"success": True, "task": task}

            if action == "bulk_add":
                tasks = kwargs.get("tasks")
                if not isinstance(tasks, list):
                    return {
                        "success": False,
                        "error": "Missing or invalid parameter: tasks (list required)",
                    }
                added = []
                for entry in tasks:
                    if not isinstance(entry, dict):
                        continue
                    title = (entry.get("title") or "").strip()
                    status = (entry.get("status") or "todo").strip().lower()
                    if not title or status not in self._valid_statuses:
                        continue
                    task = self._create_task(title, status)
                    self._tasks.append(task)
                    added.append(task)
                return {"success": True, "tasks": added, "count": len(added)}

            if action == "list":
                return {
                    "success": True,
                    "tasks": list(self._tasks),
                    "count": len(self._tasks),
                }

            if action == "update_status":
                status = (kwargs.get("status") or "").strip().lower()
                if status not in self._valid_statuses:
                    return {"success": False, "error": f"Invalid status: {status}"}
                task = self._find_task(kwargs)
                if not task:
                    return {"success": False, "error": "Task not found"}
                task["status"] = status
                task["updated_at"] = datetime.now().isoformat()
                return {"success": True, "task": task}

            if action == "delete":
                task = self._find_task(kwargs)
                if not task:
                    return {"success": False, "error": "Task not found"}
                self._tasks = [t for t in self._tasks if t["id"] != task["id"]]
                return {"success": True, "deleted": True, "id": task["id"]}

            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_task(self, title: str, status: str) -> dict[str, Any]:
        now = datetime.now().isoformat()
        task = {
            "id": self._next_id,
            "title": title,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        self._next_id += 1
        return task

    def _find_task(self, selector: dict[str, Any]) -> dict[str, Any] | None:
        task_id = selector.get("id")
        title = selector.get("title") or None
        if isinstance(task_id, int):
            for t in self._tasks:
                if t["id"] == task_id:
                    return t
        if isinstance(title, str):
            for t in self._tasks:
                if t["title"] == title:
                    return t
        return None
