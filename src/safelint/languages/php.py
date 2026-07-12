"""PHP language definition for safelint.

Registers PHP as a supported language and exposes the Tree-sitter node type
constants rules will use for type-checking nodes.

Scope: vanilla PHP (PHP 7+; the ``tree-sitter-php`` grammar tracks the
current language spec, including ``match``, enums, ``?->`` and promoted
constructor properties). PHP ports the largest share of the existing rule
set of any language so far: function shape (length / nesting / complexity /
args), error-handling discipline (empty ``catch`` bodies via SAFE202,
unlogged ``catch`` via SAFE203), shared mutable state (the literal
``global`` keyword - SAFE301's first non-Python home - and ``$GLOBALS``
writes via SAFE302), dynamic execution (``eval`` / ``call_user_func`` via
SAFE309), loop safety (``while (true)`` / ``for (;;)`` with numeric
``break N`` resolution via SAFE501), the classic web-taint flow
(superglobal ``$_GET`` / ``$_POST`` sources into ``exec`` / ``query`` /
``unserialize`` sinks via SAFE801), and suppression hygiene - the ``@``
error-suppression operator is SAFE603's most literal target in any language.

Grammar choice: ``tree-sitter-php`` exposes two grammars, ``language_php()``
(mixed HTML+PHP, the real-world templated-file shape) and
``language_php_only()``. safelint uses ``language_php()`` so templated files
parse: HTML segments outside ``<?php ... ?>`` arrive as inert ``text`` nodes
the rules never match.

Comment-prefix scope: line directives only (``// nosafe``,
``// safelint: ignore``). tree-sitter-php emits a single ``comment`` node
type for ``//`` line comments, ``#`` line comments, and ``/* */`` block
comments alike. safelint registers ``comment`` with the ``//`` prefix, so
``#``-comment and block-comment directives parse but never match the prefix
and are silently ignored - the same line-directive-only convention used by
every other registered language.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - PHP support ships in the ``[php]`` extra.
# Projects without PHP don't need to install ``tree-sitter-php`` and
# shouldn't pay the disk / install cost. Module import always succeeds;
# whether the parser can actually be constructed depends on
# ``_GRAMMAR_AVAILABLE``. Same shape as the other language modules.
try:
    import tree_sitter_php  # type: ignore[import-not-found]

    # ``language_php()`` is the mixed HTML+PHP grammar (templated files);
    # ``language_php_only()`` is the PHP-only variant. We want the former
    # so real-world ``.php`` templates parse.
    _PHP_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_php.language_php())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at
# lint time via ``_emit_missing_grammar_warnings``. Logging here would
# noise up every safelint import for users on non-PHP extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _PHP_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "php"

#: Install hint surfaced by the CLI when a user has ``.php`` files in
#: their project but ``tree-sitter-php`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_php_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for PHP.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-php`` isn't installed. The registry filters ``.php``
    out of ``supported_extensions()`` when the grammar isn't available,
    so this error is reached only when something bypasses the registry
    (rare in normal flow).
    """
    if _PHP_TS_LANGUAGE is None:
        msg = f"tree-sitter-php is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_PHP_TS_LANGUAGE)


