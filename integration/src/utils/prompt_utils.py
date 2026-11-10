from pathlib import Path

from src.harness.data_models import TaskContext
from src.tools import ToolExecutor


def build_initial_prompt(
    task_context: TaskContext,
    working_dir: Path,
    tool_executor: ToolExecutor,
    max_timeout: float,
) -> str:
    todo_tool_enabled = tool_executor.has_tool("todo")
    base_prompt = """You are an AI assistant tasked with solving command-line tasks in a Linux environment. You will be given a task description and the output from previously executed commands. Your goal is to solve the task by providing batches of shell commands.

Format your response as XML with the following structure:

<response>
<analysis>
Analyze the current state based on the terminal output provided. What do you see? What has been accomplished? What still needs to be done?
</analysis>
<plan>
Describe your plan for the next steps. What commands will you run and why? Be specific about what you expect each command to accomplish.
</plan>
<commands>
<keystrokes duration="0.1">ls -la</keystrokes>
<keystrokes duration="0.1">cd /app && find . -name '*.py' | grep django</keystrokes>"""

    if todo_tool_enabled:
        base_prompt += """

<!-- Use tool_use blocks for the todo task list tool. The body is a JSON object. -->
<tool_use>
{"tool":"todo","action":"add","title":"Run the test suite","status":"todo"}
</tool_use>

<tool_use>
{"tool":"todo","action":"list"}
</tool_use>"""

    base_prompt += """
</commands>
<task_complete>false</task_complete>
</response>

Required sections:
- <analysis>: Your analysis of the current situation
- <plan>: Your plan for the next steps  
- <commands>: Commands to execute using keystrokes format

Optional sections:
- <task_complete>: Include this tag if the task is complete. Can be:
  - <task_complete>true</task_complete> (task complete)
  - <task_complete>false</task_complete> (task not complete)
  - If not present, task is assumed not complete

COMMAND FORMAT:
Use the keystrokes format to avoid JSON parsing issues:
<keystrokes duration="0.1">simple command here</keystrokes>

IMPORTANT: The text inside keystrokes tags is sent exactly as typed to the terminal.
- NO JSON escaping needed
- NO quote escaping needed  
- Write commands exactly as you would type them
- Use duration="0.1" for fast commands (ls, cd, grep)
- Use duration="1.0" for slower commands (find, python scripts)

⚠️⚠️⚠️ CRITICAL - FILE WRITING ⚠️⚠️⚠️
NEVER use heredoc syntax (cat << EOF, cat <<'EOF', cat >> file << EOF, etc.) as it WILL cause terminal hangs and timeouts!

ALWAYS use one of these methods instead:

1. Python (BEST - works for ANY content):
   python3 -c 'import sys; open("/path/to/file", "w").write(sys.argv[1])' 'your content here'
   
   For multi-line:
   python3 << 'PY'
   with open('/path/to/file', 'w') as f:
       f.write('''line1
   line2
   line3''')
   PY

2. printf for simple multi-line:
   printf '%s\n' 'line1' 'line2' 'line3' > /path/to/file

3. echo for single line:
   echo 'single line' > /path/to/file

4. tee for appending:
   echo 'new line' | tee -a /path/to/file

5. sed for inserting/replacing in existing files:
   sed -i 's/old/new/g' /path/to/file

DO NOT use: cat << EOF, cat <<'EOF', cat >> file << 'EOF', or any heredoc variant!

DEBUGGING & ADAPTIVE PROBLEM SOLVING:
When commands fail, reason through the problem systematically:

1. Understand the Environment:
   - Examine project structure and configuration files to understand the tooling
   - Check for dependency lock files, build configs, or package manifests
   - Identify which tools/runtimes are actually installed and available
   
2. Analyze Failures Intelligently:
   - Read error messages carefully - they often tell you exactly what's wrong
   - "command not found" → Tool might not be in PATH, or wrong tool is being used
   - Permission errors → Check file permissions or try different approach
   - Missing dependencies → Understand the project's dependency management system
   
3. Adapt Your Approach:
   - Don't just retry the same failing command repeatedly
   - If a provided command fails, investigate WHY and find the correct alternative
   - Look for evidence in the codebase: what tools does it actually use?
   - Try equivalent commands with different tools if one doesn't work
   - Test assumptions by exploring the environment before executing complex steps"""

    # Add todo tool sections only if enabled
    if todo_tool_enabled:
        base_prompt += """

WORKFLOW WITH TODO TOOL:
- For larger tasks, first break the work into 3-8 concise subtasks using the todo tool (prefer bulk_add). Keep titles action-oriented and specific.
- At the beginning of each response, list the current todos to re-anchor your plan and context:
  <tool_use>
  {"tool":"todo","action":"list"}
  </tool_use>
- Choose the next item, set it to "inprogress" before executing shell commands, and mark it "done" when finished. Add or adjust items as you discover new work.
- Keep referring to the todo list to track progress and avoid repeating steps.

TODO TOOL USAGE:
- Tool name: "todo". Actions: add, list, update_status, delete, bulk_add.
- Allowed statuses: todo, inprogress, done.
- All examples:
  <tool_use>
  {"tool":"todo","action":"add","title":"Set up repository","status":"todo"}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"list"}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"update_status","id":1,"status":"inprogress"}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"update_status","title":"Set up repository","status":"done"}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"delete","id":1}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"delete","title":"Set up repository"}
  </tool_use>
  <tool_use>
  {"tool":"todo","action":"bulk_add","tasks":[
    {"title":"Create virtualenv"},
    {"title":"Install dependencies","status":"inprogress"}
  ]}
  </tool_use>"""

    base_prompt += """

ENVIRONMENT:
- Working directory: /app (source code and task files location)

Task Description:
[[TASK_INSTRUCTION]]

Current terminal state:
Starting fresh - no previous commands executed"""

    return base_prompt.replace("[[TASK_INSTRUCTION]]", task_context.instruction)


