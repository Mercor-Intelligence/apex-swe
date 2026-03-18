# APEX SWE Harness — Integration

A production-ready framework for evaluating AI models on software engineering tasks in isolated Docker environments.

## Overview

- **Docker Isolation**: Tasks run in secure, reproducible containers
- **Multi-Model Support**: 26+ production AI models from top providers (Anthropic, OpenAI, Google, xAI, Meta, DeepSeek, Qwen, Kimi)
- **Parallel Execution**: Run multiple tasks simultaneously
- **Comprehensive Logging**: Detailed episode-by-episode execution logs
- **MCP Integration**: Built-in support for Model Context Protocol servers
- **Custom Task Directories**: Point to any task folder with `--tasks-dir`

---

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (running)
- 8GB RAM minimum (16GB recommended)
- Valid API keys for your chosen AI provider
- Task definitions in a local folder

### Installation

```bash
cd integration
./install.sh
source venv/bin/activate
```

### Basic Usage

```bash
# Set your API key
export ANTHROPIC_API_KEY='your-key-here'

# Run an evaluation with tasks at a custom path
apx run my-experiment \
  --tasks 1-aws-s3-snapshots \
  --models claude-sonnet-4-20250514 \
  --n-trials 3 \
  --timeout 1800 \
  --tasks-dir <path-to-task>
```

### Parallel / Batch Usage

```bash
# High parallelism (more trials)
apx run stress-test \
  --tasks 1-aws-s3-snapshots \
  --models claude-sonnet-4-20250514 \
  --n-trials 10 \
  --max-workers 8 \
  --tasks-dir <path-to-task>

# With reasoning effort
apx run reasoning-test \
  --tasks 1-aws-s3-snapshots \
  --models gpt-5.4 \
  --reasoning-effort high \
  --n-trials 1 \
  --tasks-dir <path-to-task>
```

### List Available Resources

```bash
# List all available tasks
apx list-tasks --tasks-dir <path-to-task>

# List all supported models
apx list-models
```

---

## Supported Models

| Short Name (use with `--models`) | Provider |
|---------------------------------|----------|
| `claude-opus-4-6` | Anthropic |
| `claude-opus-4-5-20251101` | Anthropic |
| `claude-opus-4-1-20250805` | Anthropic |
| `claude-opus-4-20250514` | Anthropic |
| `claude-sonnet-4-5-20250929` | Anthropic |
| `claude-sonnet-4-20250514` | Anthropic |
| `claude-sonnet-4-6` | Anthropic |
| `gpt-4o` | OpenAI |
| `gpt-5` | OpenAI |
| `gpt-5-codex` | OpenAI |
| `gpt-5.1-codex` | OpenAI |
| `gpt-5.2` / `gpt-5.2-codex` | OpenAI |
| `gpt-5.3` / `gpt-5.3-codex` | OpenAI |
| `gpt-5.4` | OpenAI |
| `gemini/gemini-2.5-pro` | Google |
| `gemini/gemini-2.5-flash` | Google |
| `gemini/gemini-3-pro-preview` | Google |
| `gemini/gemini-3.1-pro-preview` | Google |
| `gemini/gemini-3.1-flash` | Google |
| `xai/grok-4` | xAI |
| `xai/grok-4.1` | xAI |
| `xai/grok-code-fast-1` | xAI |
| `meta_llama/Llama-4-Maverick-17B-128E-Instruct-FP8` | Meta |
| `fireworks_ai/.../qwen3-coder-480b-a35b-instruct` | Fireworks |
| `fireworks_ai/.../deepseek-v3p2` | Fireworks |
| `fireworks_ai/.../kimi-k2-thinking` | Fireworks |
| `fireworks_ai/.../kimi-k2p5` | Fireworks |

---

## Configuration

### API Keys

Set the appropriate environment variable for your chosen model:

```bash
export ANTHROPIC_API_KEY='sk-ant-...'     # For Claude models
export OPENAI_API_KEY='sk-...'            # For GPT models
export GOOGLE_API_KEY='...'               # For Gemini models
export XAI_API_KEY='...'                  # For Grok models
export FIREWORKS_API_KEY='...'            # For DeepSeek/Qwen/Kimi
export LLAMA_API_KEY='...'                # For Llama models
```

### CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--tasks, -t` | Task ID to run | (required) |
| `--models, -m` | Model to use | `claude-sonnet-4-20250514` |
| `--n-trials, -n` | Number of trials to run | `3` |
| `--timeout` | Timeout per trial in seconds | `900` |
| `--max-workers, -w` | Max parallel trials | `4` |
| `--max-steps` | Maximum steps per trial | — |
| `--reasoning-effort` | Reasoning effort (`low`, `medium`, `high`) | Auto per model |
| `--runs-dir, -r` | Results directory | `runs` |
| `--tasks-dir, -d` | Tasks directory | `tasks` |

**Note:** Each run executes a single task with a single model. The `--max-workers` option controls how many trials run in parallel (e.g., with `--n-trials 3 --max-workers 4`, all 3 trials run simultaneously).

### MCP (Model Context Protocol) Integration

The harness automatically integrates with MCP servers for specific services. Supported services include:
- Zammad
- Mattermost
- Plane API
- Grafana
- Prometheus
- EspoCRM
- Medusa

These are configured in `src/config/__init__.py` under `SERVICES_WITH_MCP`.

---

## Architecture

### Project Structure

```
integration/
├── install.sh                # One-command installation script
├── pyproject.toml            # Package configuration & dependencies
├── README.md                 # This file
├── src/                      # Source code
│   ├── main.py               # CLI entry point
│   ├── config/               # Global configuration
│   ├── harness/              # Core evaluation engine
│   │   ├── executor.py       # Orchestrates evaluations
│   │   ├── multi_step_runner.py  # Agent interaction loop
│   │   ├── evaluator.py      # Test execution & validation
│   │   └── data_models.py    # Data structures
│   ├── utils/                # Core utilities
│   │   ├── llm.py            # LLM interface (provider-aware reasoning)
│   │   ├── docker_manager.py # Docker environment management
│   │   ├── terminal_manager.py   # Terminal session handling
│   │   ├── prompt_utils.py   # Prompt generation utilities
│   │   ├── harness_utils.py  # Harness helper functions
│   │   └── logging_utils.py  # Logging system
│   └── tools/                # Agent tools
│       ├── tool.py           # Base tool interface
│       ├── tool_executor.py  # Tool execution orchestration
│       ├── file_tool.py      # File operations
│       └── terminal_tool.py  # Terminal commands
├── tasks/
│   └── shared/               # Shared resources (Dockerfiles, MCP configs, entrypoints)
└── runs/                     # Evaluation results (created at runtime)
```

---

## Results

Results are saved to `runs/experiment_<EXPERIMENT_ID>/`:

```
runs/experiment_my-experiment/
├── metadata.json                # Experiment configuration
├── results.json                 # Detailed results with all trials
└── <task-id>/
    └── <task-id>.1-of-1.<timestamp>/
        ├── agent-logs/
        │   ├── episode-0/       # Initial prompt
        │   │   ├── prompt.txt
        │   │   ├── response.json
        │   │   └── debug.json
        │   ├── episode-1/       # First agent turn
        │   │   ├── prompt.txt
        │   │   ├── response.json
        │   │   └── debug.json
        │   └── ...
        ├── panes/               # Terminal pane captures
        │   ├── pre-test.txt
        │   └── post-test.txt
        ├── sessions/            # Terminal session logs
        ├── commands.txt         # Command history
        └── test_results.json    # Test execution results
```

---

## Troubleshooting

### Docker Not Running
```bash
docker ps
sudo systemctl start docker  # if needed
```

### API Key Issues
```bash
echo $ANTHROPIC_API_KEY
python3 -c "import litellm; print(litellm.completion(model='claude-sonnet-4-20250514', messages=[{'role': 'user', 'content': 'test'}]))"
```

### Missing Tasks
```bash
# Verify your tasks directory has the expected structure
ls -la <path-to-task>/

# Each task folder should have:
# - task.yaml
# - Dockerfile (optional)
# - docker-compose.yaml (optional)
```
