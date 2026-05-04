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

    *column_start* and *column_end* are 1-based column numbers (matching
    safelint's 1-based ``lineno`` convention and most editor display
    formats). Both default to ``None`` for two reasons:

    * **Backwards-compatible cache replay** — Violations cached by an
      older safelint version don't carry these fields; deserialising
      via ``Violation(**dict)`` works as long as the new fields have
      defaults.
    * **Some violations have no meaningful column** — synthetic
      ``SAFE000`` parse errors with ``lineno == 0`` fall back to
      ``column_start = column_end = None``.

    Editor integrations (Claude Code skill, VSCode plugin) treat
    ``None`` as "no column data, fall back to underlining the whole
    line"; ``column_start == column_end`` denotes a zero-width caret
    position (e.g. for "missing token" parse errors).
    """

    rule: str
    code: str
    filepath: str
    lineno: int
    message: str
    severity: str  # "error" | "warning"
    column_start: int | None = None
    column_end: int | None = None


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
        )

    def _make_violation_for_node(
        self,
        filepath: str,
        node: tree_sitter.Node,
        message: str,
    ) -> Violation:
        """Construct a Violation positioned at *node* (lineno + column range).

        Convenience wrapper: rules that have a Tree-sitter node in hand can
        skip the manual ``node.start_point[0] + 1`` plumbing and let this
        helper extract lineno + 1-based start/end columns. Equivalent to::

            line, col_s, col_e = node_range(node)
            self._make_violation(path, line, msg, column_start=col_s, column_end=col_e)
        """
        from safelint.languages._node_utils import node_range  # noqa: PLC0415

        line, col_s, col_e = node_range(node)
        return self._make_violation(filepath, line, message, column_start=col_s, column_end=col_e)

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
