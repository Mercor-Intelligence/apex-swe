"""Tests for sys.path helper."""
import sys
from pathlib import Path

from common.path_utils import prepend_repo_root_to_path, repo_root


class TestPathUtils:
    def test_repo_root_returns_apex_swe_harness_dir(self):
        root = repo_root()
        assert root.name == "apex-swe-harness"
        assert (root / "integration").is_dir()
        assert (root / "observability").is_dir()
        assert (root / "common").is_dir()

    def test_prepend_idempotent(self):
        """Calling prepend twice must not add a duplicate entry.

        Note: we can't assert the entry appears exactly once, because pytest's
        rootdir insertion and other conftests may have also added it.
        We only verify that prepend_repo_root_to_path doesn't grow sys.path.
        """
        root = repo_root()
        prepend_repo_root_to_path()
        count_first = sum(1 for p in sys.path if p == str(root))
        assert count_first >= 1
        prepend_repo_root_to_path()
        count_second = sum(1 for p in sys.path if p == str(root))
        assert count_first == count_second
