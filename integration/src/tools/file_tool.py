"""File system operations tool."""

import shutil
from pathlib import Path
from typing import Any

from .tool import Tool


class FileTool(Tool):
    """File system operations tool."""

    def __init__(self, working_dir: Path | None = None):
        """
        Initialize file tool.

        Args:
            working_dir: Base directory for file operations
        """
        self.working_dir = working_dir or Path.cwd()

    @property
    def name(self) -> str:
        return "file"

    @property
    def description(self) -> str:
        return "File system operations (read, write, list, etc.)"

    def execute(self, operation: str, path: str, **kwargs) -> dict[str, Any]:
        """
        Execute file operation.

        Args:
            operation: Operation type (read, write, list, delete, etc.)
            path: File/directory path
            **kwargs: Additional parameters based on operation

        Returns:
            Operation result
        """
        full_path = (
            self.working_dir / path if not Path(path).is_absolute() else Path(path)
        )

        try:
            if operation == "read":
                return self._read_file(full_path)
            elif operation == "write":
                content = kwargs.get("content", "")
                return self._write_file(full_path, content)
            elif operation == "list":
                return self._list_directory(full_path)
            elif operation == "delete":
                return self._delete_path(full_path)
            elif operation == "exists":
                return {"exists": full_path.exists(), "path": str(full_path)}
            elif operation == "mkdir":
                return self._make_directory(full_path)
            elif operation == "copy":
                dest = kwargs.get("destination")
                if not dest:
                    raise ValueError("Destination required for copy operation")
                return self._copy_path(full_path, self.working_dir / dest)
            elif operation == "move":
                dest = kwargs.get("destination")
                if not dest:
                    raise ValueError("Destination required for move operation")
                return self._move_path(full_path, self.working_dir / dest)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "operation": operation,
                "path": str(full_path),
            }

    def _read_file(self, path: Path) -> dict[str, Any]:
        """Read file contents."""
        if not path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        try:
            content = path.read_text()
            return {
                "success": True,
                "content": content,
                "path": str(path),
                "size": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _write_file(self, path: Path, content: str) -> dict[str, Any]:
        """Write content to file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return {"success": True, "path": str(path), "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_directory(self, path: Path) -> dict[str, Any]:
        """List directory contents."""
        if not path.exists():
            return {"success": False, "error": f"Directory not found: {path}"}

        if not path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        try:
            items = []
            for item in path.iterdir():
                items.append(
                    {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                )
            return {
                "success": True,
                "items": items,
                "path": str(path),
                "count": len(items),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_path(self, path: Path) -> dict[str, Any]:
        """Delete file or directory."""
        if not path.exists():
            return {"success": False, "error": f"Path not found: {path}"}

        try:
            if path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _make_directory(self, path: Path) -> dict[str, Any]:
        """Create directory."""
        try:
            path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _copy_path(self, src: Path, dest: Path) -> dict[str, Any]:
        """Copy file or directory."""
        if not src.exists():
            return {"success": False, "error": f"Source not found: {src}"}

        try:
            if src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            else:
                shutil.copytree(src, dest, dirs_exist_ok=True)
            return {"success": True, "source": str(src), "destination": str(dest)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _move_path(self, src: Path, dest: Path) -> dict[str, Any]:
        """Move file or directory."""
        if not src.exists():
            return {"success": False, "error": f"Source not found: {src}"}

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            return {"success": True, "source": str(src), "destination": str(dest)}
        except Exception as e:
            return {"success": False, "error": str(e)}
