"""Schema definitions and validators for trajectory events, layer results, and trial results."""
from __future__ import annotations

EVENT_TYPES = ("reasoning", "tool_call", "tool_result", "completion")
COMPLETION_SIGNALS = ("task_complete", "timeout", "max_steps", "error")

_ENVELOPE_FIELDS = ("step", "ts", "type")

_TYPE_REQUIRED_FIELDS = {
    "reasoning": ("content", "tokens_in", "tokens_out", "latency_ms", "cost_usd"),
    "tool_call": ("tool", "args", "call_id"),
    "tool_result": ("call_id", "status", "exit_code", "stdout_bytes", "content"),
    "completion": ("signal", "total_tokens_in", "total_tokens_out", "total_cost_usd", "wall_time_s"),
}


class SchemaError(ValueError):
    """Raised when a trajectory event fails validation."""


def validate_event(event: dict) -> None:
    """Validate a trajectory event dict. Raises SchemaError on failure."""
    for field in _ENVELOPE_FIELDS:
        if field not in event:
            raise SchemaError(f"missing required envelope field: {field!r}")
    event_type = event["type"]
    if event_type not in EVENT_TYPES:
        raise SchemaError(f"unknown event type: {event_type!r} (valid: {EVENT_TYPES})")
    for field in _TYPE_REQUIRED_FIELDS[event_type]:
        if field not in event:
            raise SchemaError(f"missing field {field!r} for event type {event_type!r}")
    if event_type == "completion" and event["signal"] not in COMPLETION_SIGNALS:
        raise SchemaError(
            f"invalid completion signal: {event['signal']!r} (valid: {COMPLETION_SIGNALS})"
        )