def build_collaborative_prompt(
    task_context: "TaskContext",
    agent_id: int,
    working_dir: Path,
    tool_executor: "ToolExecutor",
    max_timeout: float,
) -> str:
    """Initial prompt for the collaborative multi-agent runner."""
    other_id = 1 - agent_id
    todo_tool_enabled = tool_executor.has_tool("todo")

    prompt = f"""You are Agent {agent_id + 1} of 2 working on a software engineering task.

Another agent is working alongside you in this same container. You share the entire filesystem — any file either of you creates or modifies is immediately visible to the other.

You are building ONE shared solution together. Coordinate with the other agent so your efforts are complementary, not duplicated. How you coordinate is entirely up to you.

When you both agree the solution is complete, create the file /app/READY_TO_SUBMIT to submit it. Both agents must reach consensus before creating this file. If either agent believes more work is needed after it has been created, delete it and continue working. You have one opportunity to submit.

━━━━ TOOLS ━━━━
Format your response as XML:

<response>
<analysis>
Analyse the current state based on terminal output and what you know so far.
</analysis>
<plan>
What you will do next and why.
</plan>
<commands>
<keystrokes duration="0.1">cd /app && ls</keystrokes>
</commands>
</response>

COMMAND FORMAT:
<keystrokes duration="0.1">command here</keystrokes>
- No JSON escaping — write commands exactly as you would type them
- duration="0.1" for fast commands (ls, cat, grep)
- duration="1.0" for slower commands (python scripts, builds)

⚠️ FILE WRITING: NEVER use heredoc syntax (cat << EOF). Use python3 or printf:
  python3 -c 'import sys; open("/path/file","w").write(sys.argv[1])' 'content here'
  printf '%s\\n' 'line1' 'line2' > /path/file

DEBUGGING: When commands fail, read the error and adapt. Do not retry identical failing commands.
"""

    if todo_tool_enabled:
        prompt += """
TODO TOOL:
<tool_use>
{"tool":"todo","action":"add","title":"My task","status":"todo"}
</tool_use>
<tool_use>
{"tool":"todo","action":"list"}
</tool_use>
"""

    prompt += f"""
ENVIRONMENT:
- Working directory: /app

Task Description:
{task_context.instruction}

Current terminal state:
Starting fresh - no previous commands executed"""

    return prompt


def build_collaborative_episode_prompt(
    step_num: int,
    initial_prompt: str,
    terminal_content: str,
    agent_id: int,
    todo_list_text: str | None = None,
) -> str:
    """Episode prompt for collaborative agents — terminal state and continuation."""
    if not terminal_content or not terminal_content.strip():
        return initial_prompt if step_num == 1 else "No terminal output available."

    todos_section = f"\n\nTODO LIST:\n{todo_list_text}" if todo_list_text else ""
    terminal_section = (
        f"CURRENT TERMINAL STATE:\n{terminal_content}{todos_section}\n\n"
        f"Continue with your next actions."
    )

    if step_num == 1:
        if "Note: You have a maximum" in initial_prompt:
            parts = initial_prompt.split("Note: You have a maximum")
            return parts[0] + terminal_section + "\n\nNote: You have a maximum" + parts[1]
        return initial_prompt + "\n\n" + terminal_section
    else:
        return terminal_section


def build_episode_prompt(
    step_num: int,
    initial_prompt: str,
    terminal_content: str,
    todo_list_text: str | None = None,
) -> str:
    """Build prompt for an episode - Episode 0 gets full template, others get only terminal output."""
    if not terminal_content or not terminal_content.strip():
        return initial_prompt if step_num == 1 else "No terminal output available."
    todos_section = (
        f"\n\nTODO LIST (auto-included):\n{todo_list_text}" if todo_list_text else ""
    )
    terminal_section = f"""CURRENT TERMINAL STATE:
{terminal_content}{todos_section}

Analyze the current terminal state above to understand what has been executed and what the current state is."""

    if step_num == 1:
        if "Note: You have a maximum" in initial_prompt:
            parts = initial_prompt.split("Note: You have a maximum")
            return (
                parts[0] + terminal_section + "\n\nNote: You have a maximum" + parts[1]
            )
        else:
            return initial_prompt + "\n\n" + terminal_section
    else:
        return terminal_section + " Continue with your next actions."
