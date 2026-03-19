"""Search files tool using ripgrep (auto-installed if missing, grep as last resort)."""

from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox


def _build_rg_cmd(
    regex: str,
    path: str,
    file_pattern: str | None,
    context_lines: int,
) -> list[str]:
    """Build a ripgrep command."""
    cmd = ["rg", "--line-number", "--color=never"]
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    if file_pattern:
        cmd.extend(["--glob", file_pattern])
    cmd.extend([regex, path])
    return cmd


def _build_grep_cmd(
    regex: str,
    path: str,
    file_pattern: str | None,
    context_lines: int,
) -> list[str]:
    """Build a grep fallback command."""
    cmd = ["grep", "-rn", "--color=never"]
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    if file_pattern:
        cmd.extend(["--include", file_pattern])
    cmd.extend([regex, path])
    return cmd


def _is_command_not_found(result) -> bool:
    """Check whether the exec result indicates a missing binary."""
    if result.returncode == 127:
        return True
    stderr = (result.stderr or "").lower()
    return "not found" in stderr or "no such file" in stderr


def _format_output(output: str, regex: str, path: str) -> str:
    """Truncate and return search output, or report no matches."""
    output = output.strip()
    if not output:
        return f"No matches found for pattern '{regex}' in {path}"
    max_length = 50000
    if len(output) > max_length:
        output = output[:max_length] + "\n\n... (output truncated)"
    return output


# Shell one-liner that tries common package managers to install ripgrep.
# Runs entirely with ||, so it short-circuits on the first success.
_INSTALL_RG_SCRIPT = (
    "(apt-get update -qq && apt-get install -y -qq ripgrep && rm -rf /var/lib/apt/lists/*) 2>/dev/null"
    " || (apk add --quiet ripgrep) 2>/dev/null"
    " || (dnf install -y -q ripgrep && rm -rf /var/cache/dnf/*) 2>/dev/null"
    " || (yum install -y -q ripgrep && rm -rf /var/cache/yum/*) 2>/dev/null"
    " || (pacman -Sy --noconfirm ripgrep && rm -rf /var/cache/pacman/pkg/*) 2>/dev/null"
    " || exit 1"
)


@tool
def search_files():
    """Search for patterns in files using ripgrep with context lines."""

    # Track whether we've already ensured rg is available in this session
    # so we don't re-run the install check on every invocation.
    _rg_available: dict[str, bool] = {"checked": False, "ok": False}

    async def _ensure_rg(sb) -> bool:
        """Ensure ripgrep is available, installing it if necessary.

        Returns True if rg is usable, False otherwise.
        """
        if _rg_available["checked"]:
            return _rg_available["ok"]

        check = await sb.exec(["rg", "--version"], timeout=10)
        if check.success:
            _rg_available.update(checked=True, ok=True)
            return True

        # Not present — try to install
        install = await sb.exec(
            ["bash", "-c", _INSTALL_RG_SCRIPT], timeout=120
        )
        if install.success:
            _rg_available.update(checked=True, ok=True)
            return True

        _rg_available.update(checked=True, ok=False)
        return False

    async def execute(
        path: str,
        regex: str,
        file_pattern: str | None = None,
        context_lines: int = 2,
    ) -> str:
        """Search for a regex pattern in files using ripgrep.

        If ripgrep is not installed in the container it is auto-installed.
        Falls back to grep only if installation is not possible.

        Args:
            path (str): Directory to search in (e.g., /app/repo, /app/repo/src).
            regex (str): Regular expression pattern to search for.
            file_pattern (str): Optional file glob pattern (e.g., *.py, *.ts). Defaults to None.
            context_lines (int): Number of context lines before/after matches. Defaults to 2.

        Returns:
            Search results with file paths, line numbers, and matching content.
        """
        if not path:
            raise ToolError("Path is required")
        if not regex:
            raise ToolError("Regex pattern is required")

        sb = sandbox()

        if await _ensure_rg(sb):
            # ripgrep is available (was already there, or we just installed it)
            rg_cmd = _build_rg_cmd(regex, path, file_pattern, context_lines)
            result = await sb.exec(rg_cmd, timeout=60)
        else:
            # rg install failed — fall back to grep
            grep_cmd = _build_grep_cmd(regex, path, file_pattern, context_lines)
            result = await sb.exec(grep_cmd, timeout=60)

            if _is_command_not_found(result):
                raise ToolError(
                    "Neither 'rg' (ripgrep) nor 'grep' is available in "
                    "the container, and ripgrep installation failed."
                )

        if result.success:
            return _format_output(result.stdout, regex, path)

        # Both rg and grep return exit code 1 for "no matches" — not an error.
        if result.returncode == 1:
            return f"No matches found for pattern '{regex}' in {path}"

        error_msg = result.stderr.strip() if result.stderr else "Unknown error"
        raise ToolError(f"Search failed: {error_msg}")

    return execute

