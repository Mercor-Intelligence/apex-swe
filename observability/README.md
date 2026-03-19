# ApexCode Observability - E2E Evaluation

End-to-end evaluation system for AI coding agents on observability tasks.

## Overview

This system evaluates AI coding agents on software engineering tasks that require:
- Debugging issues using observability tools (Loki, Grafana, Prometheus)
- MCP server integrations (Plane, Mattermost)
- Source code debugging and test validation

---

## Quick Start

### Prerequisites

- Python 3.10+ (3.12 recommended)
- Docker (for running tests in containers)
- API keys for LLM providers (Anthropic, OpenAI, etc.)

### Installation

```bash
# Navigate to observability directory
cd observability

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp env.example .env
# Edit .env with your API keys
```

Add a `.dockerignore` file in `tasks/` with the following contents:

```
# Exclude local node_modules from Docker builds
**/node_modules

# Exclude local build artifacts
**/dist
**/build

# Exclude development artifacts
**/.git
**/.DS_Store
**/*.log
**/.env
**/.env.local
**/coverage
**/.nyc_output
**/.cache
**/*.tsbuildinfo
```

### Running E2E Evaluations

#### Single Task

```bash
# Run a single task with a specific model
python run_e2e.py --task crankyoldgit-irremoteesp8266-1733-1734-observability --model claude-opus-4-5

# Run with verbose output
python run_e2e.py --task <task_id> --model claude-opus-4-5 --verbose

# Run agent only (skip scoring)
python run_e2e.py --task <task_id> --model claude-opus-4-5 --agent-only

# Save results to file
python run_e2e.py --task <task_id> --model claude-opus-4-5 --output results.json
```

#### Multiple Tasks in Parallel

```bash
# Run all tasks with 4 parallel workers
python run_e2e.py --all --model claude-opus-4-5 --parallel 4

# Run specific tasks in parallel
python run_e2e.py --tasks task1 task2 task3 --model claude-opus-4-5 --parallel 4

# Run tasks from a file
python run_e2e.py --tasks-file tasks.txt --model claude-opus-4-5 --parallel 6

# Run multiple trials per task
python run_e2e.py --all --model claude-opus-4-5 --trials 3 --parallel 4

# Resume interrupted run
python run_e2e.py --all --model claude-opus-4-5 --output results/ --resume

# With custom limits
python run_e2e.py \
  --task my-task \
  --model claude-opus-4-5 \
  --time-limit 3600 \
  --message-limit 300
```

---

## Architecture

```
  run_e2e.py ──► eval_runner/runner.py
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
 [Phase 1: Agent]              [Phase 2: Scoring]
 run_agent_sync()              unified_scorer()
       │                               │
       ▼                               ▼
 Inspect AI Task               In-sandbox testing
       │                               │
       ├── Agent executes              ├── Apply test patch
       │   (makes code changes)        ├── Run test command
       │                               ├── Parse results
       └── Diff captured               └── Compare F2P/P2P
                │
                ▼
       get_f2p_for_task()
       (F2P cache lookup)
```

Both phases run inside the same inspect-ai evaluation. The agent modifies code in the Docker sandbox, then `unified_scorer()` runs the tests and scores the result — all within one `inspect_eval()` call.

---

## Directory Structure

```
observability/
├── run_e2e.py                    # E2E evaluation runner (single/parallel)
│
├── eval_runner/                  # Evaluation orchestration
│   ├── config.py                 # Models, paths, F2P cache, defaults
│   ├── runner.py                 # Agent execution via Inspect
│   ├── inspect_scorer.py         # Inspect sandbox scoring
│   ├── logger.py                 # Logging utilities
│   └── retry_utils.py            # Retry logic
│
├── parser/                       # Test output parsing
│   ├── evaluator.py              # TaskEvaluator (F2P/P2P generation)
│   ├── docker_runner.py          # Docker execution
│   ├── parsing_utils.py          # 20+ framework parsers
│   ├── frameworks.py             # Framework configurations
│   └── eval_utils.py             # Evaluation utilities
│
├── agent/                        # Inspect AI agent
│   ├── prompts/                  # System prompts
│   └── tools/                    # Agent tools (apply_patch, read_file, search_files, update_plan)
│
├── tasks/                        # Task definitions
│   ├── <task_id>/
│   │   ├── compose.yaml          # Docker Compose stack
│   │   ├── Dockerfile            # Task container
│   │   ├── task.yaml             # Task metadata
│   │   ├── test_metadata.json    # Test command, framework
│   │   ├── problem_statement.md  # Task description
│   │   ├── golden.patch          # Solution patch
│   │   ├── test.patch            # Test modifications
│   │   ├── repo/                 # Source code
│   │   └── data/                 # MCP server data
│   └── shared/                   # Shared resources
│       ├── dockerfiles/          # Base images
│       ├── mcp-servers/          # MCP server code
│       └── config/               # Shared configs
│
├── f2p_cache/                    # F2P/P2P cache
│   └── <task_id>.json
│
├── requirements.txt              # Python dependencies
├── pyproject.toml                # Package configuration
├── env.example                   # Environment template
└── README.md                     # This document
```

