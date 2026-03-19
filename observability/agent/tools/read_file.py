"""Read file tool for inspecting file contents in the sandbox."""

from inspect_ai.tool import Tool, ToolResult, tool
from inspect_ai.util import sandbox as sandbox_env


@tool
def read_file(timeout: int | None = None) -> Tool:
    """Read the contents of a file in the sandbox environment.

    Use this tool to read source code, configuration files, or any text file
    to understand its contents and structure.

    Args:
        timeout: Timeout (in seconds) for command. Defaults to 30 if not provided.

    Returns:
        A tool for reading file contents.
    """
    timeout = timeout or 30

    async def execute(path: str) -> ToolResult:
        """Read the contents of a file.

        Args:
            path: The path to the file to read (relative to working directory or absolute).

        Returns:
            The contents of the file, or an error message if the file cannot be read.
        """
        # Use cat to read the file contents in the sandbox
        result = await sandbox_env().exec(
            cmd=["cat", path],
            timeout=timeout,
        )

        if result.success:
            return result.stdout
        else:
            # Try to provide helpful error message
            error = result.stderr.strip() if result.stderr else "Unknown error"
            return f"Error reading file '{path}': {error}"

    return execute
