#!/usr/bin/env python3
"""
Export observability eval logs to delivery format.

Extracts system_prompt, messages (OpenAI format), tool_calls, prompt/request,
response, language, domain, and model_name from inspect-ai .eval files.

Usage:
    # Export a specific eval log
    python export_delivery.py --eval-log eval_logs/<file>.eval --output exports/

    # Export most recent run for a model
    python export_delivery.py --task 0xpolygon-bor-1710-enhanced-observability --model claude-opus-4-6 --output exports/

    # Export all runs for a task
    python export_delivery.py --task 0xpolygon-bor-1710-enhanced-observability --all-models --output exports/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


# Paths
SCRIPT_DIR = Path(__file__).parent
TASKS_DIR = SCRIPT_DIR / "tasks"
EVAL_LOGS_DIR = SCRIPT_DIR / "eval_logs"


@dataclass
class DeliveryEntry:
    """Single delivery entry conforming to the output spec."""
    system_prompt: str
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    prompt: str          # Original user query / task instruction
    response: str        # Final model response
    language: str        # Programming language (go, python, etc.)
    domain: str          # Domain classification
    model_name: str      # Exact model version


def load_eval_log(eval_path: Path) -> dict[str, Any]:
    """Load an inspect-ai .eval log (ZIP archive)."""
    with zipfile.ZipFile(eval_path) as z:
        header = json.loads(z.read("header.json"))
        sample = json.loads(z.read("samples/1_epoch_1.json"))
    return {"header": header, "sample": sample}


def load_task_metadata(task_id: str) -> dict[str, Any]:
    """Load language/domain metadata from task files."""
    metadata = {
        "language": "",
        "domain": "software-engineering",
        "category": "software-engineering",
        "tags": [],
    }

    # Derive clean task name (strip trailing _N from inspect task naming)
    clean_task_id = re.sub(r"_\d+$", "", task_id)

    task_dir = TASKS_DIR / clean_task_id
    if not task_dir.exists():
        return metadata

    # test_metadata.json has language
    test_meta_path = task_dir / "test_metadata.json"
    if test_meta_path.exists():
        try:
            with open(test_meta_path) as f:
                test_meta = json.load(f)
            metadata["language"] = test_meta.get("language", "")
        except (json.JSONDecodeError, OSError):
            pass

    # task.yaml has category/tags
    task_yaml_path = task_dir / "task.yaml"
    if task_yaml_path.exists():
        try:
            with open(task_yaml_path) as f:
                task_data = yaml.safe_load(f)
            metadata["category"] = task_data.get("category", "software-engineering")
            metadata["tags"] = task_data.get("tags", [])
        except (yaml.YAMLError, OSError):
            pass

    # Build domain from category + tags
    tags = metadata.get("tags", [])
    if "mcp" in tags or "observability" in tags:
        metadata["domain"] = "observability"
    elif "integration" in tags:
        metadata["domain"] = "integration"
    else:
        metadata["domain"] = metadata.get("category", "software-engineering")

    return metadata


def extract_system_prompt(messages: list[dict]) -> str:
    """Extract the system prompt from the message list."""
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Concatenate text parts
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                return "\n".join(parts)
    return ""


def extract_prompt(messages: list[dict]) -> str:
    """Extract the original user prompt/request (first user message)."""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        parts.append(item)
                return "\n".join(parts)
    return ""


def extract_final_response(messages: list[dict]) -> str:
    """Extract the final assistant response (last assistant message with text content)."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                if text_parts:
                    return "\n".join(text_parts)
    return ""


