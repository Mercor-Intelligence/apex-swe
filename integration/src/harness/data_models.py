"""Data models for the evaluation harness."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExecutionStatus(str, Enum):
    """Status of task execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ModelType(str, Enum):
    """Supported model types."""

    CLAUDE_4_1 = "claude-opus-4-1-20250805"
    CLAUDE_4 = "claude-opus-4-20250514"
    CLAUDE_OPUS_4_5 = "claude-opus-4-5-20251101"
    CLAUDE_SONNET_4_5 = "claude-sonnet-4-5-20250929"
    CLAUDE_SONNET_4 = "claude-sonnet-4-20250514"
    GPT4O = "gpt-4o"
    GPT5 = "gpt-5"
    GPT5_CODEX = "gpt-5-codex"
    GPT5_1_CODEX = "gpt-5.1-codex"
    GEMINI_2_5_PRO = "gemini/gemini-2.5-pro"
    GEMINI_2_5_FLASH = "gemini/gemini-2.5-flash"
    GEMINI_3_PRO_PREVIEW = "gemini/gemini-3-pro-preview"
    XAI_GROK_4 = "xai/grok-4"
    META_LLAMA_4_MAVERICK = "meta_llama/Llama-4-Maverick-17B-128E-Instruct-FP8"
    QWEN3_CODER_480B = (
        "fireworks_ai/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct"
    )
    DEEPSEEK_V3P2 = "fireworks_ai/accounts/fireworks/models/deepseek-v3p2"
    KIMI_K2_THINKING = "fireworks_ai/accounts/fireworks/models/kimi-k2-thinking"
    KIMI_K2P5 = "fireworks_ai/accounts/fireworks/models/kimi-k2p5"

    CLAUDE_OPUS_4_6 = "claude-opus-4-6"
    GPT5_2 = "gpt-5.2"
    GPT5_2_CODEX = "gpt-5.2-codex"
    GPT5_3 = "gpt-5.3"
    GPT5_3_CODEX = "gpt-5.3-codex"
    GPT5_4 = "gpt-5.4"
    GEMINI_3_1_PRO_PREVIEW = "gemini/gemini-3.1-pro-preview"

    CUSTOM = "custom"


class ModelResponse(BaseModel):
    """Standardized response from a model."""

    content: str = Field(..., description="The agent's response content")
    reasoning: str | None = Field(None, description="Agent's reasoning process")
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Agent's confidence score"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    tokens_used: int | None = Field(None, ge=0, description="Number of tokens used")
    response_time: float | None = Field(
        None, ge=0, description="Response time in seconds"
    )

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v):
        if v is not None and not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class TaskContext(BaseModel):
    """Context information for a task execution."""

    task_id: str = Field(..., description="Unique task identifier")
    task_dir: Path = Field(..., description="Path to task directory")
    instruction: str = Field(..., description="Task instruction text")
    files: list[Path] = Field(default_factory=list, description="Task-related files")
    environment: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    timeout: int = Field(1800, ge=1, description="Timeout in seconds")
    max_memory: int | None = Field(None, ge=1, description="Max memory in MB")
    max_agent_timeout_sec: float | None = Field(
        None, description="Max timeout for agent execution from task.yaml"
    )
    max_test_timeout_sec: float | None = Field(
        None, description="Max timeout for test execution from task.yaml"
    )
    max_steps: int | None = Field(
        None, description="Max steps for multi-step execution (None = unlimited)"
    )
    process_checks: list[dict[str, Any]] | None = Field(
        None,
        description="Process verification checks from task.yaml — defines which services "
        "the agent must interact with during execution",
    )
    run_dir: Path | None = Field(
        None,
        description="Run output directory ({runs_dir}/{run_id}). Used by MultiStepRunner "
        "to place per-trial Kosmos artifacts (trajectory.jsonl, results.json).",
    )
    model: str | None = Field(
        None,
        description="Model name string (for recording into trial results.json).",
    )
    fail_to_pass: list[str] = Field(
        default_factory=list,
        description="FAIL_TO_PASS test IDs from test_metadata.json (for layer evaluation).",
    )
    pass_to_pass: list[str] = Field(
        default_factory=list,
        description="PASS_TO_PASS test IDs from test_metadata.json (for layer evaluation).",
    )

    class Config:
        arbitrary_types_allowed = True


