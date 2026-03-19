"""Agent package for Inspect AI evaluations.

This package provides:
- prompts: System prompts for the observability agent  
- tools: Agent tools (apply_patch, read_file, search_files, update_plan)

Usage (recommended - lazy imports):
    from agent.prompts.system_prompt import build_observability_prompt
    from agent.tools.apply_patch import apply_patch
    from agent.tools.read_file import read_file
    from agent.tools.search_files import search_files
    from agent.tools.update_plan import update_plan
"""

# Note: We don't eagerly import tools here because they depend on inspect_ai
# which may not be installed. Use direct imports from submodules instead.

__all__ = [
    "prompts",
    "tools",
]

