"""Base types shared by all safelint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from safelint.languages._node_utils import call_name


if TYPE_CHECKING:
    import tree_sitter


@dataclass(frozen=True)
class TextEdit:
    """An advisory single-range source-code edit.

    Half-open ``[start_line:start_column, end_line:end_column)`` range
    using safelint's 1-based line/column convention (matches
    :class:`Violation` position fields). ``replacement`` is the literal
    text that *would* go in place of the current range — but safelint
    never applies it. Editors / Claude Code may surface it as a
    "Quick Fix" code action subject to user confirmation.
    """

    start_line: int
    start_column: int
    end_line: int
    end_column: int
    replacement: str


@dataclass(frozen=True)
class Suggestion:
    """An advisory fix the rule offers for a violation.

    Suggestions are *never* applied automatically — safelint is a
    review tool, not a refactoring tool. Editor integrations and CI
    consumers may surface them as "Quick Fix" code actions, but every
    edit goes through user confirmation.

    * ``description`` — one-line human-readable label for the suggestion
      (shown in editor "Quick Fix" menus). Should fit on one line; the
      rule's ``message`` already explains the *what*, the description
      explains the *fix*.
    * ``edits`` — zero or more :class:`TextEdit` describing the minimal
      change that would make the rule pass. Empty when the suggestion
      is informational only (e.g. "extract a helper function" — too
      ambiguous to render as a single edit).
    """

    description: str
    edits: tuple[TextEdit, ...] = ()


@dataclass(frozen=True)
class Violation:
    """A single rule violation produced during static analysis.

    Position fields form a fully-specified ``[start, end)`` range
    matching LSP / VSCode ``Range`` and SARIF ``region`` semantics:

    * ``lineno`` (1-based) — start line. Required, always set.
    * ``end_lineno`` (1-based) — end line. ``None`` when the violation
      has no meaningful span (parse errors with no node, file-level
      violations like ``test_existence``). When set and equal to
      ``lineno``, the construct is single-line.
    * ``column_start`` (1-based) — start column on ``lineno``. ``None``
      when no Tree-sitter node was available.
    * ``column_end`` (1-based, exclusive) — end column on
      ``end_lineno``. ``None`` mirrors ``column_start``.

    Only the additional position fields (``end_lineno``,
    ``column_start``, ``column_end``) default to ``None``. ``lineno``
    is required and always set. The defaults exist for two reasons:

    * **Backwards-compatible cache replay** — Violations cached by an
      older safelint version don't carry these additional fields;
      deserialising via ``Violation(**dict)`` works as long as the
      new fields have defaults.
    * **Some violations have no span** — synthetic ``SAFE000`` parse
      errors with ``lineno == 0`` and missing-file violations have
      no Tree-sitter node to position against.

    Editor integrations treat ``column_start == None`` as "no column
    data, underline the whole line" and ``column_start == column_end``
    as a zero-width caret (e.g. parse-error markers). For multi-line
    constructs (``end_lineno > lineno``), ``column_end`` is the end
    column on ``end_lineno``, not on ``lineno`` — earlier 1.7.0 work
    omitted ``end_lineno`` and editors mistakenly assumed
    ``column_end`` was on the start line, highlighting the wrong span.
    """

    rule: str
    code: str
    filepath: str
    lineno: int
    message: str
    severity: str  # "error" | "warning"
    column_start: int | None = None
    column_end: int | None = None
    end_lineno: int | None = None
    # Advisory fixes (never applied automatically — safelint is a review
    # tool, not a refactoring tool). Editor integrations and CI consumers
    # may surface these as "Quick Fix" code actions subject to user
    # confirmation. Empty tuple = no suggestions for this violation.
    suggestions: tuple[Suggestion, ...] = ()


class BaseRule(ABC):
    """Pluggable safety rule that analyses a parsed Tree-sitter tree and returns violations."""

    name: str = ""
    code: str = ""

    #: Languages this rule applies to. The engine consults this before
    #: dispatching ``check_file`` and skips the rule entirely for files
    #: whose ``LanguageDefinition.name`` isn't listed.
    #:
    #: Default ``("python",)`` keeps every existing rule Python-only —
    #: which is the correct default for today's codebase, where the
    #: rules import Python-specific Tree-sitter node-type constants
    #: from :mod:`safelint.languages.python`. When safelint adds a
    #: second language, contributors widen this on a per-rule basis
    #: (cross-language portable rules become e.g.
    #: ``language = ("python", "typescript")``; Python-only-syntax
    #: rules like ``bare_except`` stay narrow).
    #:
    #: This is the engine-side half of the per-language dispatch
    #: contract documented in ``ADDING_A_LANGUAGE.md``. The other half
    #: (per-language rule classes vs. runtime dispatch within a rule's
    #: ``check_file``) is per-rule design and ships *with* each new
    #: language, not as part of the engine plumbing.
    language: tuple[str, ...] = ("python",)

    def __init__(self, config: dict[str, Any]) -> None:
        """Bind rule-specific config and resolve severity."""
        self.config = config
        self.severity: str = config.get("severity", "error")

    @abstractmethod
    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Analyse *tree* (parsed from *filepath*) and return every violation found."""

    def _make_violation(
        self,
        filepath: str,
        lineno: int,
        message: str,
        *,
        column_start: int | None = None,
        column_end: int | None = None,
        end_lineno: int | None = None,
    ) -> Violation:
        """Construct a Violation tagged with this rule's name, code, and severity."""
        return Violation(
            rule=self.name,
            code=self.code,
            filepath=filepath,
            lineno=lineno,
            message=message,
            severity=self.severity,
            column_start=column_start,
            column_end=column_end,
            end_lineno=end_lineno,
        )

    def _make_violation_for_node(
        self,
        filepath: str,
        node: tree_sitter.Node,
        message: str,
    ) -> Violation:
        """Construct a Violation positioned at *node*.

        Extracts the full 4-coordinate span — start line, end line, start
        column, end column — so consumers can render the precise range
        even for multi-line constructs (function definitions, except
        clauses, while loops). All four are 1-based.
        """
        from safelint.languages._node_utils import node_range  # noqa: PLC0415

        start_line, end_line, col_s, col_e = node_range(node)
        return self._make_violation(
            filepath,
            start_line,
            message,
            column_start=col_s,
            column_end=col_e,
            end_lineno=end_line,
        )

    @staticmethod
    def _call_name(call_node: tree_sitter.Node) -> str | None:  # pragma: no cover
        """Return the bare callable name from a ``call`` node, or None if unresolvable.

        Pass the call node itself (not the function sub-node).
        Handles ``foo(...)`` → ``"foo"`` and ``obj.method(...)`` → ``"method"``.

        Legacy alias retained for backward-compat with rules that called
        ``self._call_name(...)`` directly. New code uses the module-level
        ``call_name`` from ``safelint.languages._node_utils``.
        """
        return call_name(call_node)
