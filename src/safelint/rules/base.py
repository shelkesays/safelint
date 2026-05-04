"""Base types shared by all safelint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from safelint.languages._node_utils import call_name


if TYPE_CHECKING:
    import tree_sitter


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

    All four position fields default to ``None`` for two reasons:

    * **Backwards-compatible cache replay** — Violations cached by an
      older safelint version don't carry these fields; deserialising
      via ``Violation(**dict)`` works as long as new fields have
      defaults.
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


class BaseRule(ABC):
    """Pluggable safety rule that analyses a parsed Tree-sitter tree and returns violations."""

    name: str = ""
    code: str = ""

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
