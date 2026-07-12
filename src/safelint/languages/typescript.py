"""TypeScript (and AssemblyScript) language definition for safelint.

Registers TypeScript as a supported language across two underlying
Tree-sitter grammars:

* ``typescript`` - for ``.ts`` and ``.as`` (AssemblyScript) files.
  AssemblyScript is intentionally a TypeScript-syntax subset that
  compiles to WebAssembly; ``tree-sitter-typescript`` parses ``.as``
  cleanly with the standard TypeScript grammar.
* ``tsx`` - for ``.tsx`` (TypeScript + JSX/TSX) files. The TSX grammar
  is a separate parser because JSX changes the meaning of ``<``,
  ``>``, and a few other tokens that would otherwise be ambiguous.

Both grammars share the same logical language name (``"typescript"``).
Rules dispatch on the language name, so a single ``"typescript"``
entry in a rule's ``language`` tuple covers both ``.ts`` and ``.tsx``
files transparently.

**Rule dispatch:** the TypeScript AST is essentially the JavaScript
AST plus type-related nodes (``type_annotation``, ``interface_declaration``,
``type_alias_declaration``, decorators, generics, etc.). The safety
rules SafeLint cares about (function length, nesting, complexity,
error handling, side effects, resource management) don't change
semantics in TypeScript vs JavaScript - type annotations are
metadata, not control flow. Most rules dispatch TS files to the
existing JavaScript rule implementations by reusing the JavaScript
node-type constants (re-exported below); rules that genuinely need
TS-specific handling (e.g., excluding generic type parameters from
``max_arguments``) opt in explicitly via the per-language dispatch
tables.

Comment-prefix scope: line directives only (``// nosafe``,
``// safelint: ignore``). Block-comment directives (``/* nosafe */``)
parse as a single ``comment`` node in Tree-sitter but the existing
line-style suppression parser doesn't unwrap ``/* … */`` - those are
silently ignored. Same limitation as JavaScript; documented in
``docs/contributing/adding-a-language.md``.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - TypeScript support ships in the ``[typescript]``
# extra. Module import always succeeds; parser construction errors with a clear
# install hint if the grammar package isn't present.
try:
    import tree_sitter_typescript  # type: ignore[import-not-found]

    _TYPESCRIPT_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    _TSX_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_typescript.language_tsx())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint
# at lint time via ``_emit_missing_grammar_warnings``. Logging here
# would noise up every safelint import for users on non-TS extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _TYPESCRIPT_TS_LANGUAGE = None
    _TSX_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "typescript"

# Node-type constants added for the rules node-constant refactor
# (per-language literal -> imported-constant sweep).
AMP_AMP = "&&"
PIPE_PIPE = "||"
QQ = "??"
STATEMENT_IDENTIFIER = "statement_identifier"
EMPTY_STATEMENT = "empty_statement"
REQUIRED_PARAMETER = "required_parameter"
OPTIONAL_PARAMETER = "optional_parameter"
REST_PARAMETER = "rest_parameter"
NEW_EXPRESSION = "new_expression"
AS_EXPRESSION = "as_expression"
SATISFIES_EXPRESSION = "satisfies_expression"
NON_NULL_EXPRESSION = "non_null_expression"
TYPE_ASSERTION = "type_assertion"
# added for node-constant refactor
THIS = "this"

#: Install hint surfaced by the CLI when a user has ``.ts`` / ``.tsx`` / ``.as``
#: files but ``tree-sitter-typescript`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_typescript_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for TypeScript (``.ts`` / ``.as``).

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-typescript`` isn't installed.
    """
    if _TYPESCRIPT_TS_LANGUAGE is None:
        msg = f"tree-sitter-typescript is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_TYPESCRIPT_TS_LANGUAGE)


