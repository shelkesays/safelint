"""Lint engine: orchestrates rule execution across files and directories."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from safelint.core.config import SafeLintConfig
from safelint.rules import build_rules
from safelint.rules.base import Rule, Violation


@dataclass(slots=True)
class LintResult:
    """Aggregated violations for a single linted file."""

    path: Path
    violations: list[Violation] = field(default_factory=list)


class SafeLintEngine:
    """Runs configured rules against Python source files."""

    def __init__(
        self, config: SafeLintConfig | None = None, rules: Sequence[Rule] | None = None
    ) -> None:
        """Initialise the engine with optional *config* and an explicit *rules* list."""
        self.config = config or SafeLintConfig()
        self.rules = list(rules or build_rules(self.config))

    def lint_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all Python files under a directory."""
        target = Path(path)
        files = [target] if target.is_file() else sorted(self._iter_python_files(target))
        return [self.lint_file(file_path) for file_path in files]

    def lint_file(self, path: str | Path) -> LintResult:
        """Parse and lint a single Python source file, returning its violations."""
        file_path = Path(path)
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        violations: list[Violation] = []
        for rule in self.rules:
            violations.extend(rule.check(file_path, tree, source))
        return LintResult(
            path=file_path, violations=sorted(violations, key=lambda item: (item.line, item.code))
        )

    def _iter_python_files(self, root: Path) -> Iterable[Path]:
        """Yield every ``.py`` file under *root* that passes include/exclude filters."""
        for candidate in root.rglob("*.py"):
            relative = candidate.relative_to(root).as_posix()
            if self._is_excluded(relative):
                continue
            if self._is_included(relative):
                yield candidate

    def _is_included(self, relative_path: str) -> bool:
        """Return ``True`` if *relative_path* matches at least one include pattern."""
        return any(self._matches_pattern(relative_path, pattern) for pattern in self.config.include)

    def _is_excluded(self, relative_path: str) -> bool:
        """Return ``True`` if *relative_path* matches at least one exclude pattern."""
        return any(self._matches_pattern(relative_path, pattern) for pattern in self.config.exclude)

    def _matches_pattern(self, relative_path: str, pattern: str) -> bool:
        """Return ``True`` if *relative_path* matches the glob *pattern*."""
        path = Path(relative_path)
        if path.match(pattern):
            return True
        if pattern.startswith("**/"):
            return path.match(pattern.removeprefix("**/"))
        return False
