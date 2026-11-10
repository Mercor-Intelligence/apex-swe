"""Global configuration constants for apex-code."""

MODELS_OMIT_TEMP = [
    "claude-opus-4-8",
]

MODELS_NOT_SUPPORTING_TEMP = [
    "gpt-5",
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5.5-pro",
]

# Models that support extended thinking / reasoning
# Maps model prefix -> default reasoning effort level
MODELS_SUPPORTING_REASONING = {
    # OpenAI: uses reasoning_effort param
    "o1": "high",
    "o3": "high",
    "gpt-5-codex": "high",
    "gpt-5.1-codex": "high",
    "gpt-5.2": "high",
    "gpt-5.2-codex": "high",
    "gpt-5.3": "high",
    "gpt-5.3-codex": "high",
    "gpt-5.4": "high",
    "gpt-5.5": "high",
    "gpt-5.5-pro": "high",
    # xAI: uses reasoning_effort param (same as OpenAI)
    "xai/grok-4": "high",
    # Anthropic: uses thinking param with budget_tokens
    "claude-opus-4-5": "high",
    "claude-opus-4-6": "high",
    "claude-sonnet-4-5": "high",
    "claude-sonnet-4-6": "high",
    # Google: uses thinking_config
    "gemini/gemini-2.5-pro": "high",
    "gemini/gemini-2.5-flash": "high",
    "gemini/gemini-3": "high",
}

# Map reasoning effort level -> Anthropic thinking budget_tokens
ANTHROPIC_THINKING_BUDGETS = {
    "low": 5_000,
    "medium": 10_000,
    "high": 32_000,
}

# Map reasoning effort level -> Gemini thinking budget
GEMINI_THINKING_BUDGETS = {
    "low": 2_048,
    "medium": 8_192,
    "high": 32_768,
}

DEFAULT_TEMPERATURE = 0.1
REQUIRED_TEMPERATURE_1_0 = 1.0

SERVICES_WITH_MCP: dict[str, str] = {
    "zammad": "zammad",
    "mattermost": "mattermost",
    "plane-api": "plane",
    "plane": "plane",
    "grafana": "grafana",
    "prometheus": "prometheus",
    "espocrm": "espocrm",
    "medusa": "medusa",
}