---

## Available Models

| Short Name (use with `--model`) | Provider | Full Model |
|---------------------------------|----------|------------|
| `claude-opus-4-6` | Anthropic | claude-opus-4-6 |
| `claude-opus-4-5` (default) | Anthropic | claude-opus-4-5-20251101 |
| `claude-sonnet-4-5` | Anthropic | claude-sonnet-4-5-20250929 |
| `gpt-5.1-codex` | OpenAI | gpt-5.1-codex |
| `gpt-5.2-codex` | OpenAI | gpt-5.2-codex |
| `gemini-3-pro` | Google | gemini-3-pro-preview |
| `grok-4` | xAI | grok-4 |
| `kimi-k2` | Fireworks | kimi-k2-instruct-0905 |
| `kimi-k2p5` | Fireworks | kimi-k2p5 |
| `qwen3-coder` | Fireworks | qwen3-coder-480b-a35b-instruct |
| `deepseek-v3` | Fireworks | deepseek-v3-0324 |
| `cognition` | Cognition | swe-1.5 |

## Configuration

### Environment Variables

Create a `.env` file in the project root (see `env.example`):

```bash
# LLM API Keys (only needed for the models you plan to use)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
XAI_API_KEY=...
FIREWORKS_API_KEY=...       # Also used for DeepSeek, Kimi, Qwen
COGNITION_API_KEY=...
COGNITION_BASE_URL=...
```

### Internal Defaults

These are the defaults used when no CLI flag or environment variable override is provided:

| Setting | Default | Env Var Override |
|---------|---------|------------------|
| Agent time limit | 3600s (1 hr) | `EVAL_TIME_LIMIT` |
| Message limit | 250 | `EVAL_MESSAGE_LIMIT` |
| Test execution timeout | 900s (15 min) | `EVAL_TEST_TIMEOUT` |

### CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--task` | Single task ID to evaluate | - |
| `--tasks` | Multiple task IDs to evaluate | - |
| `--tasks-file` | File with task IDs (one per line) | - |
| `--all` | Run all available tasks | - |
| `--model` | Model to use | `claude-opus-4-5` |
| `--trial` | Trial number (single mode) | `1` |
| `--trials` | Trials per task (parallel mode) | `1` |
| `--time-limit` | Time limit in seconds | `3600` |
| `--message-limit` | Message limit for agent | `250` |
| `--max-retries` | Retries for transient failures | `2` |
| `--run-timeout` | Per-run timeout in seconds (parallel mode) | None |
| `--parallel` | Number of parallel workers | `1` |
| `--verbose` | Verbose output | `False` |
| `--debug` | Debug output (more verbose) | `False` |
| `--output` | Output file/directory | None |
| `--agent-only` | Only run agent, skip scoring | `False` |
| `--skip-health-check` | Skip pre-flight checks | `False` |
| `--resume` | Resume from previous run | `False` |

---

## Python API

### Full Evaluation (Agent + Scoring)

```python
from eval_runner import run_evaluation_sync, get_all_task_ids, MODELS

# List available tasks and models
tasks = get_all_task_ids()
print(f"Available tasks: {len(tasks)}")
print(f"Available models: {list(MODELS.keys())}")

# Run single evaluation
result = run_evaluation_sync(
    task_id="0xpolygon-bor-1710-observability",
    model="claude-opus-4-5",
    trial=1,
    time_limit=3600,
    message_limit=250,
    verbose=True,
)

print(f"Agent success: {result.agent_success}")
print(f"Passed: {result.passed}")
print(f"F2P: {result.f2p_passed}/{result.f2p_total}")
print(f"P2P: {result.p2p_passed}/{result.p2p_total}")
```

### Direct Parser Usage (F2P/P2P Generation)

The parser module can be used independently to generate F2P/P2P test lists:

```python
from parser import TaskEvaluator, TaskConfig

# Create configuration manually
config = TaskConfig(
    task_id="my-task",
    docker_image="my-task-default:latest",
    test_command="pytest tests/",
    test_framework="pytest",
    test_patch=open("test.patch").read(),
    golden_patch=open("golden.patch").read(),
    timeout=600,
    workdir="/app/repo",
)

evaluator = TaskEvaluator(verbose=True)

# Generate F2P/P2P lists from golden patch
f2p_result = evaluator.generate_f2p_p2p(config)
print(f"F2P: {f2p_result.fail_to_pass}")
print(f"P2P: {f2p_result.pass_to_pass}")
```

