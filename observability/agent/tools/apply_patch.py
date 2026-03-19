"""Apply patch tool for modifying files in the sandbox."""

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox


@tool
def apply_patch():
    """Apply a patch to create, update, or delete files. PRIMARY tool for editing code."""

    async def execute(patch: str) -> str:
        """Apply a patch to modify files.

        Args:
            patch (str): The patch content in *** Begin Patch format. Use *** Add File, *** Update File, or *** Delete File headers. For updates, use @@ for context, space for unchanged lines, - for removals, + for additions. Example: *** Begin Patch *** Update File: src/main.py @@ def hello(): -print("Hi") +print("Hello!") *** End Patch

        Returns:
            Result of applying the patch including which files were modified.
        """
        if not patch or not patch.strip():
            raise ToolError("No patch content provided")

        # Use heredoc to pass the patch to apply_patch tool in the container
        # The apply_patch script reads from stdin
        command = f"""apply_patch << 'PATCH_EOF'
{patch}
PATCH_EOF"""

        result = await sandbox().exec(
            ["bash", "-c", command],
            timeout=60,
        )

        if result.success:
            output = result.stdout.strip()
            if not output:
                output = "Patch applied successfully"
            return output
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            stdout_msg = result.stdout.strip() if result.stdout else ""
            full_msg = f"Patch application failed:\n{error_msg}"
            if stdout_msg:
                full_msg += f"\nOutput:\n{stdout_msg}"
            raise ToolError(full_msg)

    return execute

