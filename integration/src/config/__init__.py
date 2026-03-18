"""Global configuration constants for apex-code."""

QWEN3_CODER_480B = "fireworks_ai/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct"
GEMINI_3_PRO_PREVIEW = "gemini/gemini-3-pro-preview"
GPT5_1_CODEX = "gpt-5.1-codex"

MODELS_NOT_SUPPORTING_TEMP = [
    "gpt-5",
    "gpt-5-codex",
    "gpt-5.1-codex",
]

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
