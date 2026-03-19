"""Unified LLM implementation using LiteLLM."""

import bisect
import logging
import os
from typing import Any

import litellm
from litellm.exceptions import (
    AuthenticationError as LiteLLMAuthenticationError,
    ContextWindowExceededError as LiteLLMContextWindowExceededError,
)
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.config import (
    ANTHROPIC_THINKING_BUDGETS,
    DEFAULT_TEMPERATURE,
    GEMINI_THINKING_BUDGETS,
    MODELS_NOT_SUPPORTING_TEMP,
    MODELS_SUPPORTING_REASONING,
    REQUIRED_TEMPERATURE_1_0,
)

logger = logging.getLogger(__name__)


class ContextLengthExceededError(Exception):
    """Raised when the LLM response indicates the context length was exceeded."""

    pass


class OutputLengthExceededError(Exception):
    """Raised when the LLM response was truncated due to max_tokens limit."""

    def __init__(self, message: str, truncated_response: str | None = None):
        super().__init__(message)
        self.truncated_response = truncated_response


# Model token limits
MODEL_MAX_TOKENS = {
    "claude-sonnet-4-20250514": 1_000_000,
    "claude-sonnet-4-5-20250929": 1_000_000,
    "claude-opus-4-5-20251101": 200_000,
    "claude-opus-4-6": 1_000_000,
    "gemini/gemini-2.5-pro": 1_000_000,
    "gemini/gemini-3-pro-preview": 1_000_000,
    "gemini/gemini-3.1-pro-preview": 1_000_000,
    "gpt-5.1-codex": 272_000,
    "gpt-5.2": 400_000,
    "gpt-5.4": 272_000,
    "xai/grok-4": 256_000,
}

# Provider detection patterns
PROVIDER_PATTERNS = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "google",
    "xai/": "xai",
    "meta_llama/": "meta_llama",
    "fireworks": "fireworks_ai",
}

API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "meta_llama": "LLAMA_API_KEY",
    "fireworks_ai": "FIREWORKS_API_KEY",
}


