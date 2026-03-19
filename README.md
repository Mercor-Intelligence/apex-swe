# APEX-SWE Harness

Evaluation harness for the AI Productivity Index for Software Engineering (APEX-SWE) benchmark.

## What is APEX-SWE?

APEX-SWE is a benchmark for assessing whether frontier AI models can execute economically valuable software engineering work. Unlike existing evaluations that focus on narrow, well-defined tasks, APEX-SWE assesses two novel task types that reflect real-world software engineering:

- **Integration tasks** — Require constructing end-to-end systems across heterogeneous cloud primitives, business applications, and infrastructure-as-code services.
- **Observability tasks** — Require debugging production failures using telemetry signals such as logs and dashboards, as well as unstructured context.

This repository contains the open-source evaluation harness and a dev set (n=50).

## Prerequisites

- Python 3.10+ (3.12 recommended)
- Docker (running)
- API keys for your chosen LLM provider

## Harnesses

Each harness has its own setup and entry point. Follow the guide for the task type you want to run.

### Integration Harness

Tasks run in Docker containers with MCP (Model Context Protocol) tools for terminal access and file operations.

```bash
# Install (creates venv at repo root, installs the apx CLI)
./install.sh

# Activate and run
source venv/bin/activate
cd integration
apx run my-experiment --tasks task-id --models claude-sonnet-4-20250514 --n-trials 3
```

See [integration/README.md](integration/README.md) for full setup, CLI reference, and task authoring.

### Observability Harness

Tasks include access to observability tools (Loki, Grafana, Prometheus) alongside source code repositories.

```bash
cd observability

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set up API keys
cp env.example .env
# Edit .env with your API keys

# Run a single task
python run_e2e.py --task task-id --model claude-opus-4-5

# Run all tasks in parallel
python run_e2e.py --all --model claude-opus-4-5 --parallel 4
```

See [observability/README.md](observability/README.md) for full setup, scoring system, and framework support.

## API Keys

Set the keys for your provider(s):

```bash
export ANTHROPIC_API_KEY='sk-ant-...'   # Claude models
export OPENAI_API_KEY='sk-...'          # GPT models
export GOOGLE_API_KEY='...'             # Gemini models
export XAI_API_KEY='...'                # Grok models
export FIREWORKS_API_KEY='...'          # DeepSeek, Qwen, Kimi
```

## Supported Models

| Provider | Models |
|----------|--------|
| Anthropic | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.6, Claude Sonnet 4.5 |
| OpenAI | GPT-5.4 Codex, GPT-5.3 Codex, GPT-5.2 Codex, GPT-5.1 Codex |
| Google | Gemini 3.1 Pro, Gemini 3.1 Flash, Gemini 3 Pro, Gemini 2.5 Pro |
| xAI | Grok 4.1, Grok 4 |
| Fireworks | DeepSeek V3, Qwen3 Coder, Kimi K2.5, Kimi K2 |
| Cognition | SWE-1.5 (observability only) |


## Project Structure

```
apex-swe/
├── install.sh              # Integration harness installer
├── integration/            # Integration evaluation harness
│   ├── src/                # Harness source code
│   ├── tasks/              # Task definitions
│   └── README.md
├── observability/          # Observability evaluation harness
│   ├── run_e2e.py          # Entry point (single/parallel)
│   ├── eval_runner/        # Evaluation orchestration
│   ├── parser/             # Test output parsing
│   ├── agent/              # Inspect AI agent
│   ├── tasks/              # Observability tasks
│   └── README.md
└── README.md               # This file
```

## Results

Both harnesses output structured JSON results with:

- Pass/fail status for each trial
- Test metrics (F2P, P2P for observability)
- Timing information (agent duration, total time)
- Detailed logs (agent turns, terminal output, tool calls)

## License

MIT License — See [LICENSE](LICENSE) file for details.
