"""Python language definition for safelint.

Registers Python as a supported language and exposes all Python-specific
Tree-sitter node type constants that rules use for type-checking nodes.
"""

from __future__ import annotations

import tree_sitter
import tree_sitter_python

from safelint.languages._types import LanguageDefinition


_PYTHON_TS_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


def _create_python_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Python."""
    return tree_sitter.Parser(_PYTHON_TS_LANGUAGE)


PYTHON: LanguageDefinition = LanguageDefinition(
    name="python",
    file_extensions=frozenset({".py", ".pyw"}),
    comment_node_type="comment",
    comment_prefix="#",
    create_parser=_create_python_parser,
)


# Node type constants — use these in rules instead of magic strings.

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
