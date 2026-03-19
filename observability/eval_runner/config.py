"""
Configuration for evaluation runner.

Contains model definitions, default settings, and task configurations.

Environment Variables:
    API keys can be set via environment variables OR via a .env file at the project root.
    The .env file is loaded automatically if it exists.
    
    Required (for the models you want to use):
        ANTHROPIC_API_KEY - For Claude models
        OPENAI_API_KEY - For GPT models
        GOOGLE_API_KEY - For Gemini models
        XAI_API_KEY - For Grok models
        FIREWORKS_API_KEY - For Kimi, Qwen, DeepSeek models
        COGNITION_API_KEY - For Cognition models (OpenAI-compatible endpoint)
        COGNITION_BASE_URL - Base URL for Cognition API endpoint
    
    Optional:
        DEFAULT_MODEL - Default model name (default: claude-opus-4-5)
        EVAL_TIME_LIMIT - Time limit in seconds (default: 3600)
        EVAL_MESSAGE_LIMIT - Message limit (default: 250)
        EVAL_TEST_TIMEOUT - Test timeout in seconds (default: 900)
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time as time_module
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from eval_runner.logger import get_logger

# Parser imports for F2P generation and shared utilities
from parser import TaskEvaluator, TaskConfig as ParserTaskConfig, load_task_yaml

logger = get_logger(__name__)

# =============================================================================
# ENVIRONMENT LOADING (SINGLE SOURCE OF TRUTH)
# =============================================================================
# This is the canonical location for .env loading. Other modules (run_e2e.py, etc.)
# should NOT load .env themselves - they get it via importing this module.

try:
    from dotenv import load_dotenv
    
    # Look for .env file in observability directory
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        logger.info(f"Loaded environment from {_env_file}")
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass


# =============================================================================
# ARCHITECTURE DETECTION & DOCKER IMAGE CONFIGURATION
# =============================================================================

def _detect_architecture() -> str:
    """Detect the system architecture."""
    import platform
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    elif machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


def _setup_plane_api_image() -> None:
    """
    Set up PLANE_API_IMAGE environment variable based on architecture.
    
    - On ARM64: Uses the ECR image (default)
    - On x86_64: Uses local plane-api-x86:latest if available, otherwise ECR image
    """
    # Skip if already set by user
    if os.environ.get("PLANE_API_IMAGE"):
        return
    
    arch = _detect_architecture()
    ecr_image = "public.ecr.aws/k4t1e3r5/apex-code:plane-api"
    x86_local_image = "plane-api-x86:latest"
    
    if arch == "arm64":
        # ARM64: Use ECR image directly
        os.environ["PLANE_API_IMAGE"] = ecr_image
        logger.debug(f"ARM64 detected: Using PLANE_API_IMAGE={ecr_image}")
    else:
        # x86_64: Check if local image exists
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", x86_local_image],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                os.environ["PLANE_API_IMAGE"] = x86_local_image
                logger.info(f"x86_64 detected: Using local PLANE_API_IMAGE={x86_local_image}")
            else:
                # Local image not found - use ECR (will fail on x86, but gracefully)
                os.environ["PLANE_API_IMAGE"] = ecr_image
                logger.warning(
                    f"x86_64 detected but {x86_local_image} not found. "
                    f"Run 'scripts/build_plane_api_x86.sh' to build it. "
                    f"Using {ecr_image} (may fail on x86_64)."
                )
        except Exception as e:
            os.environ["PLANE_API_IMAGE"] = ecr_image
            logger.warning(f"Could not check for local plane-api image: {e}")


# Auto-detect and configure plane-api image on module load
_setup_plane_api_image()


# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str  # Full model name (e.g., "anthropic/claude-opus-4-5-20251101")
    short_name: str  # Short name for display/logs (e.g., "claude-opus-4-5")
    provider: str  # Provider (anthropic, openai, google, grok, fireworks, cognition)
    base_url: str | None = None  # Optional custom API base URL (for OpenAI-compatible endpoints)
    
    def __str__(self) -> str:
        return self.name


# All available models
MODELS: dict[str, ModelConfig] = {
    # Anthropic
    "claude-opus-4-6": ModelConfig(
        name="anthropic/claude-opus-4-6",
        short_name="claude-opus-4-6",
        provider="anthropic",
    ),
    "claude-opus-4-5": ModelConfig(
        name="anthropic/claude-opus-4-5-20251101",
        short_name="claude-opus-4-5",
        provider="anthropic",
    ),
    "claude-sonnet-4-5": ModelConfig(
        name="anthropic/claude-sonnet-4-5-20250929",
        short_name="claude-sonnet-4-5",
        provider="anthropic",
    ),
    
    # OpenAI
    "gpt-5.2-codex": ModelConfig(
        name="openai/gpt-5.2-codex",
        short_name="gpt-5.2-codex",
        provider="openai",
    ),
    "gpt-5.1-codex": ModelConfig(
        name="openai/gpt-5.1-codex",
        short_name="gpt-5.1-codex",
        provider="openai",
    ),
    
    # Google
    "gemini-3-pro": ModelConfig(
        name="google/gemini-3-pro-preview",
        short_name="gemini-3-pro",
        provider="google",
    ),
    
    # Grok
    "grok-4": ModelConfig(
        name="grok/grok-4",
        short_name="grok-4",
        provider="grok",
    ),
    
    # Fireworks (Kimi)
    "kimi-k2": ModelConfig(
        name="fireworks/accounts/fireworks/models/kimi-k2-instruct-0905",
        short_name="kimi-k2",
        provider="fireworks",
    ),
    "kimi-k2p5": ModelConfig(
        name="fireworks/accounts/fireworks/models/kimi-k2p5",
        short_name="kimi-k2p5",
        provider="fireworks",
    ),
    
    # Fireworks (Qwen)
    "qwen3-coder": ModelConfig(
        name="fireworks/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct",
        short_name="qwen3-coder",
        provider="fireworks",
    ),
    
    # DeepSeek (via Fireworks)
    "deepseek-v3": ModelConfig(
        name="fireworks/accounts/fireworks/models/deepseek-v3-0324",
        short_name="deepseek-v3",
        provider="fireworks",
    ),
    
    # Cognition (OpenAI-compatible endpoint)
    "cognition": ModelConfig(
        name="openai/swe-1.5",
        short_name="cognition",
        provider="cognition",
        base_url=os.environ.get("COGNITION_BASE_URL"),
    ),
}

# Default model
DEFAULT_MODEL = "claude-opus-4-5"


def get_model_config(model: str) -> ModelConfig:
    """Get model configuration by name or short name."""
    # Direct lookup by short name
    if model in MODELS:
        return MODELS[model]
    
    # Lookup by full name
    for config in MODELS.values():
        if config.name == model:
            return config
    
    # Lookup by short_name
    for config in MODELS.values():
        if config.short_name == model:
            return config
    
    raise ValueError(
        f"Unknown model: {model}. Available models: {list(MODELS.keys())}"
    )


# =============================================================================
# PATH CONFIGURATIONS (CENTRALIZED)
# =============================================================================

# Base paths
MODULE_DIR = Path(__file__).parent
# After flattening: eval_runner is inside observability/ directly
# observability/eval_runner/config.py → parent is observability/
OBSERVABILITY_DIR = MODULE_DIR.parent
TASKS_DIR = OBSERVABILITY_DIR / "tasks"

# Output directories
EVAL_OUTPUTS_DIR = OBSERVABILITY_DIR / "eval_outputs"
DEFAULT_OUTPUT_DIR = OBSERVABILITY_DIR / "eval_outputs"  # For eval_runner batch outputs
DEFAULT_LOG_DIR = OBSERVABILITY_DIR / "eval_logs"

# F2P cache directory (separate from tasks to avoid polluting task dirs)
F2P_CACHE_DIR = OBSERVABILITY_DIR / "f2p_cache"

# =============================================================================
# TIMEOUT CONFIGURATIONS (CENTRALIZED)
# =============================================================================

@dataclass
class TimeoutConfig:
    """Centralized timeout configuration for all operations.
    
    All timeout values in seconds.
    """
    # Agent execution timeout (default: 1 hour)
    agent_time_limit: int = 3600
    
    # Test execution timeout (default: 15 minutes)
    test_execution: int = 900
    
    # In-agent scorer timeout (default: 45 minutes)
    in_agent_scorer: int = 2700
    
    # Docker operations
    docker_build: int = 1200  # 20 minutes for building images
    docker_pull: int = 600   # 10 minutes for pulling images
    docker_command: int = 120  # 2 minutes for simple commands
    
    # Git operations
    git_diff: int = 60
    git_apply: int = 60
    git_checkout: int = 30
    
    # F2P generation timeout
    f2p_generation: int = 900  # 15 minutes
    
    # Lock acquisition timeout
    lock_timeout: int = 300  # 5 minutes


TIMEOUTS = TimeoutConfig()


# =============================================================================
# CONTAINER ENVIRONMENT CONFIGURATION (CENTRALIZED)
# =============================================================================

@dataclass
class ContainerConfig:
    """Centralized container environment configuration."""
    workdir: str = "/app/repo"
    
    # PATH setup for container
    path_setup: str = '''
export PATH="/usr/local/go/bin:/usr/local/bin:/root/.local/bin:/root/go/bin:$PATH:./node_modules/.bin"
export GOPATH="${GOPATH:-/root/go}"
export GOROOT="${GOROOT:-/usr/local/go}"
'''
    
    # Git configuration
    git_user_email: str = "eval@apexcode.local"
    git_user_name: str = "Eval Runner"
    
    def get_git_config_commands(self, workdir: str | None = None) -> str:
        """Get git configuration commands for container.
        
        Args:
            workdir: Override workdir for safe.directory (uses self.workdir if None)
        """
        wd = workdir or self.workdir
        return f'''git config --global user.email "{self.git_user_email}"
git config --global user.name "{self.git_user_name}"
git config --global --add safe.directory {wd}'''
    
    def get_test_results_copy_commands(self) -> str:
        """Get shell commands to copy test result files to a standard location.
        
        This is used by both inspect_scorer and docker_runner for consistency.
        Copies JUnit XML, Jest/Vitest JSON, and other framework result files.
        """
        return '''# Copy framework-generated result files to test-results directory
find /app/repo -name 'TEST-*.xml' -path '*/build/*' -exec cp {} /tmp/test-results/ \\; 2>/dev/null || true
find /app/repo -name 'TEST-*.xml' -path '*/target/*' -exec cp {} /tmp/test-results/ \\; 2>/dev/null || true
find /app/repo -name '*-results.json' -exec cp {} /tmp/test-results/ \\; 2>/dev/null || true
find /app/repo -name 'junit.xml' -exec cp {} /tmp/test-results/ \\; 2>/dev/null || true
cp /workspace/test-results/*.xml /tmp/test-results/ 2>/dev/null || true
cp /workspace/*.xml /tmp/test-results/ 2>/dev/null || true
find /app/repo -name '*.xml' -path '*/test-results/*' -exec cp {} /tmp/test-results/ \\; 2>/dev/null || true'''


CONTAINER_CONFIG = ContainerConfig()


# =============================================================================
# EVALUATION DEFAULTS
# =============================================================================

@dataclass
class EvalDefaults:
    """Default evaluation parameters.
    
    Values can be overridden via environment variables:
        EVAL_TIME_LIMIT - Time limit in seconds
        EVAL_MESSAGE_LIMIT - Message limit for agent
        EVAL_TEST_TIMEOUT - Test execution timeout
    """
    time_limit: int = 3600  # 1 hour
    message_limit: int = 250
    test_timeout: int = 900  # 15 minutes for test execution
    parallel: int = 4  # Default parallelism
    trials: int = 1  # Number of trials per task


# Create defaults, allowing environment variable overrides
EVAL_DEFAULTS = EvalDefaults(
    time_limit=int(os.environ.get("EVAL_TIME_LIMIT", TIMEOUTS.agent_time_limit)),
    message_limit=int(os.environ.get("EVAL_MESSAGE_LIMIT", 250)),
    test_timeout=int(os.environ.get("EVAL_TEST_TIMEOUT", TIMEOUTS.test_execution)),
)


# =============================================================================
# DOCKER IMAGE NAMING
# =============================================================================

def get_docker_image_name(task_id: str) -> str:
    """Get Docker image name for a task.
    
    Convention: <task_id>-default:latest
    """
    return f"{task_id}-default:latest"


# =============================================================================
# RUN DIRECTORY MANAGEMENT (UUID-BASED TO PREVENT RACE CONDITIONS)
# =============================================================================

def generate_run_id() -> str:
    """Generate a unique run ID using UUID and timestamp.
    
    Format: YYYYMMDD_HHMMSS_<uuid4-short>
    This ensures uniqueness even in parallel execution scenarios.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]  # Short UUID suffix
    return f"{timestamp}_{unique_id}"


