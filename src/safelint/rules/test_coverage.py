"""Test-coverage rules: test_existence and test_coupling (disabled by default)."""

from __future__ import annotations

import ast
from pathlib import Path

from safelint.rules.base import BaseRule, Violation


class TestExistenceRule(BaseRule):
    """Verify that a corresponding test file exists for every checked module."""

    name = "test_existence"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:  # noqa: ARG002
        """Return a violation when no test_<module>.py file can be found."""
        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
        src = Path(filepath)
        test_name = f"test_{src.stem}.py"
        for test_dir in test_dirs:
            if list(Path(test_dir).rglob(test_name)):
                return []
        dirs = ", ".join(test_dirs)
        return [
            self._v(
                filepath,
                0,
                f"No test file found for {src.name} — expected {test_name} under {dirs}/",
            )
        ]


class TestCouplingRule(BaseRule):
    """Require that when a src file changes, its test file also changes.

    Unlike ``test_existence``, this rule checks coupling: if you touched the
    source you must touch the tests. The engine injects ``_changed_files``
    (the full list of files being checked) into the rule config before running.
    """

    name = "test_coupling"

    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:  # noqa: ARG002
        """Return a violation when the paired test file was not part of this commit."""
        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
        changed: set[str] = set(self.config.get("_changed_files", []))
        src = Path(filepath)
        test_name = f"test_{src.stem}.py"

        # If no test file exists at all, defer to test_existence
        test_exists = any(list(Path(d).rglob(test_name)) for d in test_dirs)
        if not test_exists:
            return []

        if not any(test_name in f for f in changed):
            dirs = ", ".join(test_dirs)
            return [
                self._v(
                    filepath,
                    0,
                    f"{src.name} changed but {test_name} was not updated"
                    f" — tests must be updated alongside source changes (under {dirs}/)",
                )
            ]
        return []