class TaskExecution(BaseModel):
    """Result of a single task execution attempt."""

    trial_number: int = Field(..., ge=1, description="Trial number (1-based)")
    status: ExecutionStatus = Field(..., description="Execution status")
    agent_response: ModelResponse | None = Field(None, description="Agent's response")
    error_message: str | None = Field(None, description="Error message if failed")
    execution_time: float = Field(
        ..., ge=0, description="Total execution time in seconds"
    )
    memory_used: int | None = Field(None, ge=0, description="Memory used in MB")
    logs: list[str] = Field(default_factory=list, description="Execution logs")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )
    started_at: datetime = Field(..., description="When execution started")
    completed_at: datetime | None = Field(None, description="When execution completed")

    @field_validator("completed_at")
    @classmethod
    def validate_completion_time(cls, v, info):
        if v is not None and "started_at" in info.data:
            if v < info.data["started_at"]:
                raise ValueError("completed_at must be after started_at")
        return v


class EvaluationConfig(BaseModel):
    """Configuration for an evaluation run."""

    run_id: str = Field(..., description="Unique run identifier")
    task_id: str = Field(..., description="Task to evaluate")
    model: ModelType = Field(..., description="Model to use for evaluation")
    max_trials: int = Field(3, ge=1, le=10, description="Maximum number of trials")
    timeout: int = Field(1800, ge=1, description="Timeout per trial in seconds")
    runs_dir: Path = Field(Path("runs"), description="Directory to store run results")
    tasks_dir: Path = Field(Path("tasks"), description="Directory containing tasks")
    max_steps: int | None = Field(
        None, description="Maximum steps per trial (None = unlimited)"
    )
    todo_tool_enabled: bool = Field(
        False, description="Enable the todo tool for task management"
    )
    reasoning_effort: str | None = Field(
        None, description="Reasoning effort: low, medium, high (auto-detected for supported models)"
    )
    custom_agent_config: dict[str, Any] | None = Field(
        None, description="Custom agent configuration"
    )
    evaluation_metrics: list[str] = Field(
        default_factory=lambda: ["success", "time", "quality"],
        description="Metrics to evaluate",
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="When run was created"
    )

    class Config:
        arbitrary_types_allowed = True


class RunResult(BaseModel):
    """Final result of a complete evaluation run."""

    run_id: str = Field(..., description="Unique run identifier")
    task_id: str = Field(..., description="Task that was evaluated")
    model: ModelType = Field(..., description="Model used for evaluation")
    status: ExecutionStatus = Field(..., description="Overall run status")
    trials: list[TaskExecution] = Field(..., description="Individual trial results")
    success_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Success rate across trials"
    )
    average_time: float = Field(
        ..., ge=0, description="Average execution time in seconds"
    )
    total_time: float = Field(..., ge=0, description="Total run time in seconds")
    best_trial: TaskExecution | None = Field(None, description="Best performing trial")
    metrics: dict[str, float | int | str] = Field(
        default_factory=dict, description="Computed evaluation metrics"
    )
    summary: str = Field(..., description="Human-readable summary of results")
    created_at: datetime = Field(..., description="When run was created")
    completed_at: datetime | None = Field(None, description="When run was completed")

    @field_validator("success_rate")
    @classmethod
    def validate_success_rate(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("Success rate must be between 0.0 and 1.0")
        return v

    @field_validator("completed_at")
    @classmethod
    def validate_completion_time(cls, v, info):
        if v is not None and "created_at" in info.data:
            if v < info.data["created_at"]:
                raise ValueError("completed_at must be after created_at")
        return v

    class Config:
        arbitrary_types_allowed = True