def get_eval_outputs_dir(task_id: str) -> Path:
    """Get the eval_outputs directory for a specific task.
    
    This is where test_scorer.py saves agent.patch, test_output.txt, and metadata.json.
    Path: inspect_evals/eval_outputs/<task_id>/
    
    IMPORTANT: This path MUST match the path used in test_scorer.py's save_run_outputs()
    """
    return EVAL_OUTPUTS_DIR / task_id


def get_run_dir_by_id(task_id: str, run_id: str) -> Path | None:
    """Get a specific run directory by its ID.
    
    Args:
        task_id: Task identifier
        run_id: The unique run ID
        
    Returns:
        Path to the run directory, or None if not found
    """
    run_dir = get_eval_outputs_dir(task_id) / run_id
    return run_dir if run_dir.exists() else None


def get_latest_run_dir(task_id: str) -> Path | None:
    """Get the most recent run directory for a task.
    
    Note: This is provided for backward compatibility but should be avoided
    in concurrent scenarios. Prefer passing run_id explicitly through the pipeline.
    
    Returns:
        Path to the latest run directory, or None if no runs exist.
    """
    task_outputs_dir = get_eval_outputs_dir(task_id)
    if not task_outputs_dir.exists():
        return None
    
    try:
        run_dirs = sorted(task_outputs_dir.iterdir(), reverse=True)
        return run_dirs[0] if run_dirs else None
    except OSError as e:
        logger.warning(f"Failed to list run directories for {task_id}: {e}")
        return None


