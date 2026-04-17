"""Tests for common.schemas type definitions and validators."""
import pytest

from common import schemas


class TestEventTypes:
    def test_event_types_constant_lists_all_four(self):
        assert set(schemas.EVENT_TYPES) == {"reasoning", "tool_call", "tool_result", "completion"}

    def test_completion_signals_constant(self):
        assert set(schemas.COMPLETION_SIGNALS) == {"task_complete", "timeout", "max_steps", "error"}


class TestValidateEvent:
    def test_valid_reasoning_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "reasoning",
            "content": "plan...",
            "tokens_in": 100,
            "tokens_out": 20,
            "latency_ms": 500,
            "cost_usd": 0.002,
        }
        schemas.validate_event(event)  # no raise

    def test_valid_tool_call_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "tool_call",
            "tool": "bash",
            "args": {"cmd": "ls"},
            "call_id": "c_01",
        }
        schemas.validate_event(event)

    def test_valid_tool_result_event_passes(self):
        event = {
            "step": 1,
            "ts": "2026-04-16T14:22:08.123Z",
            "type": "tool_result",
            "call_id": "c_01",
            "status": "success",
            "exit_code": 0,
            "stdout_bytes": 100,
            "content": "ok",
        }
        schemas.validate_event(event)

    def test_valid_completion_event_passes(self):
        event = {
            "step": 12,
            "ts": "2026-04-16T14:28:44.771Z",
            "type": "completion",
            "signal": "task_complete",
            "total_tokens_in": 1000,
            "total_tokens_out": 200,
            "total_cost_usd": 0.1,
            "wall_time_s": 100,
        }
        schemas.validate_event(event)

    def test_missing_envelope_field_raises(self):
        event = {"type": "reasoning", "content": "x"}  # missing step, ts
        with pytest.raises(schemas.SchemaError, match="step"):
            schemas.validate_event(event)

    def test_unknown_type_raises(self):
        event = {"step": 1, "ts": "x", "type": "bogus"}
        with pytest.raises(schemas.SchemaError, match="bogus"):
            schemas.validate_event(event)

    def test_missing_args_raises_with_specific_message(self):
        event = {"step": 1, "ts": "x", "type": "tool_call", "tool": "bash", "call_id": "c_01"}
        with pytest.raises(schemas.SchemaError, match="args"):
            schemas.validate_event(event)

    def test_missing_call_id_raises_with_specific_message(self):
        event = {"step": 1, "ts": "x", "type": "tool_call", "tool": "bash", "args": {}}
        with pytest.raises(schemas.SchemaError, match="call_id"):
            schemas.validate_event(event)

    def test_invalid_completion_signal_raises(self):
        event = {
            "step": 1,
            "ts": "x",
            "type": "completion",
            "signal": "bogus",
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost_usd": 0.0,
            "wall_time_s": 0,
        }
        with pytest.raises(schemas.SchemaError, match="signal"):
            schemas.validate_event(event)
