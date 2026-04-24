"""Safety engine - orchestrates the active rule set against Python source files."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import fnmatch
import io
import logging
from pathlib import Path
import tokenize
from typing import TYPE_CHECKING, Any, Literal

from safelint.core.config import DEFAULTS, SEVERITY_ORDER
from safelint.rules import ALL_RULES
from safelint.rules.base import Violation
from safelint.rules.test_coverage import TestCouplingRule


if TYPE_CHECKING:
    from safelint.rules.base import BaseRule


_log = logging.getLogger(__name__)

# Applied only to real COMMENT tokens — not string literals.
# Matches:  # nosafe           (suppress all on this line)
#           # nosafe: SAFE101  (suppress specific code or rule name)
#           # nosafe: SAFE101, function_length  (comma-separated list)
_NOSAFE_PREFIX = "nosafe"


def _nosafe_codes(comment: str) -> set[str] | None | Literal[False]:
    """Parse a single comment token string and return the nosafe payload.

    Returns:
        ``None``           — bare ``# nosafe`` (suppress all on this line)
        ``set[str]``       — ``# nosafe: CODE, ...`` (suppress named codes/rules)
        ``Literal[False]`` — comment is not a nosafe directive, or is malformed
                             (e.g. ``# nosafe:`` with an empty payload)

    """
    body = comment[1:].strip()  # strip leading '#'
    if not body.lower().startswith(_NOSAFE_PREFIX):
        return False
    remainder = body[len(_NOSAFE_PREFIX) :].lstrip()
    if remainder == "":
        return None  # bare # nosafe
    if remainder.startswith(":"):
        codes_str = remainder[1:].strip()
        if not codes_str:
            # Malformed directive: "# nosafe:" with no codes or rule names
            _log.debug("Ignoring malformed nosafe directive with empty payload: %r", comment.strip())
            return False
        codes = {tok.strip() for tok in codes_str.split(",") if tok.strip()}
        if not codes:
            # Malformed directive: payload contains only commas/whitespace, no actual codes
            _log.debug(
                "Ignoring malformed nosafe directive with no usable codes: %r",
                comment.strip(),
            )
            return False
        return codes
    return False


def _parse_suppressions(source: str) -> dict[int, set[str] | None]:
    """Return a {lineno: codes} suppression map from real comment tokens only.

    Uses :mod:`tokenize` so that occurrences of ``# nosafe`` inside string
    literals are never mistaken for suppression comments.

    ``None`` means "suppress everything on this line" (bare ``# nosafe``).
    A ``set`` means suppress only the listed codes / rule names.
    Line numbers are 1-based.
    """
    try:
        token_list = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        # Incomplete source (e.g. mid-edit) — fall back to no suppressions
        _log.debug("tokenize failed while parsing suppressions; no suppressions applied")
        return {}

    suppressions: dict[int, set[str] | None] = {}
    for tok_type, tok_string, (lineno, _), _, _ in token_list:
        if tok_type != tokenize.COMMENT:
            continue
        payload = _nosafe_codes(tok_string)
        if payload is not False:
            suppressions[lineno] = payload
    return suppressions


def _is_suppressed(v: Violation, suppressions: dict[int, set[str] | None]) -> bool:
    """Return True when *v* is covered by a nosafe comment on its line."""
    if v.lineno not in suppressions:
        return False
    codes = suppressions[v.lineno]
    if codes is None:  # bare # nosafe
        return True
    return v.code in codes or v.rule in codes


def _is_per_file_ignored(v: Violation, pfi_names: frozenset[str], pfi_codes_upper: frozenset[str]) -> bool:
    """Return True when *v* is suppressed by a per-file ignore pattern."""
    return v.code.upper() in pfi_codes_upper or v.rule in pfi_names


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

        raw_ignore: list[str] = config.get("ignore", [])
        known_names: frozenset[str] = frozenset(cls.name for cls in ALL_RULES)
        known_codes_upper: frozenset[str] = frozenset(cls.code.upper() for cls in ALL_RULES)
        unknown = frozenset(e for e in raw_ignore if e not in known_names and e.upper() not in known_codes_upper)
        if unknown:
            _log.warning("Unknown entries in ignore list (typo or stale rule?): %s", ", ".join(sorted(unknown)))
        ignored_names: frozenset[str] = frozenset(raw_ignore)
        ignored_codes_upper: frozenset[str] = frozenset(e.upper() for e in raw_ignore)

        self.rules: list[BaseRule] = self._build_active_rules(rules_cfg, exec_cfg, ignored_names, ignored_codes_upper, changed_files)
        self.per_file_ignores: list[tuple[str, frozenset[str], frozenset[str]]] = self._parse_per_file_ignores(config.get("per_file_ignores", {}), known_names, known_codes_upper)

    @staticmethod
    def _build_active_rules(
        rules_cfg: dict[str, Any],
        exec_cfg: dict[str, Any],
        ignored_names: frozenset[str],
        ignored_codes_upper: frozenset[str],
        changed_files: list[str] | None,
    ) -> list[BaseRule]:
        """Return the ordered list of active rules derived from config."""
        order: list[str] = exec_cfg.get("order", [r.name for r in ALL_RULES])
        order_index: dict[str, int] = {name: i for i, name in enumerate(order)}
        active_rules: list[BaseRule] = []
        for cls in ALL_RULES:
            rule_cfg = dict(rules_cfg.get(cls.name, {}))
            default_enabled = DEFAULTS["rules"].get(cls.name, {}).get("enabled", True)
            if not rule_cfg.get("enabled", default_enabled):
                continue
            if cls.code.upper() in ignored_codes_upper or cls.name in ignored_names:
                continue
            if cls is TestCouplingRule and changed_files is not None:
                rule_cfg["_changed_files"] = changed_files
            active_rules.append(cls(rule_cfg))
        return sorted(active_rules, key=lambda r: order_index.get(r.name, len(order)))

    @staticmethod
    def _parse_per_file_ignores(
        raw_pfi: dict[str, list[str]],
        known_names: frozenset[str],
        known_codes_upper: frozenset[str],
    ) -> list[tuple[str, frozenset[str], frozenset[str]]]:
        """Validate and parse per_file_ignores config into (pattern, names, codes_upper) triples."""
        if not isinstance(raw_pfi, dict):
            msg = f"per_file_ignores must be a mapping, got {type(raw_pfi).__name__}"
            raise TypeError(msg)
        result: list[tuple[str, frozenset[str], frozenset[str]]] = []
        for pattern, entries in raw_pfi.items():
            if not isinstance(entries, (list, tuple)):
                msg = f"per_file_ignores[{pattern!r}] must be a list of strings, got {type(entries).__name__}"
                raise TypeError(msg)
            pfi_unknown = frozenset(e for e in entries if e not in known_names and e.upper() not in known_codes_upper)
            if pfi_unknown:
                _log.warning(
                    "Unknown entries in per_file_ignores[%r] (typo or stale rule?): %s",
                    pattern,
                    ", ".join(sorted(pfi_unknown)),
                )
            result.append((pattern, frozenset(entries), frozenset(e.upper() for e in entries)))
        return result

    def _is_excluded(self, filepath: str) -> bool:
        """Return True when *filepath* matches any configured exclusion pattern."""
        posix = Path(filepath).as_posix()
        return any(fnmatch.fnmatchcase(posix, pattern) for pattern in self.exclude_paths)

    def _file_ignored_set(self, filepath: str) -> tuple[frozenset[str], frozenset[str]]:
        """Return (names, codes_upper) accumulated from all per-file patterns matching *filepath*."""
        posix = Path(filepath).as_posix()
        names: set[str] = set()
        codes_upper: set[str] = set()
        for pattern, pfi_names, pfi_codes_upper in self.per_file_ignores:
            if fnmatch.fnmatchcase(posix, pattern):
                names |= pfi_names
                codes_upper |= pfi_codes_upper
        return frozenset(names), frozenset(codes_upper)

    def check_file(self, filepath: str) -> LintResult:
        """Parse *filepath*, run every active rule, apply inline suppressions, and return a :class:`LintResult`.

        .. note::
            **Breaking change (1.2.0):** this method previously returned
            ``list[Violation]``.  Callers that relied on the old return type
            must be updated to access ``result.violations`` instead.

        Violations are filtered by two suppression mechanisms, both of which
        count toward :attr:`LintResult.suppressed`:

        * **Inline** ``# nosafe`` comments (optionally with a comma-separated
          list of codes / rule names) suppress violations on a specific line.
        * **Per-file** ``per_file_ignores`` patterns suppress all violations
          whose code or name matches an entry for the file's path.

        When ``fail_fast`` is enabled the loop stops after the first rule that
        produces at least one violation that survives both filtering passes
        (i.e. not suppressed by either ``# nosafe`` or ``per_file_ignores``).
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

        suppressions = _parse_suppressions(source)
        pfi_names, pfi_codes_upper = self._file_ignored_set(filepath)

        active: list[Violation] = []
        suppressed = 0
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            after_nosafe = [v for v in rule_violations if not _is_suppressed(v, suppressions)]
            after_pfi = [v for v in after_nosafe if not _is_per_file_ignored(v, pfi_names, pfi_codes_upper)]
            suppressed += len(rule_violations) - len(after_pfi)
            active.extend(after_pfi)
            if self.fail_fast and after_pfi:
                break

        return LintResult(path=filepath, violations=active, suppressed=suppressed)

    def check_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all Python files under a directory."""
        target = Path(path)
        files = [str(target)] if target.is_file() else sorted(str(p) for p in target.rglob("*.py") if not self._is_excluded(str(p)))
        return [self.check_file(f) for f in files]

    @staticmethod
    def partition_violations(violations: list[Violation], fail_threshold: int) -> tuple[list[Violation], list[Violation]]:
        """Split violations into (blocking, advisory) lists based on *fail_threshold*."""
        blocking: list[Violation] = []
        advisory: list[Violation] = []
        for v in violations:
            if SEVERITY_ORDER.get(v.severity, 1) >= fail_threshold:
                blocking.append(v)
            else:
                advisory.append(v)
        return blocking, advisory