def get_agent_diff_from_run(run_dir: Path) -> str:
    """Read agent.patch from a run directory.
    
    Args:
        run_dir: Path to the run directory (e.g., eval_outputs/<task_id>/<run_id>/)
        
    Returns:
        Agent diff content, or empty string if not found.
    """
    agent_patch_path = run_dir / "agent.patch"
    if agent_patch_path.exists():
        try:
            return agent_patch_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"Failed to read agent.patch from {run_dir}: {e}")
            return ""
    return ""


# =============================================================================
# TASK CONFIGURATION
# =============================================================================

@dataclass
class EvalTaskConfig:
    """
    Configuration for a single evaluation task in the eval_runner.
    
    This is distinct from parser.TaskConfig which is used for scoring.
    EvalTaskConfig is loaded from task directories and used by the agent runner.
    """
    task_id: str
    task_dir: Path
    docker_image: str
    test_command: str
    test_framework: str
    test_patch: str
    golden_patch: str
    test_files: list[str] = field(default_factory=list)
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    language: str = ""
    timeout: int = 900
    requires_compose: bool = False  # If True, use docker compose exec for F2P generation (for tasks needing services like Redis)
    
    @classmethod
    def from_task_dir(cls, task_dir: Path) -> "EvalTaskConfig":
        """Load task configuration from a task directory.
        
        Note: F2P/P2P from test_metadata.json are NOT used.
        Use get_f2p_for_task() to get F2P/P2P from cache or golden patch.
        """
        task_id = task_dir.name
        
        # Load test_metadata.json for test command and framework only
        test_metadata_path = task_dir / "test_metadata.json"
        if not test_metadata_path.exists():
            raise FileNotFoundError(f"test_metadata.json not found in {task_dir}")
        
        try:
            with open(test_metadata_path) as f:
                metadata = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in test_metadata.json: {e}")
        
        # Load patches
        test_patch = ""
        test_patch_path = task_dir / "test.patch"
        if test_patch_path.exists():
            try:
                test_patch = test_patch_path.read_text()
            except OSError as e:
                logger.warning(f"Failed to read test.patch: {e}")
        
        golden_patch = ""
        golden_patch_path = task_dir / "golden.patch"
        if golden_patch_path.exists():
            try:
                golden_patch = golden_patch_path.read_text()
            except OSError as e:
                logger.warning(f"Failed to read golden.patch: {e}")
        
        # Load task.yaml for additional config (uses shared helper from parser)
        task_yaml = load_task_yaml(task_dir)
        requires_compose = task_yaml.get("requires_compose", False)
        
        return cls(
            task_id=task_id,
            task_dir=task_dir,
            docker_image=get_docker_image_name(task_id),
            test_command=metadata.get("test_command", ""),
            test_framework=metadata.get("test_framework", ""),
            test_patch=test_patch,
            golden_patch=golden_patch,
            test_files=metadata.get("test_files", []),
            fail_to_pass=[],
            pass_to_pass=[],
            language=metadata.get("language", ""),
            requires_compose=requires_compose,
        )


