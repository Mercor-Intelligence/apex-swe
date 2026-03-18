# APEX SWE Harness

A production-ready framework for evaluating AI models on software engineering tasks in isolated Docker environments.

## Features

- **Docker Isolation**: Tasks run in secure, reproducible containers
- **Multi-Model Support**: 26+ production AI models from top providers (Anthropic, OpenAI, Google, xAI, Meta, DeepSeek, Qwen, Kimi)
- **Parallel Execution**: Run multiple tasks simultaneously
- **Comprehensive Logging**: Detailed episode-by-episode execution logs
- **MCP Integration**: Built-in support for Model Context Protocol servers

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (running)
- 8GB RAM minimum (16GB recommended)
- Valid API keys for your chosen AI provider

### Installation

```bash
cd integration
./install.sh

# Or install manually
source venv/bin/activate
pip install -e .
```

**Key Dependencies:**
- `litellm` - Multi-provider LLM interface
- `docker` - Container management
- `typer` & `rich` - CLI interface
- `pydantic` - Data validation
- `pyyaml` - Task configuration parsing
- `tenacity` - Retry logic
- `boto3` - AWS integration

**Development Dependencies:**
```bash
pip install -e ".[dev]"  # Includes pytest, black, ruff, mypy
```

### Basic Usage

```bash
# Set your API key
export ANTHROPIC_API_KEY='your-key-here'

# Run an evaluation
apx run my-experiment \
  --tasks 1-aws-s3-snapshots \
  --models claude-sonnet-4-20250514 \
  --n-trials 3 \
  --timeout 1800
```

### List Available Resources

```bash
# List all available tasks
apx list-tasks

# List all supported models
apx list-models
```

## Supported Models

### Anthropic Claude
- `claude-opus-4-1-20250805`
- `claude-opus-4-20250514`
- `claude-opus-4-5-20251101`
- `claude-opus-4-6`
- `claude-sonnet-4-20250514`
- `claude-sonnet-4-5-20250929`
- `claude-sonnet-4-6`

### OpenAI
- `gpt-4o`
- `gpt-5`
- `gpt-5-codex`
- `gpt-5.1-codex`
- `gpt-5.2-codex`
- `gpt-5.3-codex`
- `gpt-5.4-codex`

### Google
- `gemini/gemini-2.5-pro`
- `gemini/gemini-2.5-flash`
- `gemini/gemini-3-pro-preview`
- `gemini/gemini-3.1-pro`
- `gemini/gemini-3.1-flash`

### xAI
- `xai/grok-4`
- `xai/grok-4.1`
- `xai/grok-code-fast-1`

### Meta
- `meta_llama/Llama-4-Maverick-17B-128E-Instruct-FP8`

### DeepSeek / Qwen / Kimi (via Fireworks AI)
- `fireworks_ai/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct`
- `fireworks_ai/accounts/fireworks/models/deepseek-v3p2`
- `fireworks_ai/accounts/fireworks/models/kimi-k2-thinking`

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

### MCP (Model Context Protocol) Integration

The harness automatically integrates with MCP servers for specific services. Supported services include:
- Zammad
- Mattermost
- Plane API
- Grafana
- Prometheus
- EspoCRM
- Medusa

These are configured in `src/config.py` under `SERVICES_WITH_MCP`.

### Command Options

```bash
apx run EXPERIMENT_ID [OPTIONS]

Options:
  --tasks, -t TEXT              Task ID to run [required]
  --models, -m TEXT             Model to use [default: claude-sonnet-4-20250514]
  --n-trials, -n INTEGER        Number of trials to run [default: 3]
  --timeout INTEGER             Timeout per trial in seconds [default: 900]
  --max-workers, -w INTEGER     Max parallel trials [default: 4]
  --max-steps INTEGER           Maximum steps per trial
  --todo-tool-enabled           Enable todo tool
  --runs-dir, -r PATH           Results directory [default: runs]
  --tasks-dir, -d PATH          Tasks directory [default: tasks]
```

