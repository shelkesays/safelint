"""JavaScript (Node-flavoured) language definition for safelint.

Registers JavaScript as a supported language and exposes the Tree-sitter node
type constants rules will use for type-checking nodes.

Scope today: server-side / Node JavaScript - extensions ``.js``, ``.mjs``,
``.cjs``. JSX and TypeScript are *not* registered here; ``tree-sitter-javascript``
parses some JSX leniently as a superset, but flagging it as a separate language
later avoids accidental drift in rule semantics.

Comment-prefix scope: line directives only (``// nosafe``, ``// safelint: ignore``).
Block-comment directives (``/* nosafe */``) parse as a single ``comment`` node
in Tree-sitter but the existing line-style suppression parser doesn't unwrap
``/* … */`` - those are silently ignored. Documented as a future enhancement
in ``docs/contributing/adding-a-language.md`` Step 4.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - JavaScript support ships in the ``[javascript]``
# extra. Python-only users (``pip install safelint``) don't need to install
# ``tree-sitter-javascript`` and shouldn't pay the disk / install cost. Module
# import always succeeds; whether the parser can actually be constructed
# depends on ``_GRAMMAR_AVAILABLE``.
try:
    import tree_sitter_javascript  # type: ignore[import-not-found]

    _JAVASCRIPT_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_javascript.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint
# at lint time via ``_emit_missing_grammar_warnings``. Logging here
# would noise up every safelint import for users on non-JS extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _JAVASCRIPT_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "javascript"

#: Install hint surfaced by the CLI when a user has ``.js`` / ``.mjs`` / ``.cjs``
#: files in their project but ``tree-sitter-javascript`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_javascript_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for JavaScript.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-javascript`` isn't installed. The registry filters
    ``.js`` / ``.mjs`` / ``.cjs`` out of ``supported_extensions()`` when
    the grammar isn't available, so this error is reached only when
    something bypasses the registry (rare in normal flow).
    """
    if _JAVASCRIPT_TS_LANGUAGE is None:
        msg = f"tree-sitter-javascript is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_JAVASCRIPT_TS_LANGUAGE)