# Module-level cache for task IDs (avoids re-scanning filesystem)
_task_ids_cache: list[str] | None = None


def get_all_task_ids(*, refresh: bool = False) -> list[str]:
    """
    Get all available task IDs (cached after first call).
    
    Args:
        refresh: Force refresh of the cache
        
    Returns:
        Sorted list of task IDs
    """
    global _task_ids_cache
    
    if _task_ids_cache is not None and not refresh:
        return _task_ids_cache
    
    if not TASKS_DIR.exists():
        _task_ids_cache = []
        return _task_ids_cache
    
    _task_ids_cache = sorted([
        d.name for d in TASKS_DIR.iterdir()
        if d.is_dir() and d.name != "shared" and (d / "test_metadata.json").exists()
    ])
    return _task_ids_cache


def load_task_config(task_id: str) -> EvalTaskConfig:
    """Load task configuration by ID."""
    task_dir = TASKS_DIR / task_id
    if not task_dir.exists():
        raise FileNotFoundError(f"Task directory not found: {task_dir}")
    return EvalTaskConfig.from_task_dir(task_dir)


# =============================================================================
# F2P CACHE - Pre-computed FAIL_TO_PASS / PASS_TO_PASS from golden patch
# =============================================================================

@dataclass
class F2PCache:
    """Pre-computed F2P/P2P lists from golden patch analysis."""
    task_id: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    generated_at: str = ""
    baseline_tests_count: int = 0
    golden_tests_count: int = 0
    error: str | None = None
    # Raw test outputs (stored in separate files, paths stored here)
    baseline_output_file: str | None = None
    golden_output_file: str | None = None
    # Exit codes
    baseline_exit_code: int | None = None
    golden_exit_code: int | None = None
    # Parsed results (stored inline - they're small dicts)
    baseline_parsed_results: dict[str, str] | None = None
    golden_parsed_results: dict[str, str] | None = None
    # Hash of golden.patch for cache invalidation (None = legacy cache, always valid)
    golden_patch_hash: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "fail_to_pass": self.fail_to_pass,
            "pass_to_pass": self.pass_to_pass,
            "generated_at": self.generated_at,
            "baseline_tests_count": self.baseline_tests_count,
            "golden_tests_count": self.golden_tests_count,
            "error": self.error,
            "baseline_output_file": self.baseline_output_file,
            "golden_output_file": self.golden_output_file,
            "baseline_exit_code": self.baseline_exit_code,
            "golden_exit_code": self.golden_exit_code,
            "baseline_parsed_results": self.baseline_parsed_results,
            "golden_parsed_results": self.golden_parsed_results,
            "golden_patch_hash": self.golden_patch_hash,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "F2PCache":
        return cls(
            task_id=data.get("task_id", ""),
            fail_to_pass=data.get("fail_to_pass", []),
            pass_to_pass=data.get("pass_to_pass", []),
            generated_at=data.get("generated_at", ""),
            baseline_tests_count=data.get("baseline_tests_count", 0),
            golden_tests_count=data.get("golden_tests_count", 0),
            error=data.get("error"),
            baseline_output_file=data.get("baseline_output_file"),
            golden_output_file=data.get("golden_output_file"),
            baseline_exit_code=data.get("baseline_exit_code"),
            golden_exit_code=data.get("golden_exit_code"),
            baseline_parsed_results=data.get("baseline_parsed_results"),
            golden_parsed_results=data.get("golden_parsed_results"),
            golden_patch_hash=data.get("golden_patch_hash"),
        )


