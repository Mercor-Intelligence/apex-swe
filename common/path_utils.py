"""Helpers for locating the apex-swe-harness repo root and wiring up sys.path."""
from __future__ import annotations

import sys
from pathlib import Path


def repo_root() -> Path:
    """Return the absolute path to the apex-swe-harness repo root."""
    # This file lives at <repo>/common/path_utils.py
    return Path(__file__).resolve().parent.parent


def prepend_repo_root_to_path() -> None:
    """Prepend the repo root to sys.path if not already present."""
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