def normalize_content(content: Any) -> str | list[dict]:
    """Normalize message content to OpenAI-compatible format.

    - Plain strings pass through.
    - Lists of content items are filtered to only include types that OpenAI
      recognizes (text, image_url).  Reasoning blocks (from Anthropic extended
      thinking) are stripped from the main content but their *summary* is
      preserved as a text block so no semantic information is lost.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        normalized: list[dict] = []
        for item in content:
            if isinstance(item, str):
                normalized.append({"type": "text", "text": item})
            elif isinstance(item, dict):
                ctype = item.get("type", "")
                if ctype == "text":
                    normalized.append({"type": "text", "text": item.get("text", "")})
                elif ctype == "reasoning":
                    # Preserve the human-readable summary, drop the encrypted blob
                    summary = item.get("summary", "")
                    if summary:
                        normalized.append({
                            "type": "text",
                            "text": f"[Reasoning summary]: {summary}",
                        })
                elif ctype == "image_url":
                    normalized.append(item)
                # Skip other types (redacted, etc.)
        return normalized if len(normalized) != 1 else normalized[0].get("text", normalized)

    return str(content)


def convert_tool_call(tc: dict) -> dict:
    """Convert an inspect-ai tool call to OpenAI-compatible format."""
    return {
        "id": tc.get("id", ""),
        "type": "function",
        "function": {
            "name": tc.get("function", ""),
            "arguments": json.dumps(tc.get("arguments", {})),
        },
    }


def build_openai_messages(raw_messages: list[dict]) -> list[dict[str, Any]]:
    """Convert inspect-ai message list to standard OpenAI messages format."""
    openai_messages = []

    for msg in raw_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            openai_messages.append({
                "role": "system",
                "content": normalize_content(content),
            })

        elif role == "user":
            openai_messages.append({
                "role": "user",
                "content": normalize_content(content),
            })

        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant"}

            # Normalize content
            normalized = normalize_content(content)
            if normalized:
                entry["content"] = normalized
            else:
                entry["content"] = None  # OpenAI requires content field

            # Tool calls
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                entry["tool_calls"] = [convert_tool_call(tc) for tc in tool_calls]

            openai_messages.append(entry)

        elif role == "tool":
            entry = {
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": normalize_content(content),
            }
            openai_messages.append(entry)

    return openai_messages


def collect_all_tool_calls(raw_messages: list[dict]) -> list[dict[str, Any]]:
    """Collect all tool invocations with their results, paired by tool_call_id."""
    # Build map of tool_call_id -> tool result
    result_map: dict[str, dict] = {}
    for msg in raw_messages:
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id", "")
            if tcid:
                result_map[tcid] = {
                    "tool_call_id": tcid,
                    "function": msg.get("function", ""),
                    "result": normalize_content(msg.get("content", "")),
                }

    # Collect all tool calls from assistant messages
    all_calls = []
    for msg in raw_messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tcid = tc.get("id", "")
                call_entry = {
                    "id": tcid,
                    "type": "function",
                    "function": {
                        "name": tc.get("function", ""),
                        "arguments": tc.get("arguments", {}),
                    },
                    "result": result_map.get(tcid, {}).get("result", ""),
                }
                all_calls.append(call_entry)

    return all_calls


def export_eval_log(eval_path: Path, task_id_override: str | None = None) -> DeliveryEntry:
    """Export a single eval log to delivery format."""
    data = load_eval_log(eval_path)
    header = data["header"]
    sample = data["sample"]

    raw_messages = sample.get("messages", [])
    eval_info = header.get("eval", {})
    model_name = eval_info.get("model", "unknown")

    # Task ID from header or override
    task_name = eval_info.get("task", "")
    task_id = task_id_override or re.sub(r"_\d+$", "", task_name)

    # Load task metadata for language/domain
    task_meta = load_task_metadata(task_id)

    return DeliveryEntry(
        system_prompt=extract_system_prompt(raw_messages),
        messages=build_openai_messages(raw_messages),
        tool_calls=collect_all_tool_calls(raw_messages),
        prompt=extract_prompt(raw_messages),
        response=extract_final_response(raw_messages),
        language=task_meta.get("language", ""),
        domain=task_meta.get("domain", "software-engineering"),
        model_name=model_name,
    )


def find_eval_logs(
    task_id: str | None = None,
    model: str | None = None,
    latest_only: bool = True,
) -> list[Path]:
    """Find matching eval log files."""
    if not EVAL_LOGS_DIR.exists():
        return []

    candidates = sorted(EVAL_LOGS_DIR.glob("*.eval"), key=lambda p: p.stat().st_mtime, reverse=True)
    results = []

    for path in candidates:
        try:
            with zipfile.ZipFile(path) as z:
                if "header.json" not in z.namelist():
                    continue
                header = json.loads(z.read("header.json"))
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError):
            continue

        eval_info = header.get("eval", {})
        log_model = eval_info.get("model", "")
        log_task = re.sub(r"_\d+$", "", eval_info.get("task", ""))

        if task_id and task_id not in log_task:
            continue
        if model and model not in log_model:
            continue

        results.append(path)
        if latest_only and model:
            break  # Got the most recent match

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Export observability eval logs to delivery format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--eval-log", type=Path, help="Path to a specific .eval file")
    source.add_argument("--task", help="Task ID to search for in eval_logs/")

    parser.add_argument("--model", help="Filter by model name (substring match)")
    parser.add_argument("--all-models", action="store_true", help="Export all models for the task")
    parser.add_argument("--output", "-o", type=Path, default=Path("exports"), help="Output directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    # Find eval logs
    if args.eval_log:
        if not args.eval_log.exists():
            print(f"Error: File not found: {args.eval_log}", file=sys.stderr)
            sys.exit(1)
        eval_logs = [args.eval_log]
    else:
        latest_only = not args.all_models
        eval_logs = find_eval_logs(
            task_id=args.task,
            model=args.model if not args.all_models else None,
            latest_only=latest_only,
        )
        if not eval_logs:
            print(f"Error: No eval logs found for task={args.task} model={args.model}", file=sys.stderr)
            sys.exit(1)

    # Export
    args.output.mkdir(parents=True, exist_ok=True)

    for eval_path in eval_logs:
        print(f"Exporting: {eval_path.name}")
        try:
            entry = export_eval_log(eval_path, task_id_override=args.task)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            continue

        # Build output filename
        safe_model = entry.model_name.replace("/", "_")
        timestamp = eval_path.stem.split("_")[0] if "_" in eval_path.stem else "unknown"
        out_name = f"{safe_model}__{args.task or 'unknown'}__{timestamp}.json"
        out_path = args.output / out_name

        indent = 2 if args.pretty else None
        with open(out_path, "w") as f:
            json.dump(asdict(entry), f, indent=indent, ensure_ascii=False)

        msg_count = len(entry.messages)
        tc_count = len(entry.tool_calls)
        print(f"  -> {out_path}")
        print(f"     model={entry.model_name} lang={entry.language} domain={entry.domain}")
        print(f"     messages={msg_count} tool_calls={tc_count}")
        print(f"     system_prompt={len(entry.system_prompt)} chars")
        print(f"     prompt={len(entry.prompt)} chars")
        print(f"     response={len(entry.response)} chars")
        print()

    print(f"Done. {len(eval_logs)} entries exported to {args.output}/")


if __name__ == "__main__":
    main()