**Note:** Each run executes a single task with a single model. The `--max-workers` option controls how many trials run in parallel (e.g., with `--n-trials 3 --max-workers 4`, all 3 trials run simultaneously).

## Project Structure

```
integration/
├── install.sh                # One-command installation script
├── pyproject.toml            # Package configuration & dependencies
├── LICENSE                   # MIT License
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
│   │   ├── llm.py            # LLM interface
│   │   ├── docker_manager.py # Docker environment management
│   │   ├── terminal_manager.py   # Terminal session handling
│   │   ├── prompt_utils.py   # Prompt generation utilities
│   │   ├── harness_utils.py  # Harness helper functions
│   │   └── logging_utils.py  # Logging system
│   └── tools/                # Agent tools
│       ├── tool.py           # Base tool interface
│       ├── tool_executor.py  # Tool execution orchestration
│       ├── file_tool.py      # File operations
│       ├── terminal_tool.py  # Terminal commands
│       └── todo_tool.py      # Todo management
├── tasks/                    # Task definitions (25 OS tasks + shared resources)
└── runs/                     # Evaluation results (created at runtime)
```

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

## Example Workflow

```bash
# 1. Set API key
export ANTHROPIC_API_KEY='your-key'

# 2. List available tasks
apx list-tasks

# 3. Run evaluation (3 parallel trials of one task)
apx run my-eval \
  --tasks 1-aws-s3-snapshots \
  --models claude-sonnet-4-20250514 \
  --n-trials 3 \
  --timeout 1800

# 4. View results
cat runs/experiment_my-eval/results.json
```

## Advanced Usage

### High Parallelism (More Trials)

```bash
# Run 10 trials with 8 running in parallel
apx run stress-test \
  --tasks 1-aws-s3-snapshots \
  --models claude-sonnet-4-20250514 \
  --n-trials 10 \
  --max-workers 8
```

### Custom Timeouts

```bash
apx run fast-eval \
  --tasks simple-task \
  --models claude-sonnet-4-20250514 \
  --timeout 600
```

### With Todo Tool

```bash
apx run with-todos \
  --tasks complex-task \
  --models claude-sonnet-4-20250514 \
  --todo-tool-enabled
```

## Development

### Testing

The project is configured with `pytest` (see `pytest.ini`). Test infrastructure is ready but tests are not yet implemented.

```bash
# Install development dependencies
pip install -e ".[dev]"

# When tests are available, run with:
pytest
```

### Code Quality

The project uses:
- **Black** - Code formatting (line length: 100)
- **Ruff** - Linting (pycodestyle, pyflakes, isort, etc.)
- **MyPy** - Type checking

```bash
# Format code
black src/

# Run linter
ruff check src/

# Type checking
mypy src/
```

## Troubleshooting

### Docker Not Running
```bash
# Check Docker status
docker ps

# Start Docker if needed
sudo systemctl start docker
```

### API Key Issues
```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Test API key with LiteLLM
python3 -c "import litellm; print(litellm.completion(model='claude-sonnet-4-20250514', messages=[{'role': 'user', 'content': 'test'}]))"
```

### Missing Tasks
```bash
# Ensure tasks directory exists and has proper structure
ls -la tasks/

# Each task should have:
# - task.yaml
# - Dockerfile (optional)
# - docker-compose.yaml (optional)
```

## Contributing

This is a production-ready evaluation framework. When contributing:

1. Maintain the minimal, clean structure
2. All code must be actively used (no dead code)
3. Follow existing code patterns and style (Black formatting, line length 100)
4. Update this README for user-facing changes
5. Consider adding type hints (mypy compatibility)
6. Test your changes thoroughly before submitting

## License

MIT License - See LICENSE file for details

## Support

For issues and questions, please open a GitHub issue.
