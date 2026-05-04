"""function_length rule - body must not exceed the configured size limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import end_lineno, lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# Tree-sitter node types that count as "one statement" under
# count_mode = "statements". Lined up with what Python's ``ast`` module
# would call statement nodes (excluding the function_definition itself
# and any nested function bodies).
#
# Note: ``yield`` deliberately omitted — Tree-sitter parses ``yield x``
# as ``expression_statement`` containing a ``yield`` node, so counting
# both would double-count every yield expression.
#
# ``class_definition`` is included: in Python's grammar a class
# definition is a (compound) statement, so a function containing a
# nested class should count the ``class Inner:`` line as 1 toward the
# enclosing function's statement total. The class body's own
# statements are walked too — they contribute to the enclosing
# function's complexity-proxy count, which matches the rule's intent.
# Per-mode unit string baked into the violation message. Surfacing
# "logical lines" / "statements" instead of a generic "lines" for the
# non-default modes prevents the user from misreading a small count as
# raw source lines (where blanks/comments would inflate the figure).
_UNIT_BY_MODE: dict[str, str] = {
    "statements": "statements",
    "logical_lines": "logical lines",
}


_STATEMENT_TYPES = frozenset(
    {
        "expression_statement",
        "assignment",
        "augmented_assignment",
        "if_statement",
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "match_statement",
        "return_statement",
        "raise_statement",
        "import_statement",
        "import_from_statement",
        "global_statement",
        "nonlocal_statement",
        "assert_statement",
        "delete_statement",
        "pass_statement",
        "break_statement",
        "continue_statement",
        "class_definition",
    }
)


class FunctionLengthRule(BaseRule):
    """Reject functions whose body exceeds the configured size limit.

    Three counting modes are supported via the ``count_mode`` config key:

    * ``"lines"`` (default) — inclusive source line span. Holzmann's
      original "fits on a printed page" framing. Matches what humans
      see in their editor; counts blank lines and comments. Easy to
      understand but game-able by reformatting (split a line, add
      blanks, etc.).
    * ``"logical_lines"`` — source lines minus blanks and pure-comment
      lines. Closer to what an experienced reviewer would intuitively
      count; less game-able than ``"lines"``.
    * ``"statements"`` — count Python statement nodes from the
      Tree-sitter parse. Equivalent in spirit to ruff's PLR0915
      (``too-many-statements``); robust to formatting choices since
      it ignores whitespace entirely. Statements inside nested
      function definitions are not counted toward the outer function.

    The default stays ``"lines"`` for backward compatibility — existing
    configs continue to behave identically. Switch to ``"logical_lines"``
    for cleaner human-readable accounting, or ``"statements"`` for full
    formatting independence.
    """

    name = "function_length"
    code = "SAFE101"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function or async function exceeding the configured size."""
        max_lines: int = self.config.get("max_lines", 60)
        count_mode: str = self.config.get("count_mode", "lines")
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            length = self._function_size(node, count_mode)
            if length > max_lines:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                unit = _UNIT_BY_MODE.get(count_mode, "lines")
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'Function "{func_name}" is {length} {unit} (max {max_lines})',
                    )
                )
        return violations

    @staticmethod
    def _function_size(func_node: tree_sitter.Node, count_mode: str) -> int:
        """Return the function's size under the requested counting mode.

        Validates *count_mode* explicitly — silently falling back on a
        typo (e.g. ``"line"`` instead of ``"lines"``) would leave the
        user wondering why their config didn't take effect. Raise
        ``ValueError`` so misconfiguration fails clearly when this rule
        evaluates the function (during ``check_file``), rather than
        producing silently different output. (Engine construction
        currently does not pre-validate per-rule config; per-rule
        validation runs lazily when the rule first runs against a
        file.)
        """
        if count_mode == "statements":
            return FunctionLengthRule._count_statements(func_node)
        if count_mode == "logical_lines":
            return FunctionLengthRule._count_logical_lines(func_node)
        if count_mode == "lines":
            return end_lineno(func_node) - lineno(func_node) + 1
        msg = f"function_length count_mode must be one of 'lines', 'logical_lines', 'statements' — got {count_mode!r}"
        raise ValueError(msg)

    @staticmethod
    def _count_statements(func_node: tree_sitter.Node) -> int:
        """Count statement nodes inside *func_node*, skipping nested defs.

        Skipping nested function bodies matters: a 12-statement helper
        defined inside a 3-statement outer function should not count
        the helper's statements toward the outer's total.
        """
        return sum(1 for n in walk(func_node, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)) if n is not func_node and n.type in _STATEMENT_TYPES)

    @staticmethod
    def _count_logical_lines(func_node: tree_sitter.Node) -> int:
        """Count source lines covered by *func_node*, excluding blanks and pure-comment lines.

        Walks the function's text byte-by-line: any line containing
        non-whitespace, non-``#``-prefixed content counts. ``# nosafe``
        and other inline comments still count if there's code on the
        same line; only lines that are *entirely* blank or comment-only
        are excluded.
        """
        text = node_text(func_node)
        if not text:  # pragma: no cover — defensive; node_text returns "" only for ERROR nodes
            return 0
        count = 0
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            count += 1
        return count