PHP: LanguageDefinition = LanguageDefinition(
    name="php",
    file_extensions=frozenset({".php"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_php_parser,
)


# Node type constants - use these in rules instead of magic strings.
# Names mirror the tree-sitter-php grammar's node types (verified by
# probing the installed grammar, not from memory).

# Function-defining nodes. PHP has four: top-level / namespaced functions
# (``function_definition``), class / interface / trait methods
# (``method_declaration``), closures (``anonymous_function``), and the
# expression-bodied short closure (``arrow_function``, ``fn($x) => ...``).
FUNCTION_DEFINITION = "function_definition"
METHOD_DECLARATION = "method_declaration"
ANONYMOUS_FUNCTION = "anonymous_function"  # ``function () use ($x) { ... }``
ARROW_FUNCTION = "arrow_function"  # ``fn ($x) => $x + 1`` - expression body, no compound_statement

#: Aggregate of every PHP node type that defines a function. Use in rules
#: instead of listing the individual constants. Two caveats the per-rule
#: logic must handle (PHP has no separate signature node, unlike Rust):
#: ``method_declaration`` in an ``interface`` (or an ``abstract`` method)
#: carries NO ``compound_statement`` body - body-metric rules must skip
#: those; ``arrow_function`` has a single expression body rather than a
#: ``compound_statement``.
FUNCTION_TYPES = frozenset(
    {
        FUNCTION_DEFINITION,
        METHOD_DECLARATION,
        ANONYMOUS_FUNCTION,
        ARROW_FUNCTION,
    }
)

# Call shapes. PHP spreads calls across five node types; ``call_name`` in
# ``_node_utils`` resolves the bareword for each.
FUNCTION_CALL_EXPRESSION = "function_call_expression"  # ``foo(...)`` - callee on ``function`` field (a ``name``/``qualified_name``)
MEMBER_CALL_EXPRESSION = "member_call_expression"  # ``$obj->method(...)`` - method on ``name`` field
NULLSAFE_MEMBER_CALL_EXPRESSION = "nullsafe_member_call_expression"  # ``$obj?->method(...)``
SCOPED_CALL_EXPRESSION = "scoped_call_expression"  # ``Cls::m(...)`` / ``self::m(...)`` / ``static::m(...)``
OBJECT_CREATION_EXPRESSION = "object_creation_expression"  # ``new Cls(...)``

# Member / scope access (non-call). Used by SAFE105 (``$this->walk()``
# recursion) and SAFE803 (chained nullable access; ``?->`` is the safe form).
MEMBER_ACCESS_EXPRESSION = "member_access_expression"  # ``$obj->prop``
NULLSAFE_MEMBER_ACCESS_EXPRESSION = "nullsafe_member_access_expression"  # ``$obj?->prop`` - safe form
SCOPED_PROPERTY_ACCESS_EXPRESSION = "scoped_property_access_expression"  # ``Cls::$prop``
CLASS_CONSTANT_ACCESS_EXPRESSION = "class_constant_access_expression"  # ``Cls::CONST`` / ``self::CONST``

# Control flow.
IF_STATEMENT = "if_statement"
WHILE_STATEMENT = "while_statement"  # ``while (cond) { ... }``
DO_STATEMENT = "do_statement"  # ``do { ... } while (cond);``
FOR_STATEMENT = "for_statement"  # ``for (init; cond; step)`` - ``for (;;)`` is the infinite form
FOREACH_STATEMENT = "foreach_statement"  # ``foreach ($a as $k => $v)``
SWITCH_STATEMENT = "switch_statement"
MATCH_EXPRESSION = "match_expression"  # ``match ($v) { 1 => 'a', default => 'b' }``
MATCH_BLOCK = "match_block"
MATCH_CONDITIONAL_EXPRESSION = "match_conditional_expression"  # one non-default arm
MATCH_DEFAULT_EXPRESSION = "match_default_expression"  # the ``default =>`` arm
MATCH_CONDITION_LIST = "match_condition_list"
TRY_STATEMENT = "try_statement"
CATCH_CLAUSE = "catch_clause"  # always carries a ``type_list`` (PHP 7+) - no bare catch
FINALLY_CLAUSE = "finally_clause"
BREAK_STATEMENT = "break_statement"  # ``break;`` or ``break N;`` (numeric level via an ``integer`` child)
CONTINUE_STATEMENT = "continue_statement"
RETURN_STATEMENT = "return_statement"
THROW_EXPRESSION = "throw_expression"  # PHP 8 made ``throw`` an expression

# Statements / declarations.
EXPRESSION_STATEMENT = "expression_statement"
COMPOUND_STATEMENT = "compound_statement"  # the ``{ ... }`` body block
GLOBAL_DECLARATION = "global_declaration"  # ``global $x;`` inside a function
ECHO_STATEMENT = "echo_statement"  # ``echo ...`` is a statement, not a call
NAMESPACE_DEFINITION = "namespace_definition"

# Assignment.
ASSIGNMENT_EXPRESSION = "assignment_expression"  # ``$x = ...``
AUGMENTED_ASSIGNMENT_EXPRESSION = "augmented_assignment_expression"  # ``$x += ...`` (read-modify-write)

# Expressions.
BINARY_EXPRESSION = "binary_expression"  # has an ``operator`` field; covers ``&&`` ``||`` ``??`` ``==`` ``===`` ...
CONDITIONAL_EXPRESSION = "conditional_expression"  # ternary ``$a ? $b : $c``
ERROR_SUPPRESSION_EXPRESSION = "error_suppression_expression"  # the ``@`` operator - SAFE603's literal target
SUBSCRIPT_EXPRESSION = "subscript_expression"  # ``$_GET['id']`` / ``$arr[$i]``
PARENTHESIZED_EXPRESSION = "parenthesized_expression"
INCLUDE_EXPRESSION = "include_expression"  # ``include $path``
INCLUDE_ONCE_EXPRESSION = "include_once_expression"
REQUIRE_EXPRESSION = "require_expression"  # ``require $path``
REQUIRE_ONCE_EXPRESSION = "require_once_expression"
ARGUMENTS = "arguments"
ARGUMENT = "argument"

# Class-like declarations.
CLASS_DECLARATION = "class_declaration"
INTERFACE_DECLARATION = "interface_declaration"
TRAIT_DECLARATION = "trait_declaration"
ENUM_DECLARATION = "enum_declaration"
DECLARATION_LIST = "declaration_list"  # the ``{ ... }`` body of a class-like

# Parameters.
FORMAL_PARAMETERS = "formal_parameters"
SIMPLE_PARAMETER = "simple_parameter"  # ``$a`` / ``int $a = 1``
VARIADIC_PARAMETER = "variadic_parameter"  # ``...$args``
PROPERTY_PROMOTION_PARAMETER = "property_promotion_parameter"  # ``private int $x`` in a constructor

# Identifiers / scope keywords / literals.
NAME = "name"  # a bareword identifier (function names, member names, the inner part of ``variable_name``)
VARIABLE_NAME = "variable_name"  # ``$x`` - wraps a ``name`` child whose text is the variable (``this`` for ``$this``)
QUALIFIED_NAME = "qualified_name"  # ``\\Foo\\Bar`` / ``Throwable``
RELATIVE_SCOPE = "relative_scope"  # ``self`` / ``static`` / ``parent`` in a scoped call/access
ANONYMOUS_FUNCTION_USE_CLAUSE = "anonymous_function_use_clause"  # ``use ($x)`` on a closure
VISIBILITY_MODIFIER = "visibility_modifier"
PAIR = "pair"  # ``$k => $v`` in foreach / arrays
BOOLEAN = "boolean"  # ``true`` / ``false`` literal node
INTEGER = "integer"
STRING = "string"  # single-quoted ``'...'``
ENCAPSED_STRING = "encapsed_string"  # double-quoted ``"..."`` (interpolating)
STRING_CONTENT = "string_content"

# Misc.
PROGRAM = "program"  # the root node
PHP_TAG = "php_tag"  # the ``<?php`` open tag
TEXT = "text"  # raw HTML segment outside ``<?php ... ?>`` - rules never match these
COMMENT = "comment"  # single type for ``//``, ``#``, and ``/* */``

# Node-type constants added for the rules node-constant refactor
# (per-language literal -> imported-constant sweep).
ELSE_IF_CLAUSE = "else_if_clause"
CASE_STATEMENT = "case_statement"
AMP_AMP = "&&"
PIPE_PIPE = "||"
QQ = "??"
AND_KW = "and"
OR_KW = "or"
EMPTY_STATEMENT = "empty_statement"
FLOAT = "float"
NULL = "null"
UPDATE_EXPRESSION = "update_expression"
UNARY_OP_EXPRESSION = "unary_op_expression"
ARRAY_CREATION_EXPRESSION = "array_creation_expression"
ARRAY_ELEMENT_INITIALIZER = "array_element_initializer"