def get_f2p_cache_path(task_id: str) -> Path:
    """Get path to F2P cache file for a task."""
    return F2P_CACHE_DIR / f"{task_id}.json"


def compute_golden_patch_hash(golden_patch: str | None) -> str | None:
    """Compute SHA-256 hash of golden patch content for cache invalidation."""
    if not golden_patch:
        return None
    return hashlib.sha256(golden_patch.encode()).hexdigest()[:16]


def load_f2p_cache(task_id: str, *, validate_hash: bool = True) -> F2PCache | None:
    """Load pre-computed F2P/P2P from cache.
    
    Args:
        task_id: Task identifier
        validate_hash: If True, invalidate cache if golden.patch has changed
    
    Returns:
        F2PCache if cache exists and is valid, None otherwise.
    """
    cache_path = get_f2p_cache_path(task_id)
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path) as f:
            data = json.load(f)
        cache = F2PCache.from_dict(data)
        
        # Validate golden patch hash if requested and cache has a hash
        if validate_hash and cache.golden_patch_hash is not None:
            try:
                config = load_task_config(task_id)
                current_hash = compute_golden_patch_hash(config.golden_patch)
                if current_hash != cache.golden_patch_hash:
                    logger.info(
                        f"[{task_id}] F2P cache invalidated: golden.patch changed "
                        f"(cached: {cache.golden_patch_hash}, current: {current_hash})"
                    )
                    return None
            except FileNotFoundError:
                # Task config not found - cache is still valid for its original task
                pass
        
        return cache
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load F2P cache for {task_id}: {e}")
        return None


