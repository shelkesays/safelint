"""Safety engine - orchestrates the active rule set against Python source files."""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from safelint.core.config import DEFAULTS, SEVERITY_ORDER
from safelint.rules import ALL_RULES
from safelint.rules.base import BaseRule, Violation
from safelint.rules.test_coverage import TestCouplingRule

_log = logging.getLogger(__name__)

# Matches:  # nosafe           (suppress all on this line)
#           # nosafe: SAFE101  (suppress specific code or rule name)
#           # nosafe: SAFE101, function_length  (comma-separated list)
_NOSAFE_RE = re.compile(r"#\s*nosafe(?::\s*(.+))?", re.IGNORECASE)


def _parse_suppressions(source: str) -> dict[int, set[str] | None]:
    """Return a {lineno: codes} suppression map parsed from inline comments.

    ``None`` means "suppress everything on this line" (bare ``# nosafe``).
    A ``set`` means suppress only the listed codes / rule names.
    Line numbers are 1-based.
    """
    suppressions: dict[int, set[str] | None] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _NOSAFE_RE.search(line)
        if not m:
            continue
        raw = m.group(1)
        if raw:
            suppressions[lineno] = {tok.strip() for tok in raw.split(",") if tok.strip()}
        else:
            suppressions[lineno] = None  # bare # nosafe → suppress all
    return suppressions


def _is_suppressed(v: Violation, suppressions: dict[int, set[str] | None]) -> bool:
    """Return True when *v* is covered by a nosafe comment on its line."""
    if v.lineno not in suppressions:
        return False
    codes = suppressions[v.lineno]
    if codes is None:  # bare # nosafe
        return True
    return v.code in codes or v.rule in codes


@dataclass
class LintResult:
    """Aggregated violations for a single linted file."""

    path: str
    violations: list[Violation] = field(default_factory=list)
    suppressed: int = 0

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

    def check_file(self, filepath: str) -> LintResult:
        """Parse *filepath*, run every active rule, apply inline suppressions, and
        return a LintResult.

        Violations on lines that carry a ``# nosafe`` comment (optionally
        followed by a comma-separated list of codes / rule names) are filtered
        out and counted in :attr:`LintResult.suppressed` instead of appearing
        in :attr:`LintResult.violations`.

        When ``fail_fast`` is enabled the loop stops after the first rule that
        produces at least one violation.
        """
        if self._is_excluded(filepath):
            return LintResult(path=filepath)
        try:
            source = Path(filepath).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filepath)
        except (SyntaxError, OSError) as exc:
            _log.debug("Failed to parse %s: %s", filepath, exc)
            return LintResult(
                path=filepath,
                violations=[
                    Violation(
                        rule="parse",
                        code="SAFE000",
                        filepath=filepath,
                        lineno=0,
                        message=f"Parse error: {exc}",
                        severity="error",
                    )
                ],
            )

        raw: list[Violation] = []
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            raw.extend(rule_violations)
            if self.fail_fast and rule_violations:
                break

        suppressions = _parse_suppressions(source)
        active = [v for v in raw if not _is_suppressed(v, suppressions)]
        return LintResult(path=filepath, violations=active, suppressed=len(raw) - len(active))

    def check_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all Python files under a directory."""
        target = Path(path)
        if target.is_file():
            files = [str(target)]
        else:
            files = sorted(str(p) for p in target.rglob("*.py") if not self._is_excluded(str(p)))
        return [self.check_file(f) for f in files]

    @staticmethod
    def partition_violations(
        violations: list[Violation], fail_threshold: int
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
