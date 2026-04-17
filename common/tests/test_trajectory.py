"""Tests for TrajectoryWriter."""
import json
from pathlib import Path

import pytest

from common.trajectory import TrajectoryWriter
from common.schemas import SchemaError


class TestTrajectoryWriter:
    def test_writes_jsonl_one_event_per_line(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        writer = TrajectoryWriter(path)
        writer.write(
            step=1,
            ts="2026-04-16T14:22:08.123Z",
            type="reasoning",
            content="plan",
            tokens_in=10,
            tokens_out=5,
            latency_ms=100,
            cost_usd=0.001,
        )
        writer.write(
            step=1,
            ts="2026-04-16T14:22:09.000Z",
            type="tool_call",
            tool="bash",
            args={"cmd": "ls"},
            call_id="c_01",
        )
        writer.close()

        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "reasoning"
        assert json.loads(lines[1])["type"] == "tool_call"

    def test_truncates_tool_result_content_and_records_original_size(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        writer = TrajectoryWriter(path, max_content_bytes=100)
        big_content = "x" * 5000
        writer.write(
            step=1,
            ts="t",
            type="tool_result",
            call_id="c_01",
            status="success",
            exit_code=0,
            stdout_bytes=5000,
            content=big_content,
        )
        writer.close()

        event = json.loads(path.read_text().splitlines()[0])
        assert event["stdout_bytes"] == 5000
        assert len(event["content"]) < 5000
        assert event["content"].endswith("...[truncated]")

    def test_rejects_invalid_event(self, tmp_path):
        writer = TrajectoryWriter(tmp_path / "trajectory.jsonl")
        with pytest.raises(SchemaError):
            writer.write(step=1, ts="t", type="bogus")
        writer.close()

    def test_context_manager_closes_file(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        with TrajectoryWriter(path) as writer:
            writer.write(
                step=1,
                ts="t",
                type="reasoning",
                content="x",
                tokens_in=0,
                tokens_out=0,
                latency_ms=0,
                cost_usd=0.0,
            )
        # File should exist and contain exactly one line
        assert len(path.read_text().splitlines()) == 1

    def test_appends_to_existing_file(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        with TrajectoryWriter(path) as w1:
            w1.write(
                step=1, ts="t", type="reasoning", content="a",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        with TrajectoryWriter(path) as w2:
            w2.write(
                step=2, ts="t", type="reasoning", content="b",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        assert len(path.read_text().splitlines()) == 2

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "trajectory.jsonl"
        with TrajectoryWriter(path) as writer:
            writer.write(
                step=1, ts="t", type="reasoning", content="x",
                tokens_in=0, tokens_out=0, latency_ms=0, cost_usd=0.0,
            )
        assert path.exists()
