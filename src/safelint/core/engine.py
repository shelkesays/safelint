"""Safety engine - orchestrates the active rule set against source files."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from safelint.core import _diagnostics
from safelint.core.config import DEFAULTS, SEVERITY_ORDER
from safelint.languages import get_language_for_file, supported_extensions
from safelint.languages._node_utils import lineno as node_lineno
from safelint.languages._node_utils import node_text, walk
from safelint.rules import ALL_RULES
from safelint.rules.base import Violation
from safelint.rules.test_coverage import TestCouplingRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import BaseRule


_NOSAFE_PREFIX = "nosafe"


def _nosafe_codes(comment: str, prefix: str = "#") -> set[str] | None | Literal[False]:
    """Parse a single comment string and return the nosafe payload.

    Returns:
        ``None``           — bare nosafe (suppress everything on this line)
        ``set[str]``       — nosafe: CODE, ... (suppress named codes/rules)
        ``Literal[False]`` — not a nosafe directive, or malformed

    """
    body = comment[len(prefix) :].strip()
    if not body.lower().startswith(_NOSAFE_PREFIX):
        return False
    remainder = body[len(_NOSAFE_PREFIX) :].lstrip()
    if remainder == "":
        return None
    if remainder.startswith(":"):
        codes_str = remainder[1:].strip()
        if not codes_str:
            return False
        codes = {tok.strip() for tok in codes_str.split(",") if tok.strip()}
        if not codes:
            return False
        return codes
    return False


def _parse_suppressions(
    tree: tree_sitter.Tree,
    comment_node_type: str,
    comment_prefix: str,
) -> dict[int, set[str] | None]:
    """Return a {lineno: codes} suppression map by querying comment nodes in the Tree-sitter tree.

    This replaces the old tokenize-based implementation. Because Tree-sitter
    parses comment nodes as first-class tree nodes, there is no risk of
    confusing a nosafe directive inside a string literal with a real one.

    ``comment_node_type`` and ``comment_prefix`` come from the LanguageDefinition,
    so this function works for any language without modification.
    """
    suppressions: dict[int, set[str] | None] = {}
    for node in walk(tree.root_node):
        if node.type != comment_node_type:
            continue
        comment_text = node_text(node)
        payload = _nosafe_codes(comment_text, prefix=comment_prefix)
        if payload is not False:
            suppressions[node_lineno(node)] = payload
    return suppressions


def _is_suppressed(violation: Violation, suppressions: dict[int, set[str] | None]) -> bool:
    """Return True when *violation* is covered by a nosafe comment on its line."""
    if violation.lineno not in suppressions:
        return False
    codes = suppressions[violation.lineno]
    if codes is None:
        return True
    return violation.code in codes or violation.rule in codes


def _is_per_file_ignored(violation: Violation, ignored_names: frozenset[str], ignored_codes: frozenset[str]) -> bool:
    """Return True when *violation* is suppressed by a per-file ignore pattern."""
    return violation.code.upper() in ignored_codes or violation.rule in ignored_names


@dataclass
class LintResult:
    """Aggregated violations for a single linted file.

    ``suppressed`` is the list of violations that were filtered out by inline
    ``# nosafe`` directives or per-file ignore patterns. Use ``len(...)`` for
    the count and iterate to inspect codes/rules/lines.
    """

    path: str
    violations: list[Violation] = field(default_factory=list)
    suppressed: list[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        """Return True when at least one violation was found."""
        return bool(self.violations)


class SafetyEngine:
    """Orchestrates the active rule set against a collection of source files."""

    def __init__(
        self,
        config: dict[str, Any],
        changed_files: list[str] | None = None,
    ) -> None:
        """Build the ordered, active rule set from *config*."""
        rules_cfg: dict[str, Any] = config.get("rules", {})
        exec_cfg: dict[str, Any] = config.get("execution", {})
        self.fail_fast: bool = exec_cfg.get("fail_fast", False)
        self.exclude_paths: list[str] = config.get("exclude_paths", [])

        raw_ignore: list[str] = config.get("ignore", [])
        known_names: frozenset[str] = frozenset(cls.name for cls in ALL_RULES)
        known_codes_upper: frozenset[str] = frozenset(cls.code.upper() for cls in ALL_RULES)
        unknown = frozenset(e for e in raw_ignore if e not in known_names and e.upper() not in known_codes_upper)
        if unknown:
            _diagnostics.print_warning(f"unknown entries in ignore list (typo or stale rule?): {', '.join(sorted(unknown))}")
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
            unknown_entries = frozenset(e for e in entries if e not in known_names and e.upper() not in known_codes_upper)
            if unknown_entries:
                _diagnostics.print_warning(f"unknown entries in per_file_ignores[{pattern!r}] (typo or stale rule?): {', '.join(sorted(unknown_entries))}")
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
        for pattern, ignored_names, ignored_codes in self.per_file_ignores:
            if fnmatch.fnmatchcase(posix, pattern):
                names |= ignored_names
                codes_upper |= ignored_codes
        return frozenset(names), frozenset(codes_upper)

    @staticmethod
    def _parse_error_result(filepath: str, message: str, lineno: int = 0) -> LintResult:
        """Build a LintResult carrying a single SAFE000 parse-error violation."""
        return LintResult(
            path=filepath,
            violations=[
                Violation(
                    rule="parse",
                    code="SAFE000",
                    filepath=filepath,
                    lineno=lineno,
                    message=message,
                    severity="error",
                )
            ],
        )

    @staticmethod
    def _first_parse_error(root: tree_sitter.Node) -> tuple[int, int, str] | None:
        """Return ``(lineno, column, kind)`` for the earliest parse-error node, else None.

        Walks every child (named *and* anonymous) because Tree-sitter records
        missing-token errors on anonymous nodes. Prunes subtrees whose
        ``has_error`` is False, so the traversal stays cheap on mostly-valid
        files. ``lineno`` is 1-based; ``column`` is 0-based to match
        Tree-sitter's own coordinates.
        """
        stack: list[tree_sitter.Node] = [root]
        while stack:  # nosafe: SAFE501
            node = stack.pop()
            if not node.has_error:
                continue
            if node.is_missing:
                return node.start_point[0] + 1, node.start_point[1], f"missing {node.type!r}"
            if node.type == "ERROR":
                return node.start_point[0] + 1, node.start_point[1], "syntax error"
            # Pre-order DFS: push reversed so the first original child pops first.
            stack.extend(reversed(node.children))
        return None

    @staticmethod
    def _partition_rule_output(
        rule_violations: list[Violation],
        suppressions: dict[int, set[str] | None],
        ignored_names: frozenset[str],
        ignored_codes: frozenset[str],
    ) -> tuple[list[Violation], list[Violation]]:
        """Split a single rule's output into (active, suppressed) violation lists."""
        active: list[Violation] = []
        suppressed: list[Violation] = []
        for v in rule_violations:
            if _is_suppressed(v, suppressions) or _is_per_file_ignored(v, ignored_names, ignored_codes):
                suppressed.append(v)
            else:
                active.append(v)
        return active, suppressed

    def _run_rules(
        self,
        filepath: str,
        tree: tree_sitter.Tree,
        suppressions: dict[int, set[str] | None],
        ignored_names: frozenset[str],
        ignored_codes: frozenset[str],
    ) -> tuple[list[Violation], list[Violation]]:
        """Run active rules against *tree*, returning (active, suppressed) violation lists."""
        active: list[Violation] = []
        suppressed: list[Violation] = []
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            rule_active, rule_suppressed = self._partition_rule_output(rule_violations, suppressions, ignored_names, ignored_codes)
            active.extend(rule_active)
            suppressed.extend(rule_suppressed)
            if self.fail_fast and rule_active:
                break
        return active, suppressed

    def check_file(self, filepath: str) -> LintResult:
        """Parse *filepath*, run every active rule, apply inline suppressions, return a LintResult."""
        if self._is_excluded(filepath):
            return LintResult(path=filepath)

        lang = get_language_for_file(filepath)
        if lang is None:
            return LintResult(path=filepath)

        try:
            source = Path(filepath).read_text(encoding="utf-8")
        # Read failures are surfaced to the user as a SAFE000 parse-error
        # violation — the error is reported, not swallowed.
        except (OSError, UnicodeDecodeError) as exc:  # nosafe: SAFE203
            return self._parse_error_result(filepath, f"Read error: {exc}")

        tree = lang.create_parser().parse(source.encode("utf-8"))
        if tree.root_node.has_error:
            location = self._first_parse_error(tree.root_node)
            if location is None:
                msg = "Parse error: tree-sitter could not fully parse this file"
                err_lineno = 0
            else:
                line, col, kind = location
                # column is reported 1-based to match common editor convention.
                msg = f"Parse error ({kind}) at line {line}, column {col + 1} - check syntax near this location"
                err_lineno = line
            return self._parse_error_result(filepath, msg, lineno=err_lineno)

        suppressions = _parse_suppressions(tree, lang.comment_node_type, lang.comment_prefix)
        ignored_names, ignored_codes = self._file_ignored_set(filepath)
        active, suppressed = self._run_rules(filepath, tree, suppressions, ignored_names, ignored_codes)
        return LintResult(path=filepath, violations=active, suppressed=suppressed)

    def _discover_files(self, target: Path) -> list[str]:
        """Return every supported source file under *target*, deduplicated and sorted."""
        seen: set[str] = set()
        for ext in supported_extensions():
            for path in target.rglob(f"*{ext}"):
                seen.add(str(path))
        return sorted(p for p in seen if not self._is_excluded(p))

    def check_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all supported files under a directory."""
        target = Path(path)
        files = [str(target)] if target.is_file() else self._discover_files(target)
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