def _acquire_lock_with_timeout(lock_path: Path, timeout: int = TIMEOUTS.lock_timeout) -> tuple[Any, bool]:
    """Acquire a file lock with timeout.
    
    Args:
        lock_path: Path to the lock file
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (lock_file, was_first) where was_first indicates if we acquired
        the lock immediately (True) vs had to wait for another process (False).
        Returns (None, False) if lock acquisition failed entirely.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    
    start_time = time_module.time()
    was_first = False
    lock_acquired = False
    
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            was_first = True  # Got lock immediately - we're first
            lock_acquired = True
            break
        except BlockingIOError:
            if time_module.time() - start_time > timeout:
                logger.warning(f"Lock acquisition timeout after {timeout}s for {lock_path}, switching to blocking")
                break
            time_module.sleep(0.5)
    
    if not lock_acquired:
        # Non-blocking attempts timed out, try blocking acquisition
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            was_first = False  # We had to wait - another process was first
            lock_acquired = True
        except OSError as e:
            logger.error(f"Failed to acquire lock: {e}")
            lock_file.close()
            return None, False
    
    return lock_file, was_first


def _release_lock(lock_file: Any, lock_path: Path) -> None:
    """Release a file lock and clean up lock file."""
    if lock_file is None:
        return
    
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
    except OSError as e:
        logger.warning(f"Error releasing lock: {e}")
    
    # Clean up lock file
    try:
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass  # Ignore cleanup errors


def save_f2p_cache(cache: F2PCache) -> Path:
    """Save F2P cache to disk with file locking to prevent race conditions.
    
    Returns:
        Path to the saved cache file.
    """
    F2P_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_f2p_cache_path(cache.task_id)
    lock_path = cache_path.with_suffix(".lock")
    
    lock_file, _ = _acquire_lock_with_timeout(lock_path)
    if lock_file is None:
        logger.error(f"Failed to acquire lock for saving F2P cache: {cache.task_id}")
        # Still try to save without lock
        with open(cache_path, "w") as f:
            json.dump(cache.to_dict(), f, indent=2)
        return cache_path
    
    try:
        with open(cache_path, "w") as f:
            json.dump(cache.to_dict(), f, indent=2)
    finally:
        _release_lock(lock_file, lock_path)
    
    return cache_path


def generate_f2p_cache_for_task(
    task_id: str, 
    timeout: int = TIMEOUTS.f2p_generation, 
    verbose: bool = False
) -> F2PCache:
    """Generate F2P/P2P cache for a task by running tests with golden patch.
    
    Priority: F2P cache > golden patch generation
    test_metadata.json F2P/P2P is NOT used.
    
    Uses TaskEvaluator.generate_f2p_p2p() which properly handles:
    - Tests that FAIL in baseline but PASS in golden (standard F2P)
    - Tests that only exist in golden and PASS (new tests added by golden patch)
    
    Returns:
        F2PCache with computed F2P/P2P lists
    """
    if verbose:
        logger.info(f"[{task_id}] Generating F2P cache from golden patch...")
    
    config = load_task_config(task_id)
    
    if not config.golden_patch:
        return F2PCache(
            task_id=task_id,
            fail_to_pass=[],
            pass_to_pass=[],
            error="No golden.patch found",
            generated_at=datetime.now().isoformat(),
        )
    
    # Create parser TaskConfig
    parser_config = ParserTaskConfig(
        task_id=task_id,
        docker_image=config.docker_image,
        test_command=config.test_command,
        test_framework=config.test_framework,
        test_patch=config.test_patch,
        golden_patch=config.golden_patch,
        test_files=config.test_files,
        fail_to_pass=None,  # Will be generated
        pass_to_pass=None,  # Will be generated
        language=config.language,
        timeout=timeout,
        workdir=CONTAINER_CONFIG.workdir,
        task_dir=config.task_dir,
        requires_compose=config.requires_compose,  # Pass through for tasks needing services
    )
    
    # Use generate_f2p_p2p() which properly computes F2P/P2P including new tests
    evaluator = TaskEvaluator(verbose=verbose, workdir=CONTAINER_CONFIG.workdir)
    
    try:
        result = evaluator.generate_f2p_p2p(parser_config)
    except Exception as e:
        logger.error(f"[{task_id}] F2P generation failed: {e}")
        return F2PCache(
            task_id=task_id,
            fail_to_pass=[],
            pass_to_pass=[],
            error=f"F2P generation failed: {str(e)}",
            generated_at=datetime.now().isoformat(),
        )
    
    if result.error:
        return F2PCache(
            task_id=task_id,
            fail_to_pass=[],
            pass_to_pass=[],
            error=result.error,
            generated_at=datetime.now().isoformat(),
        )
    
    if verbose:
        logger.info(f"[{task_id}] Pre-patch: {len(result.pre_patch_results)} tests")
        logger.info(f"[{task_id}] Post-patch: {len(result.post_patch_results)} tests")
        logger.info(f"[{task_id}] F2P: {len(result.fail_to_pass)} tests, P2P: {len(result.pass_to_pass)} tests")
    
    # Save raw test outputs to separate files (they can be large)
    baseline_output_file = None
    golden_output_file = None
    
    if result.pre_output:
        baseline_path = get_f2p_cache_path(task_id).with_suffix(".baseline.txt")
        try:
            baseline_path.write_text(result.pre_output)
            baseline_output_file = str(baseline_path)
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to save baseline output: {e}")
    
    if result.post_output:
        golden_path = get_f2p_cache_path(task_id).with_suffix(".golden.txt")
        try:
            golden_path.write_text(result.post_output)
            golden_output_file = str(golden_path)
        except Exception as e:
            logger.warning(f"[{task_id}] Failed to save golden output: {e}")
    
    cache = F2PCache(
        task_id=task_id,
        fail_to_pass=result.fail_to_pass,
        pass_to_pass=result.pass_to_pass,
        generated_at=datetime.now().isoformat(),
        baseline_tests_count=len(result.pre_patch_results),
        golden_tests_count=len(result.post_patch_results),
        baseline_output_file=baseline_output_file,
        golden_output_file=golden_output_file,
        baseline_exit_code=result.pre_exit_code,
        golden_exit_code=result.post_exit_code,
        baseline_parsed_results=result.pre_patch_results,
        golden_parsed_results=result.post_patch_results,
        golden_patch_hash=compute_golden_patch_hash(config.golden_patch),
    )
    
    # Save cache for future use
    save_f2p_cache(cache)
    
    return cache


def get_f2p_for_task(
    task_id: str, 
    auto_generate: bool = True,
    timeout: int = TIMEOUTS.f2p_generation,
    verbose: bool = False,
) -> tuple[list[str], list[str]]:
    """Get F2P/P2P lists for a task.
    
    Priority:
    1. F2P cache (pre-computed from golden patch) - preferred
    2. Auto-generate from golden patch if auto_generate=True
    3. Empty lists as fallback
    
    Note: F2P/P2P from test_metadata.json is NOT used.
    
    Uses file locking with timeout to prevent race conditions when multiple 
    processes try to generate the cache for the same task simultaneously.
    
    Args:
        task_id: Task identifier
        auto_generate: If True, generate F2P cache if it doesn't exist
        timeout: Timeout for test execution during generation
        verbose: Print progress during generation
    
    Returns:
        tuple of (fail_to_pass, pass_to_pass) lists
    """
    # Try F2P cache first
    cache = load_f2p_cache(task_id)
    if cache and cache.fail_to_pass:
        return cache.fail_to_pass, cache.pass_to_pass
    
    # Auto-generate if enabled and cache doesn't exist
    if auto_generate:
        F2P_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = get_f2p_cache_path(task_id).with_suffix(".generation.lock")
        
        lock_file, got_lock = _acquire_lock_with_timeout(lock_path)
        
        if lock_file is None:
            logger.warning(f"[{task_id}] Could not acquire lock for F2P generation")
            # Fallback: try without locking
            try:
                cache = generate_f2p_cache_for_task(task_id, timeout=timeout, verbose=verbose)
                if cache and cache.fail_to_pass:
                    return cache.fail_to_pass, cache.pass_to_pass
            except Exception as e:
                logger.error(f"[{task_id}] Failed to generate F2P cache: {e}")
            return [], []
        
        try:
            # Check cache again (another process might have created it)
            cache = load_f2p_cache(task_id)
            if cache and cache.fail_to_pass:
                return cache.fail_to_pass, cache.pass_to_pass
            
            # Generate cache if we got the lock first or cache still doesn't exist
            if verbose:
                logger.info(f"[{task_id}] Generating F2P cache from golden patch...")
            
            cache = generate_f2p_cache_for_task(task_id, timeout=timeout, verbose=verbose)
            if cache and cache.fail_to_pass:
                return cache.fail_to_pass, cache.pass_to_pass
            
        except Exception as e:
            logger.error(f"[{task_id}] Failed to generate F2P cache: {e}")
        finally:
            _release_lock(lock_file, lock_path)
    
    logger.warning(
        f"[{task_id}] Returning empty F2P/P2P lists - task cannot be properly validated"
    )
    return [], []


# =============================================================================
# HEALTH CHECKS
# =============================================================================

@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def check_docker_available() -> HealthCheckResult:
    """Check if Docker daemon is running and accessible."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return HealthCheckResult(
                name="docker",
                passed=True,
                message="Docker daemon is running",
            )
        else:
            return HealthCheckResult(
                name="docker",
                passed=False,
                message=f"Docker check failed: {result.stderr[:200]}",
            )
    except subprocess.TimeoutExpired:
        return HealthCheckResult(
            name="docker",
            passed=False,
            message="Docker check timed out",
        )
    except FileNotFoundError:
        return HealthCheckResult(
            name="docker",
            passed=False,
            message="Docker not found in PATH",
        )
    except Exception as e:
        return HealthCheckResult(
            name="docker",
            passed=False,
            message=f"Docker check error: {e}",
        )


