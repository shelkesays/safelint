"""Safety engine - orchestrates the active rule set against source files."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from safelint.core import _cache, _diagnostics
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

# Codes / names emitted directly by the engine rather than by a registered
# BaseRule. They're recognised in the user's ``ignore`` list (so e.g.
# ``ignore = ["SAFE004"]`` disables unused-suppression warnings) without
# triggering the typo-guard warning that fires for codes outside
# ``ALL_RULES``.
_ENGINE_INTERNAL_CODES = frozenset({"SAFE000", "SAFE004"})
_ENGINE_INTERNAL_NAMES = frozenset({"parse", "unused_suppression"})


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


def _check_suppressed_marking_used(
    violation: Violation,
    suppressions: dict[int, set[str] | None],
    used: set[tuple[int, str | None]],
) -> bool:
    """Match :func:`_is_suppressed` and record which directive caught *violation*.

    *used* receives ``(lineno, None)`` for bare ``# nosafe`` hits, or
    ``(lineno, code_or_rule_name)`` for ``# nosafe: <code>`` hits. After
    all rules run, the entries in ``suppressions`` *not* present in
    *used* are the directives that didn't actually silence anything —
    the engine emits SAFE004 (``unused_suppression``) warnings for those.
    """
    if violation.lineno not in suppressions:
        return False
    codes = suppressions[violation.lineno]
    if codes is None:
        used.add((violation.lineno, None))
        return True
    if violation.code in codes:
        used.add((violation.lineno, violation.code))
        return True
    if violation.rule in codes:
        used.add((violation.lineno, violation.rule))
        return True
    return False


def _is_per_file_ignored(violation: Violation, ignored_names: frozenset[str], ignored_codes: frozenset[str]) -> bool:
    """Return True when *violation* is suppressed by a per-file ignore pattern."""
    return violation.code.upper() in ignored_codes or violation.rule in ignored_names


def _make_unused_suppression(filepath: str, lineno_: int, message: str) -> Violation:
    """Build a ``SAFE004`` violation for an unused inline suppression directive."""
    return Violation(
        rule="unused_suppression",
        code="SAFE004",
        filepath=filepath,
        lineno=lineno_,
        message=message,
        severity="warning",
        end_lineno=lineno_,
    )


def _unused_violations_for_line(
    filepath: str,
    lineno_: int,
    codes: set[str] | None,
    used: set[tuple[int, str | None]],
) -> list[Violation]:
    """Return SAFE004 violations for the directive(s) on a single line.

    Bare ``# nosafe`` (codes=None) emits one violation if no rule fired
    on that line. Coded ``# nosafe: A, B`` emits one violation per
    individual code that didn't catch anything.

    Self-referential directives are skipped to avoid recursive
    reports. Inline suppressions accept either the SAFE-code or the
    rule-name (see :func:`_check_suppressed_marking_used`), so we
    skip *both* representations of SAFE004 here:

    * ``# nosafe: SAFE004`` (any case)
    * ``# nosafe: unused_suppression`` (the rule name)
    """
    if codes is None:
        if (lineno_, None) in used:
            return []
        return [_make_unused_suppression(filepath, lineno_, "this `# nosafe` directive did not suppress any violation")]
    # Iterate in sorted order so multiple SAFE004 violations on the
    # same line (e.g. ``# nosafe: SAFE101, SAFE102, SAFE103``) come out
    # in stable alphabetical sequence — JSON/SARIF consumers rely on
    # deterministic per-run ordering, and ``set[str]`` iteration is
    # hash-randomised across processes.
    return [
        _make_unused_suppression(filepath, lineno_, f"`# nosafe: {code}` did not suppress any violation")
        for code in sorted(codes)
        if not _is_safe004_self_reference(code) and (lineno_, code) not in used
    ]


def _is_safe004_self_reference(code: str) -> bool:
    """Return True when *code* refers to SAFE004 by either its code or rule name.

    A *deliberate* leniency, narrower than the rest of the engine: this
    helper accepts either the canonical ``SAFE004`` (case-insensitive,
    so ``safe004`` / ``Safe004`` are also recognised) or the
    ``unused_suppression`` rule name. Inline ``# nosafe:`` matching at
    :func:`_is_suppressed` and :func:`_check_suppressed_marking_used`
    is otherwise *case-sensitive* on codes — the global ``ignore``
    config list is normalised to upper-case at load time, but per-line
    inline directives are matched verbatim. Treating the SAFE004
    self-reference more leniently is intentional: a directive whose
    only purpose is to silence the SAFE004 rule itself shouldn't
    recursively trigger SAFE004 just because the user typed it
    lowercase.
    """
    return code.upper() == "SAFE004" or code == "unused_suppression"


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
        cache: _cache.LintCache | None = None,
    ) -> None:
        """Build the ordered, active rule set from *config*.

        *cache* is an optional :class:`safelint.core._cache.LintCache`. If
        provided (and not pointing at ``None``), per-file lint results are
        memoised by ``sha256(source + engine_fingerprint + filepath)`` so
        re-runs on unchanged files become essentially instant. Pass
        ``None`` (the default) to disable caching.
        """
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
        known_names: frozenset[str] = frozenset(cls.name for cls in ALL_RULES) | _ENGINE_INTERNAL_NAMES
        known_codes_upper: frozenset[str] = frozenset(cls.code.upper() for cls in ALL_RULES) | _ENGINE_INTERNAL_CODES
        unknown = frozenset(e for e in raw_ignore if e not in known_names and e.upper() not in known_codes_upper)
        if unknown:
            _diagnostics.print_warning(f"unknown entries in ignore list (typo or stale rule?): {', '.join(sorted(unknown))}")
        ignored_names: frozenset[str] = frozenset(raw_ignore)
        ignored_codes_upper: frozenset[str] = frozenset(e.upper() for e in raw_ignore)

        self.rules: list[BaseRule] = self._build_active_rules(rules_cfg, exec_cfg, ignored_names, ignored_codes_upper, changed_files)
        self.per_file_ignores: list[tuple[str, frozenset[str], frozenset[str]]] = self._parse_per_file_ignores(config.get("per_file_ignores", {}), known_names, known_codes_upper)
        self._cache = cache
        # Combined ignore-set for engine-internal violations (SAFE000 parse
        # errors, SAFE004 unused-suppression). Includes both the upper-cased
        # codes *and* the rule names from the ignore list, so users can write
        # either ``ignore = ["SAFE004"]`` or ``ignore = ["unused_suppression"]``
        # and have it work. Rule-based BaseRule violations go through their
        # own filter at ``_build_active_rules``; this set is consulted only
        # for the codes the engine emits directly.
        self._globally_ignored_engine_internal: frozenset[str] = ignored_codes_upper | ignored_names
        # Lazy: only computed when the cache is non-trivial — saves the
        # JSON-encode + sha256 round-trip when ``--no-cache`` is in use.
        self._engine_fingerprint: str | None = None

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
    def _parse_error_result(
        filepath: str,
        message: str,
        lineno: int = 0,
        column: int | None = None,
    ) -> LintResult:
        """Build a LintResult carrying a single SAFE000 parse-error violation.

        *column* is the 1-based column of the offending token; when supplied
        it becomes a zero-width caret (``column_start == column_end``) on
        ``end_lineno == lineno`` so editors can render a precise marker
        rather than underlining the whole line.
        """
        end = lineno if column is not None else None
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
                    column_start=column,
                    column_end=column,
                    end_lineno=end,
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
            if node.is_missing:  # pragma: no cover
                return node.start_point[0] + 1, node.start_point[1], f"missing {node.type!r}"
            if node.type == "ERROR":
                return node.start_point[0] + 1, node.start_point[1], "syntax error"
            # Pre-order DFS: push reversed so the first original child pops first.
            stack.extend(reversed(node.children))
        # Defensive: the outer caller only invokes this when ``has_error``
        # is True, which means at least one ERROR or MISSING node exists
        # somewhere — but the loop below could in principle skip it if
        # the parser produces an unusual tree shape. Falling back to None
        # makes the message a generic "could not parse" without a location.
        return None  # pragma: no cover

    @staticmethod
    def _partition_rule_output(
        rule_violations: list[Violation],
        suppressions: dict[int, set[str] | None],
        ignored_names: frozenset[str],
        ignored_codes: frozenset[str],
        used_suppressions: set[tuple[int, str | None]],
    ) -> tuple[list[Violation], list[Violation]]:
        """Split a single rule's output into (active, suppressed) violation lists.

        *used_suppressions* is mutated in place: every inline-suppressed
        violation contributes a ``(lineno, code_or_rule_or_None)`` entry,
        which the engine inspects after the run to flag any directive
        that didn't actually catch anything as ``SAFE004``.
        """
        active: list[Violation] = []
        suppressed: list[Violation] = []
        for v in rule_violations:
            if _check_suppressed_marking_used(v, suppressions, used_suppressions) or _is_per_file_ignored(v, ignored_names, ignored_codes):
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
        used_suppressions: set[tuple[int, str | None]],
    ) -> tuple[list[Violation], list[Violation], bool]:
        """Run active rules against *tree*, returning (active, suppressed, stopped_early).

        *stopped_early* is True when ``fail_fast`` caused the rule loop
        to short-circuit on a hit. The caller uses this to suppress the
        SAFE004 (``unused_suppression``) pass: if later rules never
        ran, we don't yet know whether their corresponding ``# nosafe``
        directives were truly unused or just blocked from firing.
        """
        active: list[Violation] = []
        suppressed: list[Violation] = []
        stopped_early = False
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            rule_active, rule_suppressed = self._partition_rule_output(rule_violations, suppressions, ignored_names, ignored_codes, used_suppressions)
            active.extend(rule_active)
            suppressed.extend(rule_suppressed)
            if self.fail_fast and rule_active:
                stopped_early = True
                break
        return active, suppressed, stopped_early

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
        # Stat denial / device read errors: fail-open so read_text reports
        # the real underlying issue as a SAFE000 violation. Practically
        # untestable without fault injection.
        except OSError:  # nosafe: SAFE203
            return None
        if not is_regular:
            _diagnostics.print_warning(f"skipping {filepath} (not a regular file)")
            return LintResult(path=filepath)
        try:
            size = path_obj.stat().st_size
        # Same fail-open posture as is_file() above.
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

        If a cache is configured, this method consults it before parsing
        and stores the result on miss. The cache key folds in the engine
        fingerprint (rules + their config + safelint version) *and* the
        filepath itself, so two files with identical contents under
        different paths never share an entry. Any config change invalidates
        entries automatically.
        """
        source_bytes = source.encode("utf-8")
        cache_key = self._cache_key_for(filepath, source_bytes)
        if cache_key is not None and self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return self._apply_cached(filepath, cached)

        tree = lang.create_parser().parse(source_bytes)
        if tree.root_node.has_error:
            # Honour ``ignore = ["SAFE000"]`` / ``ignore = ["parse"]``.
            # Parse errors are emitted by the engine, not by a registered
            # BaseRule, so their suppression is handled here directly.
            if self._engine_internal_ignored("SAFE000", "parse"):
                return LintResult(path=filepath, violations=[], suppressed=[])
            return self._build_parse_error_result(filepath, tree.root_node)

        suppressions = _parse_suppressions(tree, lang.comment_node_type, lang.comment_prefix)
        ignored_names, ignored_codes = self._file_ignored_set(filepath)
        used_suppressions: set[tuple[int, str | None]] = set()
        active, suppressed, stopped_early = self._run_rules(filepath, tree, suppressions, ignored_names, ignored_codes, used_suppressions)
        # Skip the SAFE004 unused-suppression pass when ``fail_fast``
        # short-circuited the rule loop: ``used_suppressions`` is
        # incomplete in that case (later rules never got to mark their
        # directives as used), so emitting SAFE004 would falsely report
        # directives for un-run rules as "unused".
        if not stopped_early:
            self._append_unused_suppressions(filepath, suppressions, used_suppressions, active, suppressed, ignored_names, ignored_codes)
        if cache_key is not None and self._cache is not None:
            self._cache.put(cache_key, active, suppressed)
        return LintResult(path=filepath, violations=active, suppressed=suppressed)

    def _cache_key_for(self, filepath: str, source_bytes: bytes) -> str | None:
        """Return the cache key for *filepath* / *source_bytes*, or None if cache is disabled."""
        if self._cache is None or self._cache.cache_dir is None:
            return None
        return _cache.compute_file_key(source_bytes, self._get_engine_fingerprint(), filepath)

    def _build_parse_error_result(self, filepath: str, root: tree_sitter.Node) -> LintResult:
        """Construct the SAFE000 ``LintResult`` for a tree with parse errors.

        Parse errors aren't cached: they're typically transient (a file
        mid-edit), and re-parsing a still-broken buffer is cheap — Tree-sitter
        bails on the first ERROR/MISSING node, so the cost saved by caching
        wouldn't be material against the extra read/JSON-parse round-trip.
        """
        location = self._first_parse_error(root)
        if location is None:  # pragma: no cover
            return self._parse_error_result(filepath, "Parse error: tree-sitter could not fully parse this file", lineno=0, column=None)
        line, col, kind = location
        msg = f"Parse error ({kind}) at line {line}, column {col + 1} - check syntax near this location"
        return self._parse_error_result(filepath, msg, lineno=line, column=col + 1)

    def _append_unused_suppressions(
        self,
        filepath: str,
        suppressions: dict[int, set[str] | None],
        used_suppressions: set[tuple[int, str | None]],
        active: list[Violation],
        suppressed: list[Violation],
        ignored_names: frozenset[str],
        ignored_codes: frozenset[str],
    ) -> None:
        """Generate SAFE004 warnings for unused directives and route them to *active* / *suppressed*."""
        if self._engine_internal_ignored("SAFE004", "unused_suppression"):
            return
        for v in self._unused_suppression_violations(filepath, suppressions, used_suppressions):
            target = suppressed if _is_per_file_ignored(v, ignored_names, ignored_codes) else active
            target.append(v)

    def _engine_internal_ignored(self, code: str, name: str) -> bool:
        """Return True when an engine-internal violation is ignored globally.

        Engine-internal codes (SAFE000 parse, SAFE004 unused_suppression)
        don't go through the rule-filter path, so the user's ``ignore``
        list is consulted directly here. Both *code* (e.g. ``"SAFE000"``)
        and *name* (e.g. ``"parse"``) are accepted — the comparison is
        case-insensitive on the code and exact on the name, matching how
        the BaseRule pipeline treats them.
        """
        return code.upper() in self._globally_ignored_engine_internal or name in self._globally_ignored_engine_internal

    @staticmethod
    def _unused_suppression_violations(
        filepath: str,
        suppressions: dict[int, set[str] | None],
        used: set[tuple[int, str | None]],
    ) -> list[Violation]:
        """Return ``SAFE004`` violations for ``# nosafe`` directives that didn't fire.

        For each declared directive, check whether *any* violation hit it. If
        not, emit a warning so the user can clean up stale annotations after
        a refactor. ``# nosafe: SAFE004`` is special-cased — a directive that
        only mentions SAFE004 is always considered "used" to avoid recursive
        self-reporting.
        """
        violations: list[Violation] = []
        for lineno_, codes in suppressions.items():
            violations.extend(_unused_violations_for_line(filepath, lineno_, codes, used))
        return violations

    def _apply_cached(self, filepath: str, cached: tuple[list[Violation], list[Violation]]) -> LintResult:
        """Build a LintResult from a cache hit.

        The cache key folds in everything that affects what gets reported
        for this file:

        * source bytes — inline ``# nosafe`` directives live in source.
        * filepath — path-dependent rules (``test_existence``,
          ``test_coupling``) and ``Violation.filepath`` itself.
        * engine fingerprint — safelint version, schema version, the
          active rule set + per-rule config (so CLI ``--ignore`` /
          top-level ``ignore`` already invalidate, since they remove
          rules from ``self.rules``), *and* the ``per_file_ignores``
          mapping (so adding/removing/editing a glob entry between
          runs invalidates the affected entries).

        With all of that in the key, a hit means the cached lists are
        already correctly partitioned for the current call — no
        post-hit re-filter needed. An earlier version re-applied
        ``per_file_ignores`` here, but that was both redundant *and*
        wrong: it only walked the cached active list, never the
        suppressed list, so loosening ``per_file_ignores`` would
        wrongly leave previously suppressed violations suppressed.
        Folding the dict into the fingerprint fixes both issues.
        """
        cached_violations, cached_suppressed = cached
        return LintResult(path=filepath, violations=cached_violations, suppressed=cached_suppressed)

    def _get_engine_fingerprint(self) -> str:
        """Return (and lazily compute) the cache fingerprint for this engine."""
        if self._engine_fingerprint is None:
            # Local import to avoid the engine ↔ package-init circular
            # path (``safelint/__init__.py`` re-exports SafetyEngine and
            # also wants ``__version__``). Lazy lookup is fine here:
            # called at most once per engine instance.
            from safelint import __version__  # noqa: PLC0415

            self._engine_fingerprint = _cache.compute_engine_fingerprint(
                __version__,
                ((r.name, r.code, r.severity, r.config) for r in self.rules),
                per_file_ignores=((p, sorted(names), sorted(codes)) for p, names, codes in self.per_file_ignores),
                # Engine-internal codes (SAFE000 parse, SAFE004 unused
                # suppression) aren't part of ``self.rules``, so without
                # this the cache wouldn't notice when the user toggles
                # ``ignore = ["SAFE004"]`` between runs and would
                # re-serve the previously emitted SAFE004 violations.
                engine_internal_ignored=self._globally_ignored_engine_internal,
            )
        return self._engine_fingerprint

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
