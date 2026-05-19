"""function_length rule - body must not exceed the configured size limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages import get_language_for_file
from safelint.languages._node_utils import end_lineno, lineno, node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# Per-language node-type sets keyed by ``LanguageDefinition.name``.
# Adding a language widens both tables (or, for stmt-mode, adds an
# entry - see _STATEMENT_TYPES_BY_LANG).
_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
}

# ``count_mode = "statements"`` is language-aware: each language has a
# different notion of what counts as a statement node. Python is wired
# up; JS / TS files use the universal ``lines`` (default) or
# ``logical_lines`` modes - adding a JS / TS statement-set is possible
# but the universal modes have proven sufficient in practice. A language
# not in this table raises a clear error rather than silently miscounting.
_STATEMENT_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    # Tree-sitter node types that count as "one statement" for Python.
    # Lined up with what Python's ``ast`` module would call statement nodes
    # (excluding the function_definition itself and any nested function
    # bodies).
    #
    # Note: ``yield`` deliberately omitted - Tree-sitter parses ``yield x``
    # as ``expression_statement`` containing a ``yield`` node, so counting
    # both would double-count every yield expression.
    #
    # ``class_definition`` is included: in Python's grammar a class
    # definition is a (compound) statement, so a function containing a
    # nested class should count the ``class Inner:`` line as 1 toward the
    # enclosing function's statement total. The class body's own
    # statements are walked too - they contribute to the enclosing
    # function's complexity-proxy count, which matches the rule's intent.
    "python": frozenset(
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
    ),
}

# Per-mode unit string baked into the violation message. Surfacing
# "logical lines" / "statements" instead of a generic "lines" for the
# non-default modes prevents the user from misreading a small count as
# raw source lines (where blanks/comments would inflate the figure).
_UNIT_BY_MODE: dict[str, str] = {
    "statements": "statements",
    "logical_lines": "logical lines",
}


class FunctionLengthRule(BaseRule):
    """Reject functions whose body exceeds the configured size limit.

    Three counting modes are supported via the ``count_mode`` config key:

    * ``"lines"`` (default) - inclusive source line span. Holzmann's
      original "fits on a printed page" framing. Matches what humans
      see in their editor; counts blank lines and comments. Easy to
      understand but game-able by reformatting (split a line, add
      blanks, etc.).
    * ``"logical_lines"`` - source lines minus blanks and pure-comment
      lines. Closer to what an experienced reviewer would intuitively
      count; less game-able than ``"lines"``.
    * ``"statements"`` - count statement nodes from the Tree-sitter
      parse. Equivalent in spirit to ruff's PLR0915
      (``too-many-statements``); robust to formatting choices since
      it ignores whitespace entirely. Statements inside nested
      function definitions are not counted toward the outer function.
      *Python-only today*; configuring ``statements`` mode on a
      non-Python file raises a clear error rather than silently
      mis-counting.

    The default stays ``"lines"`` for backward compatibility - existing
    configs continue to behave identically. Switch to ``"logical_lines"``
    for cleaner human-readable accounting, or ``"statements"`` for full
    formatting independence (Python only).
    """

    name = "function_length"
    code = "SAFE101"
    language = ("python", "javascript", "typescript", "java")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function or async function exceeding the configured size."""
        max_lines: int = self.config.get("max_lines", 60)
        count_mode: str = self.config.get("count_mode", "lines")
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        # Sourced from the registered ``LanguageDefinition`` rather than
        # branched per-lang here - adding a new language to the registry
        # then automatically routes the right comment marker without a
        # separate edit to this rule. Falls back to ``"#"`` for the
        # unit-test path where ``filepath`` has no registered extension
        # (``resolve_lang_name`` defaults to Python in that case, so the
        # comment prefix stays consistent with the dispatched language).
        lang_def = get_language_for_file(filepath)
        comment_prefix = lang_def.comment_prefix if lang_def is not None else "#"
        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            length = self._function_size(node, count_mode, lang_name, function_types, comment_prefix)
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
    def _function_size(
        func_node: tree_sitter.Node,
        count_mode: str,
        lang_name: str,
        function_types: frozenset[str],
        comment_prefix: str,
    ) -> int:
        """Return the function's size under the requested counting mode.

        Validates *count_mode* explicitly - silently falling back on a
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
            return FunctionLengthRule._count_statements(func_node, lang_name, function_types)
        if count_mode == "logical_lines":
            return FunctionLengthRule._count_logical_lines(func_node, comment_prefix)
        if count_mode == "lines":
            return end_lineno(func_node) - lineno(func_node) + 1
        msg = f"function_length count_mode must be one of 'lines', 'logical_lines', 'statements' - got {count_mode!r}"
        raise ValueError(msg)

    @staticmethod
    def _count_statements(func_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> int:
        """Count statement nodes inside *func_node*, skipping nested defs.

        Skipping nested function bodies matters: a 12-statement helper
        defined inside a 3-statement outer function should not count
        the helper's statements toward the outer's total.
        """
        if lang_name not in _STATEMENT_TYPES_BY_LANG:
            msg = f"function_length count_mode='statements' is not supported for {lang_name!r} files; use 'lines' or 'logical_lines' instead"
            raise ValueError(msg)
        statement_types = _STATEMENT_TYPES_BY_LANG[lang_name]
        return sum(1 for n in walk(func_node, skip_types=tuple(function_types)) if n is not func_node and n.type in statement_types)

    @staticmethod
    def _count_logical_lines(func_node: tree_sitter.Node, comment_prefix: str) -> int:
        """Count source lines covered by *func_node*, excluding blanks and pure-comment lines.

        Walks the function's text byte-by-line: any line containing
        non-whitespace content that isn't entirely a comment counts.
        Inline comments (code + trailing comment) still count as one line;
        only lines that are *entirely* blank or comment-only are excluded.
        Comment-prefix is language-specific (``#`` for Python, ``//`` for
        JavaScript) - taken from the active ``LanguageDefinition``.
        """
        text = node_text(func_node)
        if not text:  # pragma: no cover - defensive; node_text returns "" only for ERROR nodes
            return 0
        count = 0
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith(comment_prefix):
                continue
            count += 1
        return count