Or load directly from a task directory:

```python
from parser import TaskEvaluator, TaskConfig

config = TaskConfig.from_task_dir("tasks/my-task", "my-image:latest")

evaluator = TaskEvaluator(verbose=True)
f2p_result = evaluator.generate_f2p_p2p(config)
```

---

## F2P/P2P Scoring

### What is F2P/P2P?

- **F2P (Fail-to-Pass)**: Tests that FAIL in baseline but PASS after applying the golden patch
- **P2P (Pass-to-Pass)**: Tests that PASS in both baseline and after golden patch

### How F2P/P2P Lists Are Generated

1. **Pre-patch tests**: Run tests with only `test.patch` applied (baseline)
2. **Post-patch tests**: Run tests with `test.patch` + `golden.patch` applied
3. **Compute F2P**: Tests that FAILED in pre but PASSED in post (+ new passing tests)
4. **Compute P2P**: Tests that PASSED in both pre and post

### How Agent Scoring Works

1. Agent's diff is applied inside the Docker sandbox
2. Test patch is applied (resets test files to known state)
3. Test command runs
4. Output is parsed by the appropriate framework parser
5. Results are compared against F2P/P2P:
   - All F2P tests must PASS (the agent fixed the bug)
   - All P2P tests must PASS (the agent didn't break anything)

### F2P Cache

The F2P cache ensures consistent and efficient scoring across runs.

- **First evaluation**: F2P/P2P is computed by running tests with/without golden patch
- **Cache stored**: Results saved to `f2p_cache/<task_id>.json`
- **Subsequent runs**: Cache is loaded instantly, no recomputation needed

The cache includes a hash of the golden patch. If `golden.patch` changes, regenerate:

```bash
rm f2p_cache/<task_id>.json
```

---

## Supported Test Frameworks

The parser supports 20+ test frameworks:

| Framework | Language | Output Format |
|-----------|----------|---------------|
| pytest | Python | JUnit XML |
| unittest | Python | JUnit XML |
| jest | JavaScript | JSON |
| vitest | JavaScript | JSON |
| mocha | JavaScript | JSON |
| bun | JavaScript | Text |
| go test | Go | JSON |
| cargo-nextest | Rust | JUnit XML |
| gtest | C++ | JSON/Console |
| junit/maven | Java | XML |
| gradle | Java/Kotlin | XML |
| ctest | C/C++ | JUnit XML |
| xctest | Swift | JUnit XML |
| busted | Lua | JUnit XML |
| luaunit | Lua | JUnit XML |
| tap | Various | TAP format |
| unity | C | Text |
| bespoke | Various | Custom |

---

## Output Format

Results are saved as JSON with the following structure:

```json
{
  "task_id": "task-name-observability",
  "model": "claude-opus-4-5",
  "trial": 1,
  "passed": true,
  "f2p_passed": 5,
  "f2p_total": 5,
  "p2p_passed": 10,
  "p2p_total": 10,
  "test_exit_code": 0,
  "agent_duration": 120.5,
  "scoring_duration": 30.2,
  "total_duration": 150.7
}
```

For parallel runs, results are aggregated in `results/results.json`:

```json
{
  "generated_at": "2026-01-22T12:00:00",
  "model": "claude-opus-4-5",
  "total_runs": 25,
  "passed_count": 18,
  "pass_rate": 0.72,
  "results": [...]
}
```

---

## Troubleshooting

### For x86_64 systems

```bash
# Build the plane-api image for x86_64 [NOTE THIS STEP IS IMPORTANT FOR x86_64 systems]
cd tasks/
docker build -f shared/dockerfiles/Dockerfile.plane-lightweight -t plane-api-x86:latest .
```

### Docker Image Not Found

```bash
# Check if image exists
docker images | grep <task_id>

# Build image if needed (compose.yaml handles this)
cd tasks/<task_id>
docker compose build
```

### Task Not Found

```bash
# List available tasks via Python
python -c "
from eval_runner import get_all_task_ids
for t in sorted(get_all_task_ids()): print(t)
"

# Check task directory exists
ls tasks/<task_id>/
```

### Scoring Fails

```bash
# Run with verbose/debug output
python run_e2e.py --task <task_id> --model claude-opus-4-5 --debug

# Check test_metadata.json
cat tasks/<task_id>/test_metadata.json

# Check if F2P cache exists
cat f2p_cache/<task_id>.json
```