JAVASCRIPT: LanguageDefinition = LanguageDefinition(
    name="javascript",
    file_extensions=frozenset({".js", ".mjs", ".cjs"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_javascript_parser,
)


# Node type constants - use these in rules instead of magic strings.
#
# Names mirror the tree-sitter-javascript grammar's node types. Where Python
# has a single concept that JavaScript splits across multiple node types
# (function-like things, in particular), we expose tuples so rules can match
# them with ``node.type in JS_FUNCTION_TYPES``.

# Function-defining nodes - JS has more variety than Python.
FUNCTION_DECLARATION = "function_declaration"
FUNCTION_EXPRESSION = "function_expression"
ARROW_FUNCTION = "arrow_function"
METHOD_DEFINITION = "method_definition"
GENERATOR_FUNCTION = "generator_function"
GENERATOR_FUNCTION_DECLARATION = "generator_function_declaration"

#: Aggregate of every JS node type that defines a function. Use in rules
#: instead of listing the individual constants - keeps porting consistent.
FUNCTION_TYPES = frozenset(
    {
        FUNCTION_DECLARATION,
        FUNCTION_EXPRESSION,
        ARROW_FUNCTION,
        METHOD_DEFINITION,
        GENERATOR_FUNCTION,
        GENERATOR_FUNCTION_DECLARATION,
    }
)

CLASS_DECLARATION = "class_declaration"
CLASS_BODY = "class_body"

# Control flow.
IF_STATEMENT = "if_statement"
ELSE_CLAUSE = "else_clause"
FOR_STATEMENT = "for_statement"
FOR_IN_STATEMENT = "for_in_statement"  # ``for (k in obj)``
FOR_OF_STATEMENT = "for_of_statement"  # not actually emitted by the grammar - for_in_statement covers both; kept here for symmetry
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
NEW_EXPRESSION = "new_expression"
MEMBER_EXPRESSION = "member_expression"
SUBSCRIPT_EXPRESSION = "subscript_expression"
ASSIGNMENT_EXPRESSION = "assignment_expression"
BINARY_EXPRESSION = "binary_expression"
UNARY_EXPRESSION = "unary_expression"
UPDATE_EXPRESSION = "update_expression"
AWAIT_EXPRESSION = "await_expression"
YIELD_EXPRESSION = "yield_expression"
TERNARY_EXPRESSION = "ternary_expression"
SEQUENCE_EXPRESSION = "sequence_expression"  # ``(a, b, c)`` comma operator
PARENTHESIZED_EXPRESSION = "parenthesized_expression"  # ``(expr)``

# TypeScript-only expression wrappers. The shared JS/TS grammar surface means
# rules that walk ``.ts`` / ``.tsx`` trees see these; they don't appear in plain
# ``.js`` sources but the constants live here so the family shares one vocabulary.
TYPE_ASSERTION = "type_assertion"  # ``<T>expr``
AS_EXPRESSION = "as_expression"  # ``expr as T``
SATISFIES_EXPRESSION = "satisfies_expression"  # ``expr satisfies T``
NON_NULL_EXPRESSION = "non_null_expression"  # ``expr!``

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

# Assignment / declaration shapes - used by the dataflow analyser.
# JS doesn't separate "annotated assignment" from "regular assignment"
# the way Python does; type annotations live in the TS grammar, not JS.
# Reuse ``ASSIGNMENT_EXPRESSION`` from the *Expressions* section above -
# kept canonical there because the dataflow analyser also imports it
# under that grouping.
AUGMENTED_ASSIGNMENT_EXPRESSION = "augmented_assignment_expression"
VARIABLE_DECLARATOR = "variable_declarator"  # ``const x = y``, ``let x = y``, ``var x = y``
LEXICAL_DECLARATION = "lexical_declaration"  # ``const`` / ``let`` wrapper
VARIABLE_DECLARATION = "variable_declaration"  # ``var`` wrapper

# Destructuring patterns (LHS shapes).
ARRAY_PATTERN = "array_pattern"  # ``[a, b] = ...``
OBJECT_PATTERN = "object_pattern"  # ``{a, b} = ...``
REST_PATTERN = "rest_pattern"  # ``...rest`` in destructuring
ASSIGNMENT_PATTERN = "assignment_pattern"  # ``{a = 1}`` / ``[a = 1]`` default in destructuring
SHORTHAND_PROPERTY_IDENTIFIER_PATTERN = "shorthand_property_identifier_pattern"  # ``{foo}`` short form
PAIR_PATTERN = "pair_pattern"  # ``{key: alias}`` in object destructuring
# TypeScript typed-parameter wrappers around a binding pattern in ``formal_parameters``.
REQUIRED_PARAMETER = "required_parameter"  # ``x: number``
OPTIONAL_PARAMETER = "optional_parameter"  # ``x?: number``
REST_PARAMETER = "rest_parameter"  # ``...args: number[]``

# Composite expressions that propagate taint between operands.
TEMPLATE_SUBSTITUTION = "template_substitution"  # ``${expr}`` inside a template_string
SPREAD_ELEMENT = "spread_element"  # ``foo(...args)`` in call positions

# Container literals.
ARRAY = "array"
OBJECT = "object"
PAIR = "pair"  # ``key: value`` entry inside an object literal

# Field name on a member_expression marking optional chaining (``foo?.bar``).
# When present, the chained access is null-safe by construction - null_dereference
# (SAFE803) should NOT fire.
OPTIONAL_CHAIN = "optional_chain"
# added for node-constant refactor
AMP_AMP = "&&"
PIPE_PIPE = "||"
QQ = "??"
# added for node-constant refactor
EMPTY_STATEMENT = "empty_statement"
STATEMENT_IDENTIFIER = "statement_identifier"
# added for node-constant refactor
THIS = "this"