def check_disk_space(min_gb: float = 10.0) -> HealthCheckResult:
    """Check if there's enough disk space available."""
    try:
        usage = shutil.disk_usage(OBSERVABILITY_DIR)
        free_gb = usage.free / (1024**3)
        
        if free_gb >= min_gb:
            return HealthCheckResult(
                name="disk_space",
                passed=True,
                message=f"Disk space OK: {free_gb:.1f} GB free",
                details={"free_gb": free_gb, "min_gb": min_gb},
            )
        else:
            return HealthCheckResult(
                name="disk_space",
                passed=False,
                message=f"Low disk space: {free_gb:.1f} GB free (need {min_gb} GB)",
                details={"free_gb": free_gb, "min_gb": min_gb},
            )
    except Exception as e:
        return HealthCheckResult(
            name="disk_space",
            passed=False,
            message=f"Disk space check error: {e}",
        )


def check_task_exists(task_id: str) -> HealthCheckResult:
    """Check if a task directory exists with required files."""
    task_dir = TASKS_DIR / task_id
    
    if not task_dir.exists():
        return HealthCheckResult(
            name="task_exists",
            passed=False,
            message=f"Task directory not found: {task_dir}",
        )
    
    required_files = ["test_metadata.json"]
    optional_files = ["test.patch", "golden.patch", "compose.yaml"]
    
    missing_required = [f for f in required_files if not (task_dir / f).exists()]
    if missing_required:
        return HealthCheckResult(
            name="task_exists",
            passed=False,
            message=f"Missing required files: {missing_required}",
        )
    
    existing_optional = [f for f in optional_files if (task_dir / f).exists()]
    
    return HealthCheckResult(
        name="task_exists",
        passed=True,
        message=f"Task exists with files: {existing_optional}",
        details={"task_dir": str(task_dir), "optional_files": existing_optional},
    )


