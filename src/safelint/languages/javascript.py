"""JavaScript (Node-flavoured) language definition for safelint.

Registers JavaScript as a supported language and exposes the Tree-sitter node
type constants rules will use for type-checking nodes.

Scope today: server-side / Node JavaScript — extensions ``.js``, ``.mjs``,
``.cjs``. JSX and TypeScript are *not* registered here; ``tree-sitter-javascript``
parses some JSX leniently as a superset, but flagging it as a separate language
later avoids accidental drift in rule semantics.

Comment-prefix scope: line directives only (``// nosafe``, ``// safelint: ignore``).
Block-comment directives (``/* nosafe */``) parse as a single ``comment`` node
in Tree-sitter but the existing line-style suppression parser doesn't unwrap
``/* … */`` — those are silently ignored. Documented as a future enhancement
in ``docs/contributing/adding-a-language.md`` Step 4.
"""

from __future__ import annotations

import tree_sitter
import tree_sitter_javascript

from safelint.languages._types import LanguageDefinition


_JAVASCRIPT_TS_LANGUAGE = tree_sitter.Language(tree_sitter_javascript.language())


def _create_javascript_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for JavaScript."""
    return tree_sitter.Parser(_JAVASCRIPT_TS_LANGUAGE)


JAVASCRIPT: LanguageDefinition = LanguageDefinition(
    name="javascript",
    file_extensions=frozenset({".js", ".mjs", ".cjs"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_javascript_parser,
)


# Node type constants — use these in rules instead of magic strings.
#
# Names mirror the tree-sitter-javascript grammar's node types. Where Python
# has a single concept that JavaScript splits across multiple node types
# (function-like things, in particular), we expose tuples so rules can match
# them with ``node.type in JS_FUNCTION_TYPES``.

# Function-defining nodes — JS has more variety than Python.
FUNCTION_DECLARATION = "function_declaration"
FUNCTION_EXPRESSION = "function_expression"
ARROW_FUNCTION = "arrow_function"
METHOD_DEFINITION = "method_definition"
GENERATOR_FUNCTION = "generator_function"
GENERATOR_FUNCTION_DECLARATION = "generator_function_declaration"

#: Aggregate of every JS node type that defines a function. Use in rules
#: instead of listing the individual constants — keeps porting consistent.
FUNCTION_TYPES = frozenset({
    FUNCTION_DECLARATION,
    FUNCTION_EXPRESSION,
    ARROW_FUNCTION,
    METHOD_DEFINITION,
    GENERATOR_FUNCTION,
    GENERATOR_FUNCTION_DECLARATION,
})

CLASS_DECLARATION = "class_declaration"
CLASS_BODY = "class_body"

# Control flow.
IF_STATEMENT = "if_statement"
ELSE_CLAUSE = "else_clause"
FOR_STATEMENT = "for_statement"
FOR_IN_STATEMENT = "for_in_statement"  # ``for (k in obj)``
FOR_OF_STATEMENT = "for_of_statement"  # not actually emitted by the grammar — for_in_statement covers both; kept here for symmetry
WHILE_STATEMENT = "while_statement"
DO_STATEMENT = "do_statement"
SWITCH_STATEMENT = "switch_statement"
SWITCH_CASE = "switch_case"
TRY_STATEMENT = "try_statement"
CATCH_CLAUSE = "catch_clause"
FINALLY_CLAUSE = "finally_clause"

# Statements.
RETURN_STATEMENT = "return_statement"
THROW_STATEMENT = "throw_statement"
BREAK_STATEMENT = "break_statement"
CONTINUE_STATEMENT = "continue_statement"
EXPRESSION_STATEMENT = "expression_statement"

# Expressions.
CALL_EXPRESSION = "call_expression"
MEMBER_EXPRESSION = "member_expression"
SUBSCRIPT_EXPRESSION = "subscript_expression"
ASSIGNMENT_EXPRESSION = "assignment_expression"
BINARY_EXPRESSION = "binary_expression"
UNARY_EXPRESSION = "unary_expression"
UPDATE_EXPRESSION = "update_expression"
AWAIT_EXPRESSION = "await_expression"
TERNARY_EXPRESSION = "ternary_expression"

# Identifiers / literals.
IDENTIFIER = "identifier"
PROPERTY_IDENTIFIER = "property_identifier"
NULL = "null"
UNDEFINED = "undefined"
TRUE = "true"
FALSE = "false"
NUMBER = "number"
STRING = "string"
TEMPLATE_STRING = "template_string"
COMMENT = "comment"