class LiteLLM:
    """LiteLLM implementation with integrated conversation management."""

    def __init__(
        self,
        model_name: str,
        api_key: str | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        **kwargs,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.conversation_history: list[dict[str, Any]] = []
        self.total_tokens_used = 0

        # Set reasoning effort (explicit > config default > None)
        self.reasoning_effort = reasoning_effort
        if not self.reasoning_effort:
            for prefix, default_effort in MODELS_SUPPORTING_REASONING.items():
                if model_name.startswith(prefix):
                    self.reasoning_effort = default_effort
                    break

        # Set max tokens
        self.max_tokens = MODEL_MAX_TOKENS.get(model_name)
        if not self.max_tokens:
            if "qwen3-coder" in model_name.lower():
                self.max_tokens = 262_144
            elif "deepseek" in model_name.lower():
                self.max_tokens = 163_840
            elif "kimi-k2" in model_name.lower():
                self.max_tokens = 128_000
            else:
                try:
                    self.max_tokens = litellm.get_max_tokens(model_name)
                except Exception:
                    logger.warning(f"Failed to get max tokens for {model_name}, using default")
                    self.max_tokens = 4096

        # Set temperature
        if temperature is not None:
            self.temperature = temperature
        elif model_name in MODELS_NOT_SUPPORTING_TEMP:
            self.temperature = REQUIRED_TEMPERATURE_1_0
        else:
            self.temperature = DEFAULT_TEMPERATURE

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=15),
        retry=retry_if_not_exception_type(
            (ContextLengthExceededError, OutputLengthExceededError, LiteLLMAuthenticationError)
        ),
    )
    def call(self, prompt: str, **kwargs) -> str:
        """Call the LLM with a prompt and return the response."""
        try:
            messages = self.conversation_history + [{"role": "user", "content": prompt}]
            completion_kwargs = {
                "model": self.model_name,
                "messages": messages,
                "temperature": self.temperature,
                "api_key": self.api_key,
                "drop_params": True,
                **kwargs,
            }

            # Model-specific adjustments
            if self.model_name in ("claude-sonnet-4-20250514", "claude-sonnet-4-5-20250929"):
                completion_kwargs["extra_headers"] = {"anthropic-beta": "context-1m-2025-08-07"}
            if self.model_name in ("claude-sonnet-4-5-20250929", "claude-opus-4-5-20251101"):
                completion_kwargs["temperature"] = 1.0
            # Apply reasoning/thinking based on provider
            if self.reasoning_effort:
                provider = get_provider_for_model(self.model_name)
                if provider == "anthropic":
                    budget = ANTHROPIC_THINKING_BUDGETS.get(self.reasoning_effort, 32_000)
                    completion_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                    completion_kwargs["temperature"] = 1.0  # Required for Anthropic thinking
                elif provider == "google":
                    budget = GEMINI_THINKING_BUDGETS.get(self.reasoning_effort, 32_768)
                    completion_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                else:
                    # OpenAI, xAI: use reasoning_effort directly
                    completion_kwargs["reasoning_effort"] = self.reasoning_effort

            response = litellm.completion(**completion_kwargs)
            return response.choices[0].message.content

        except LiteLLMContextWindowExceededError:
            raise ContextLengthExceededError

    def count_tokens(self, messages: list[dict]) -> int:
        """Count tokens in messages."""
        try:
            return litellm.utils.token_counter(self.model_name, messages)
        except Exception:
            return sum(len(str(msg.get("content", ""))) for msg in messages) // 4

    def add_to_conversation(self, user_message: str, assistant_message: str) -> None:
        """Add a user-assistant exchange to conversation history."""
        self.conversation_history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )

    def log_token_usage(self, step_num: int, tokens: int) -> None:
        """Log token usage for a step."""
        self.total_tokens_used += tokens

    def get_conversation_status(self) -> dict[str, Any]:
        """Get conversation status."""
        token_count = self.count_tokens(self.conversation_history)
        return {
            "model": self.model_name,
            "current_tokens": token_count,
            "limit": self.max_tokens,
            "fits": token_count <= self.max_tokens,
            "total_tokens_used": self.total_tokens_used,
            "should_trim": token_count > self.max_tokens * 0.8,
        }

    def trim_conversation(self, target_tokens: int | None = None) -> int:
        """Trim conversation history to fit within limits."""
        if target_tokens is None:
            target_tokens = int(self.max_tokens * 0.6)

        current_tokens = self.count_tokens(self.conversation_history)
        if current_tokens <= target_tokens:
            return current_tokens

        token_counts = [
            self.count_tokens(self.conversation_history[-i:] if i > 0 else [])
            for i in range(len(self.conversation_history) + 1)
        ]
        best_trim = max(0, bisect.bisect_right(token_counts, target_tokens) - 1)
        self.conversation_history[:] = self.conversation_history[-best_trim:]
        return self.count_tokens(self.conversation_history)

    def manage_conversation_tokens(
        self, logger_instance, episode_num: int, elapsed_minutes: float
    ) -> None:
        """Manage conversation tokens and perform trimming if needed."""
        status = self.get_conversation_status()

        if logger_instance:
            logger_instance._log(
                f"Episode {episode_num} (elapsed: {elapsed_minutes:.1f}m): {status['current_tokens']}/{status['limit']} tokens"
            )

        trim_threshold = int(self.max_tokens * 0.9)
        if status["current_tokens"] > trim_threshold:
            if logger_instance:
                logger_instance._log(f"Trimming conversation: {status['current_tokens']} tokens")
            trimmed = self.trim_conversation()
            if logger_instance:
                logger_instance._log(f"Trimmed to {trimmed} tokens")
        elif len(self.conversation_history) > 200:
            if logger_instance:
                logger_instance._log(
                    f"Episode-based trimming: {len(self.conversation_history)} messages"
                )
            self.conversation_history[:] = self.conversation_history[-150:]
            trimmed = self.count_tokens(self.conversation_history)
            if logger_instance:
                logger_instance._log(f"Kept last 150 messages ({trimmed} tokens)")


def get_provider_for_model(model: str) -> str:
    """Auto-detect provider from model name."""
    for pattern, provider in PROVIDER_PATTERNS.items():
        if model.startswith(pattern):
            return provider
    raise ValueError(f"Unknown model: {model}")


def create_llm(model_name: str, api_key: str | None = None, reasoning_effort: str | None = None, **kwargs) -> LiteLLM:
    """Create an LLM from model name."""
    if not api_key:
        provider = get_provider_for_model(model_name)
        api_key = os.getenv(API_KEY_ENV[provider])
        if not api_key:
            raise ValueError(f"API key not found for {model_name}")
    return LiteLLM(model_name, api_key, reasoning_effort=reasoning_effort)
