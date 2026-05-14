"""Python language definition for safelint.

Registers Python as a supported language and exposes all Python-specific
Tree-sitter node type constants that rules use for type-checking nodes.

Grammar import is *optional* - Python support ships in the ``[python]``
extra (``pip install 'safelint[python]'``). Module import always
succeeds; whether ``tree-sitter-python`` is actually loaded depends on
:data:`_GRAMMAR_AVAILABLE`. This keeps non-Python projects from paying
the disk / install cost of a grammar they'll never use.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


try:
    import tree_sitter_python  # type: ignore[import-not-found]

    _PYTHON_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_python.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint
# at lint time via ``_emit_missing_grammar_warnings``. Logging here
# would noise up every safelint import for users on non-Python extras.
# Coverage of this branch is excluded via ``except ImportError:`` in
# ``[tool.coverage.report].exclude_lines`` - the dev environment
# always installs the grammar, so the branch is genuinely unreachable
# in tests; behaviour is verified via monkeypatching the resulting
# state in ``tests/core/test_optional_grammars.py``.
except ImportError:  # nosafe: SAFE203
    _PYTHON_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands like
#: ``pip install 'safelint[python,typescript]'`` when more than one
#: grammar is missing.
EXTRA_NAME = "python"

#: Install hint surfaced by the CLI when a user has ``.py`` / ``.pyw``
#: files but ``tree-sitter-python`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_python_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Python.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-python`` isn't installed. The registry filters
    ``.py`` / ``.pyw`` out of ``supported_extensions()`` when the
    grammar isn't available, so this error is reached only when
    something bypasses the registry (rare in normal flow).
    """
    if _PYTHON_TS_LANGUAGE is None:
        msg = f"tree-sitter-python is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_PYTHON_TS_LANGUAGE)


PYTHON: LanguageDefinition = LanguageDefinition(
    name="python",
    file_extensions=frozenset({".py", ".pyw"}),
    comment_node_type="comment",
    comment_prefix="#",
    create_parser=_create_python_parser,
)


# Node type constants - use these in rules instead of magic strings.

FUNCTION_DEF = "function_definition"
ASYNC_FUNCTION_DEF = "async_function_definition"
CLASS_DEF = "class_definition"

IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"
WHILE_STATEMENT = "while_statement"
WITH_STATEMENT = "with_statement"
TRY_STATEMENT = "try_statement"
MATCH_STATEMENT = "match_statement"
EXCEPT_CLAUSE = "except_clause"
ELIF_CLAUSE = "elif_clause"
ELSE_CLAUSE = "else_clause"

ASSIGNMENT = "assignment"
AUGMENTED_ASSIGNMENT = "augmented_assignment"
ANNOTATED_ASSIGNMENT = "annotated_assignment"

# LHS destructure shapes: ``a, b``, ``(a, b)``, ``[a, b]``, ``a, *rest``.
PATTERN_LIST = "pattern_list"
TUPLE_PATTERN = "tuple_pattern"
LIST_PATTERN = "list_pattern"
LIST_SPLAT_PATTERN = "list_splat_pattern"

CALL = "call"
IDENTIFIER = "identifier"
ATTRIBUTE = "attribute"
SUBSCRIPT = "subscript"

GLOBAL_STATEMENT = "global_statement"
ASSERT_STATEMENT = "assert_statement"
RAISE_STATEMENT = "raise_statement"
BREAK_STATEMENT = "break_statement"
RETURN_STATEMENT = "return_statement"
EXPRESSION_STATEMENT = "expression_statement"

BINARY_OPERATOR = "binary_operator"
BOOLEAN_OPERATOR = "boolean_operator"
UNARY_OPERATOR = "unary_operator"
COMPARISON_OPERATOR = "comparison_operator"
CONDITIONAL_EXPRESSION = "conditional_expression"

STRING = "string"
CONCATENATED_STRING = "concatenated_string"
INTERPOLATION = "interpolation"
LIST = "list"
TUPLE = "tuple"
SET = "set"

TRUE = "true"
FALSE = "false"
NONE = "none"
INTEGER = "integer"
FLOAT = "float"

FOR_IN_CLAUSE = "for_in_clause"
IF_CLAUSE = "if_clause"
COMMENT = "comment"
WITH_ITEM = "with_item"
PARAMETERS = "parameters"
