"""Safety engine - orchestrates the active rule set against source files."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
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

    from safelint.languages._types import LanguageDefinition
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
        self.max_file_size_bytes: int = self._resolve_max_file_size_bytes(config)

        raw_ignore = config.get("ignore", [])
        if not isinstance(raw_ignore, (list, tuple)):
            msg = f"ignore must be a list of strings, got {type(raw_ignore).__name__}"
            raise TypeError(msg)
        non_strings = [e for e in raw_ignore if not isinstance(e, str)]
        if non_strings:
            bad = ", ".join(f"{type(e).__name__}({e!r})" for e in non_strings)
            msg = f"ignore must contain only strings — got: {bad}"
            raise TypeError(msg)
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
    def _resolve_max_file_size_bytes(config: dict[str, Any]) -> int:
        """Validate ``max_file_size_bytes`` from *config* and return the resolved value.

        Rules:
        * Must be a non-negative integer (``bool`` is rejected since it
          subclasses ``int`` — ``true`` would silently coerce to ``1``).
        * Negative values raise ``ValueError`` with a clear message.
        * ``0`` would defeat the OOM guard entirely; treat it as a likely
          typo, emit a stderr warning, and fall back to the built-in
          default rather than silently disabling the safety net.
        """
        raw_max = config.get("max_file_size_bytes", DEFAULTS["max_file_size_bytes"])
        if not isinstance(raw_max, int) or isinstance(raw_max, bool):
            msg = f"max_file_size_bytes must be a non-negative integer, got {type(raw_max).__name__}"
            raise TypeError(msg)
        if raw_max < 0:
            msg = f"max_file_size_bytes must be >= 0, got {raw_max}"
            raise ValueError(msg)
        if raw_max == 0:
            default = DEFAULTS["max_file_size_bytes"]
            _diagnostics.print_warning(
                f"max_file_size_bytes = 0 is not supported — it would read every file unbounded and defeat "
                f"the OOM guard. Falling back to the built-in default of {default:,} bytes. "
                f"To allow larger files, set a positive value explicitly (e.g. 50_000_000 for 50 MB)."
            )
            return default
        return raw_max

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
            non_strings = [e for e in entries if not isinstance(e, str)]
            if non_strings:
                bad = ", ".join(f"{type(e).__name__}({e!r})" for e in non_strings)
                msg = f"per_file_ignores[{pattern!r}] must contain only strings — got: {bad}"
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

    def _is_excluded_dir(self, dir_path: Path) -> bool:
        """Return True when *dir_path* should be pruned during walk descent.

        Tests the directory candidate in two forms against each pattern:

        * **Without trailing slash** (``"src/legacy"``) — supports patterns
          that name a specific directory exactly, e.g.
          ``exclude_paths = ["src/legacy"]``.
        * **With trailing slash** (``"src/legacy/"``) — supports the very
          common ``/**`` glob, e.g. ``exclude_paths = ["tests/**"]``.
          ``fnmatch.fnmatchcase('tests', 'tests/**')`` is ``False`` because
          the pattern requires a literal ``/`` after ``tests``; appending
          the slash explicitly lets the prune fire as users naturally
          expect.

        Files are still matched without modification via ``_is_excluded``
        at the per-file step, so file-level patterns are unaffected.
        """
        bare = dir_path.as_posix().rstrip("/")
        with_slash = bare + "/"
        return any(fnmatch.fnmatchcase(bare, pattern) or fnmatch.fnmatchcase(with_slash, pattern) for pattern in self.exclude_paths)

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

    def _pre_read_skip(self, filepath: str, path_obj: Path) -> LintResult | None:
        """Return an empty LintResult to skip *filepath*, or None to proceed.

        Catches the two pre-read conditions that mean we shouldn't even
        attempt to read the file:

        * **Non-regular path** — FIFOs, device files, broken symlinks.
          ``check_file`` is also called via CLI hook mode with an explicit
          file list (bypassing ``_discover_files``'s filter), so a FIFO
          path passed straight in would block ``read_text`` forever.
        * **Oversize input** — files larger than ``max_file_size_bytes``
          would OOM the process when fully read.

        Stat failures fall through to the read path so the user sees a
        real ``SAFE000`` parse-error rather than a misleading skip.
        """
        try:
            is_regular = path_obj.is_file()
        except OSError:  # nosafe: SAFE203
            # Can't stat — let read_text produce a SAFE000 with the
            # actual error rather than guess at "not a regular file".
            return None
        if not is_regular:
            _diagnostics.print_warning(f"skipping {filepath} (not a regular file)")
            return LintResult(path=filepath)
        try:
            size = path_obj.stat().st_size
        except OSError:  # nosafe: SAFE203
            return None
        if size > self.max_file_size_bytes:
            _diagnostics.print_warning(f"skipping {filepath} ({size:,} bytes exceeds max_file_size_bytes={self.max_file_size_bytes:,})")
            return LintResult(path=filepath)
        return None

    def check_file(self, filepath: str) -> LintResult:
        """Parse *filepath* from disk, run every active rule, return a LintResult.

        Use :meth:`check_source` instead when you already have the source
        in memory (e.g. an editor's unsaved buffer fed via ``--stdin``).
        """
        if self._is_excluded(filepath):
            return LintResult(path=filepath)

        lang = get_language_for_file(filepath)
        if lang is None:
            return LintResult(path=filepath)

        path_obj = Path(filepath)
        skip = self._pre_read_skip(filepath, path_obj)
        if skip is not None:
            return skip

        try:
            source = path_obj.read_text(encoding="utf-8")
        # Read failures are surfaced to the user as a SAFE000 parse-error
        # violation — the error is reported, not swallowed.
        except (OSError, UnicodeDecodeError) as exc:  # nosafe: SAFE203
            return self._parse_error_result(filepath, f"Read error: {exc}")

        return self._lint_parsed_source(filepath, source, lang)

    def check_source(self, filepath: str, source: str) -> LintResult:
        """Lint pre-loaded *source* as if it came from *filepath*.

        Used by editor integrations and the ``--stdin`` mode: the caller
        has the buffer contents in memory and doesn't want safelint to
        re-read from disk. The pre-read pre-checks (size guard, regular
        file guard) are skipped since by definition the source is already
        in hand. Exclusion and language detection still apply because
        config-driven excludes and unsupported extensions still mean
        "no lint".
        """
        if self._is_excluded(filepath):
            return LintResult(path=filepath)

        lang = get_language_for_file(filepath)
        if lang is None:
            return LintResult(path=filepath)

        return self._lint_parsed_source(filepath, source, lang)

    def _lint_parsed_source(self, filepath: str, source: str, lang: LanguageDefinition) -> LintResult:
        """Inner: parse *source* with *lang*'s parser and run rules.

        Caller has already done exclusion and language lookup. Used by
        both :meth:`check_file` (after a disk read) and :meth:`check_source`
        (with a caller-provided buffer).
        """
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

    def _walk_supported_files(self, target: Path, ext_tuple: tuple[str, ...]) -> set[str]:
        """Return the set of regular-file paths under *target* whose name ends with one of *ext_tuple*.

        Uses ``os.walk(..., followlinks=False)`` so symlink cycles
        (e.g. ``a/sub -> ..``) cannot cause infinite descent: when this
        flag is off, ``os.walk`` does not follow symlinks to
        subdirectories during descent. Matches what ruff and flake8
        do by default.

        ``os.walk`` lists every non-directory entry in *filenames*, which
        includes FIFOs, sockets, device files, and broken symlinks. The
        ``is_file()`` guard drops those — calling ``read_text()`` on a
        FIFO would block the process forever, and reading a device file
        is undefined behaviour. The stat cost is bounded to suffix
        matches (the cheap string check runs first).

        Excluded subtrees (matching ``exclude_paths`` glob patterns) are
        pruned during descent by mutating ``dirnames`` in place — saves
        the cost of walking large excluded trees like ``node_modules``,
        ``.venv``, or ``build/`` when the user has explicit directory
        excludes. Files matching exclude patterns are still filtered
        at the per-file step (handles patterns that target file names
        rather than directories).
        """
        seen: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
            dir_path = Path(dirpath)
            # In-place mutation tells os.walk which subdirs to descend into.
            # Use the directory-aware excluder so ``tests/**``-style globs
            # prune at descent time (not just per-file at the end).
            dirnames[:] = [d for d in dirnames if not self._is_excluded_dir(dir_path / d)]
            # Two-stage generator: build the joined Path once per suffix
            # match, then filter on ``is_file()`` using that same object.
            # Avoids constructing ``dir_path / name`` twice and keeps the
            # comprehension readable.
            candidates = (dir_path / name for name in filenames if name.endswith(ext_tuple))
            seen.update(str(p) for p in candidates if p.is_file())
        return seen

    def _discover_files(self, target: Path) -> list[str]:
        """Return every supported source file under *target*, deduplicated and sorted."""
        # Pre-build a tuple for ``str.endswith`` so the per-file check
        # stays a cheap string operation (no Path() construction per name).
        ext_tuple = tuple(supported_extensions())
        seen = self._walk_supported_files(target, ext_tuple)
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
