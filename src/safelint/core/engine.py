"""Safety engine - orchestrates the active rule set against Python source files."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from safelint.core.config import DEFAULTS, SEVERITY_ORDER
from safelint.rules import ALL_RULES
from safelint.rules.base import BaseRule, Violation
from safelint.rules.test_coverage import TestCouplingRule

_log = logging.getLogger(__name__)


@dataclass
class LintResult:
    """Aggregated violations for a single linted file."""

    path: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Return True when at least one violation was found."""
        return bool(self.violations)


class SafetyEngine:
    """Orchestrates the active rule set against a collection of Python files."""

    def __init__(
        self,
        config: dict[str, Any],
        changed_files: list[str] | None = None,
    ) -> None:
        """Build the ordered, active rule set from *config*.

        Rules are sorted by ``execution.order``; rules not listed there are
        appended at the end. Disabled rules are excluded entirely.
        ``changed_files`` is injected into test-coupling rules that need it.
        """
        rules_cfg: dict[str, Any] = config.get("rules", {})
        exec_cfg: dict[str, Any] = config.get("execution", {})
        self.fail_fast: bool = exec_cfg.get("fail_fast", False)
        self.exclude_paths: list[str] = config.get("exclude_paths", [])

        order: list[str] = exec_cfg.get("order", [r.name for r in ALL_RULES])
        order_index: dict[str, int] = {name: i for i, name in enumerate(order)}

        active_rules: list[BaseRule] = []
        for cls in ALL_RULES:
            rule_cfg = dict(rules_cfg.get(cls.name, {}))
            default_enabled = DEFAULTS["rules"].get(cls.name, {}).get("enabled", True)
            if not rule_cfg.get("enabled", default_enabled):
                continue
            if cls is TestCouplingRule and changed_files is not None:
                rule_cfg["_changed_files"] = changed_files
            active_rules.append(cls(rule_cfg))

        self.rules: list[BaseRule] = sorted(
            active_rules,
            key=lambda r: order_index.get(r.name, len(order)),
        )

    def _is_excluded(self, filepath: str) -> bool:
        """Return True when *filepath* matches any configured exclusion pattern."""
        p = Path(filepath)
        return any(p.match(pattern) for pattern in self.exclude_paths)

    def check_file(self, filepath: str) -> list[Violation]:
        """Parse *filepath*, run every active rule, and return all violations.

        When ``fail_fast`` is enabled the loop stops after the first rule that
        produces at least one violation.
        """
        if self._is_excluded(filepath):
            return []
        try:
            source = Path(filepath).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, OSError) as exc:
            _log.debug("Failed to parse %s: %s", filepath, exc)
            return [
                Violation(
                    rule="parse",
                    code="SAFE000",
                    filepath=filepath,
                    lineno=0,
                    message=f"Parse error: {exc}",
                    severity="error",
                )
            ]

        violations: list[Violation] = []
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            violations.extend(rule_violations)
            if self.fail_fast and rule_violations:
                break
        return violations

    def check_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all Python files under a directory."""
        target = Path(path)
        if target.is_file():
            files = [str(target)]
        else:
            files = sorted(str(p) for p in target.rglob("*.py") if not self._is_excluded(str(p)))
        return [LintResult(path=f, violations=self.check_file(f)) for f in files]

    def partition_violations(
        self, violations: list[Violation], fail_threshold: int
    ) -> tuple[list[Violation], list[Violation]]:
        """Split violations into (blocking, advisory) lists based on *fail_threshold*."""
        blocking: list[Violation] = []
        advisory: list[Violation] = []
        for v in violations:
            if SEVERITY_ORDER.get(v.severity, 1) >= fail_threshold:
                blocking.append(v)
            else:
                advisory.append(v)
        return blocking, advisory