def check_docker_image_exists(task_id: str) -> HealthCheckResult:
    """Check if the Docker image for a task exists locally."""
    image_name = get_docker_image_name(task_id)
    
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        
        if result.returncode == 0:
            return HealthCheckResult(
                name="docker_image",
                passed=True,
                message=f"Docker image exists: {image_name}",
            )
        else:
            return HealthCheckResult(
                name="docker_image",
                passed=False,
                message=f"Docker image not found: {image_name} (will be built on demand)",
            )
    except Exception as e:
        return HealthCheckResult(
            name="docker_image",
            passed=False,
            message=f"Docker image check error: {e}",
        )


def check_api_key(provider: str) -> HealthCheckResult:
    """Check if API key is configured for a provider."""
    key_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "grok": "XAI_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
        "cognition": "COGNITION_API_KEY",
    }
    
    var_name = key_vars.get(provider.lower())
    if not var_name:
        return HealthCheckResult(
            name=f"api_key_{provider}",
            passed=False,
            message=f"Unknown provider: {provider}",
        )
    
    value = os.environ.get(var_name, "")
    
    if value:
        # Mask the key for security
        masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
        return HealthCheckResult(
            name=f"api_key_{provider}",
            passed=True,
            message=f"{var_name} is set ({masked})",
        )
    else:
        return HealthCheckResult(
            name=f"api_key_{provider}",
            passed=False,
            message=f"{var_name} is not set",
        )


def run_health_checks(
    task_id: Optional[str] = None,
    model: Optional[str] = None,
) -> list[HealthCheckResult]:
    """Run all relevant health checks.
    
    Args:
        task_id: Optional task ID to check task-specific requirements
        model: Optional model name to check API key
        
    Returns:
        List of health check results
    """
    results = []
    
    # Always check Docker
    results.append(check_docker_available())
    
    # Always check disk space
    results.append(check_disk_space())
    
    # Check task if specified
    if task_id:
        results.append(check_task_exists(task_id))
        results.append(check_docker_image_exists(task_id))
    
    # Check API key if model specified
    if model:
        try:
            config = get_model_config(model)
            results.append(check_api_key(config.provider))
        except ValueError:
            results.append(HealthCheckResult(
                name="model",
                passed=False,
                message=f"Unknown model: {model}",
            ))
    
    return results


def validate_health_checks(
    task_id: Optional[str] = None,
    model: Optional[str] = None,
    fail_on_warning: bool = False,
) -> bool:
    """Run health checks and return True if all critical checks pass.
    
    Args:
        task_id: Optional task ID
        model: Optional model name
        fail_on_warning: If True, treat warnings as failures
        
    Returns:
        True if all checks pass, False otherwise
    """
    results = run_health_checks(task_id, model)
    
    all_passed = True
    for result in results:
        status = "✓" if result.passed else "✗"
        level = "INFO" if result.passed else "ERROR"
        
        if result.passed:
            logger.info(f"  {status} {result.name}: {result.message}")
        else:
            logger.error(f"  {status} {result.name}: {result.message}")
            # Docker image not existing is a warning, not a failure
            if result.name != "docker_image":
                all_passed = False
    
    return all_passed