def _create_tsx_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for TSX (``.tsx``).

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-typescript`` isn't installed.
    """
    if _TSX_TS_LANGUAGE is None:
        msg = f"tree-sitter-typescript is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_TSX_TS_LANGUAGE)


#: TypeScript language definition for ``.ts`` and ``.as`` (AssemblyScript) files.
#: Shares the ``name="typescript"`` with :data:`TSX` so rules' ``language``
#: tuples only need one entry to cover all three extensions.
TYPESCRIPT: LanguageDefinition = LanguageDefinition(
    name="typescript",
    file_extensions=frozenset({".ts", ".as"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_typescript_parser,
)


#: TSX language definition for ``.tsx`` files.
#: Shares the ``name="typescript"`` with :data:`TYPESCRIPT` - the two grammars
#: are an implementation detail; from the rule perspective TSX is just
#: TypeScript with JSX nodes added (and a few token disambiguations).
TSX: LanguageDefinition = LanguageDefinition(
    name="typescript",
    file_extensions=frozenset({".tsx"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_tsx_parser,
)


# ---------------------------------------------------------------------------
# Node type constants - TypeScript's AST is a superset of JavaScript's
# ---------------------------------------------------------------------------
#
# Tree-sitter-typescript reuses most of tree-sitter-javascript's node type
# names (``call_expression``, ``function_declaration``, ``if_statement``,
# etc.) and adds type-related nodes on top. Rather than duplicate every
# constant, we re-export the JavaScript constants below - rules that already
# import from ``safelint.languages.javascript`` continue to work on TS files
# without modification.
#
# TypeScript-specific nodes (when they become relevant in future slices):
#
# * ``type_annotation`` - ``: number`` on a parameter or variable
# * ``type_alias_declaration`` - ``type Foo = ...``
# * ``interface_declaration`` - ``interface Foo { ... }``
# * ``enum_declaration`` - ``enum Foo { A, B }``
# * ``decorator`` - ``@MyDecorator``
# * ``as_expression`` - type assertions ``x as Foo``
# * ``type_parameters`` - generic ``<T, U>``
# * ``optional_parameter`` - ``function f(x?: number)``
# * ``rest_parameter`` - ``function f(...args: number[])``
# * ``ambient_declaration`` - ``declare module ...``
#
# These are introduced as constants in later slices when rules need them.

from safelint.languages.javascript import (  # noqa: E402, F401
    ARRAY,
    ARRAY_PATTERN,
    ARROW_FUNCTION,
    ASSIGNMENT_EXPRESSION,
    AUGMENTED_ASSIGNMENT_EXPRESSION,
    AWAIT_EXPRESSION,
    BINARY_EXPRESSION,
    BREAK_STATEMENT,
    CALL_EXPRESSION,
    CATCH_CLAUSE,
    CLASS_BODY,
    CLASS_DECLARATION,
    COMMENT,
    CONTINUE_STATEMENT,
    DO_STATEMENT,
    ELSE_CLAUSE,
    EXPRESSION_STATEMENT,
    FALSE,
    FINALLY_CLAUSE,
    FOR_IN_STATEMENT,
    FOR_OF_STATEMENT,
    FOR_STATEMENT,
    FUNCTION_DECLARATION,
    FUNCTION_EXPRESSION,
    FUNCTION_TYPES,
    GENERATOR_FUNCTION,
    GENERATOR_FUNCTION_DECLARATION,
    IDENTIFIER,
    IF_STATEMENT,
    LEXICAL_DECLARATION,
    MEMBER_EXPRESSION,
    METHOD_DEFINITION,
    NULL,
    NUMBER,
    OBJECT,
    OBJECT_PATTERN,
    OPTIONAL_CHAIN,
    PAIR_PATTERN,
    PROPERTY_IDENTIFIER,
    REST_PATTERN,
    RETURN_STATEMENT,
    SHORTHAND_PROPERTY_IDENTIFIER_PATTERN,
    SPREAD_ELEMENT,
    STRING,
    SUBSCRIPT_EXPRESSION,
    SWITCH_CASE,
    SWITCH_STATEMENT,
    TEMPLATE_STRING,
    TEMPLATE_SUBSTITUTION,
    TERNARY_EXPRESSION,
    THROW_STATEMENT,
    TRUE,
    TRY_STATEMENT,
    UNARY_EXPRESSION,
    UNDEFINED,
    UPDATE_EXPRESSION,
    VARIABLE_DECLARATION,
    VARIABLE_DECLARATOR,
    WHILE_STATEMENT,
)
