"""C language definition for safelint.

Registers C as a supported language and exposes the Tree-sitter node type
constants rules will use for type-checking nodes.

Scope: C is Holzmann's original target language, so several "Power of Ten"
clauses that every other language *adapts away* apply literally here. C
ports the 16 cross-language rules and adds **five new C-only rules** that
finally express those clauses directly: SAFE106 ``nonlocal_jumps`` (rule 1 -
``goto`` / ``setjmp``), SAFE310 ``dynamic_allocation`` (rule 3 -
``malloc``-family), SAFE311 ``complex_macro`` and SAFE312
``conditional_compilation`` (rule 8 - the real preprocessor), and SAFE313
``restricted_pointers`` (rule 9 - pointer levels / function pointers).

``.h`` ownership: ``.h`` headers register to C. A C++ project that uses
``.h`` headers gets them linted as C (content sniffing is out of scope); the
C++ addition keeps the C++-only header extensions (``.hpp`` etc.). This is a
documented limitation stated on both language pages.

Comment-prefix scope: line directives only (``// nosafe``,
``// safelint: ignore``). tree-sitter-c emits a single ``comment`` node type
for ``//`` line comments and ``/* */`` block comments alike. safelint
registers ``comment`` with the ``//`` prefix, so block-comment directives
parse but never match the prefix and are silently ignored - the same
line-directive-only convention used by every other registered language.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - C support ships in the ``[c]`` extra.
# Projects without C don't need to install ``tree-sitter-c`` and shouldn't
# pay the disk / install cost. Module import always succeeds; whether the
# parser can actually be constructed depends on ``_GRAMMAR_AVAILABLE``. Same
# shape as the other language modules.
try:
    import tree_sitter_c  # type: ignore[import-not-found]

    _C_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_c.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at lint
# time via ``_emit_missing_grammar_warnings``. Logging here would noise up
# every safelint import for users on non-C extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _C_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by the
#: CLI to compose multi-language install commands.
EXTRA_NAME = "c"

#: Install hint surfaced by the CLI when a user has ``.c`` / ``.h`` files in
#: their project but ``tree-sitter-c`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_c_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for C.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-c`` isn't installed. The registry filters ``.c`` / ``.h``
    out of ``supported_extensions()`` when the grammar isn't available, so
    this error is reached only when something bypasses the registry (rare in
    normal flow).
    """
    if _C_TS_LANGUAGE is None:
        msg = f"tree-sitter-c is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_C_TS_LANGUAGE)


C: LanguageDefinition = LanguageDefinition(
    name="c",
    file_extensions=frozenset({".c", ".h"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_c_parser,
)


# Node type constants - use these in rules instead of magic strings. Names
# mirror the tree-sitter-c grammar's node types (verified by probing the
# installed grammar, not from memory).

# The single function-defining node. C has no methods, closures, or lambdas,
# so ``function_definition`` is the only member of ``FUNCTION_TYPES`` - the
# simplest function model of any registered language.
FUNCTION_DEFINITION = "function_definition"

#: Aggregate of every C node type that defines a function (a single member).
#: Use in rules instead of the bare constant for cross-language symmetry.
FUNCTION_TYPES = frozenset({FUNCTION_DEFINITION})

# Calls. ``call_expression`` exposes the callee on the ``function`` field (an
# ``identifier`` for bare calls); the shared ``call_name`` resolves it via the
# generic ``function``-field path, so C needs no dispatch entry.
CALL_EXPRESSION = "call_expression"

# Control flow.
IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"  # ``for (;;)`` is the infinite form (empty condition)
WHILE_STATEMENT = "while_statement"  # ``while (1)`` / ``while (true)`` is the infinite form
DO_STATEMENT = "do_statement"  # ``do { ... } while (cond);``
SWITCH_STATEMENT = "switch_statement"
CASE_STATEMENT = "case_statement"  # both ``case X:`` and ``default:``
BREAK_STATEMENT = "break_statement"  # C has no labelled break; ``goto`` is the escape
CONTINUE_STATEMENT = "continue_statement"
RETURN_STATEMENT = "return_statement"
GOTO_STATEMENT = "goto_statement"  # SAFE106 / a loop-exit for SAFE501
LABELED_STATEMENT = "labeled_statement"  # ``label: ...`` - the goto target

# Statements / blocks.
COMPOUND_STATEMENT = "compound_statement"  # the ``{ ... }`` body block
EXPRESSION_STATEMENT = "expression_statement"  # wraps a bare call for SAFE802
DECLARATION = "declaration"  # file-scope -> SAFE302; the ``int **p`` carrier for SAFE313
INIT_DECLARATOR = "init_declarator"  # ``x = 1`` inside a declaration
PARAMETER_LIST = "parameter_list"
PARAMETER_DECLARATION = "parameter_declaration"

# Declarators (SAFE313 restricted pointers).
POINTER_DECLARATOR = "pointer_declarator"  # ``*p``; nests for ``**p``
FUNCTION_DECLARATOR = "function_declarator"  # also wraps function-pointer declarators
PARENTHESIZED_DECLARATOR = "parenthesized_declarator"  # ``(*fp)`` in a function pointer
ARRAY_DECLARATOR = "array_declarator"

# Expressions.
BINARY_EXPRESSION = "binary_expression"  # ``operator`` field; ``&&`` / ``||`` count for complexity
CONDITIONAL_EXPRESSION = "conditional_expression"  # ternary ``a ? b : c``
CAST_EXPRESSION = "cast_expression"  # ``(void)f()`` - wraps the call, so SAFE802 does NOT fire
ASSIGNMENT_EXPRESSION = "assignment_expression"  # ``x = ...``
UPDATE_EXPRESSION = "update_expression"  # ``x++`` / ``--y``
ARGUMENT_LIST = "argument_list"
FIELD_EXPRESSION = "field_expression"  # ``s.field`` / ``p->field``

# Qualifiers / specifiers (SAFE302 global mutation - ``const`` exempts).
TYPE_QUALIFIER = "type_qualifier"  # ``const`` / ``volatile`` / ``restrict``
STORAGE_CLASS_SPECIFIER = "storage_class_specifier"  # ``static`` / ``extern`` / ``typedef``
PRIMITIVE_TYPE = "primitive_type"
TYPE_DESCRIPTOR = "type_descriptor"  # the type inside a cast

# Preprocessor (SAFE311 complex macros, SAFE312 conditional compilation).
PREPROC_DEF = "preproc_def"  # ``#define NAME value`` (object-like)
PREPROC_FUNCTION_DEF = "preproc_function_def"  # ``#define SQ(x) ((x)*(x))`` (function-like)
PREPROC_IF = "preproc_if"  # ``#if ...``
PREPROC_IFDEF = "preproc_ifdef"  # ``#ifdef`` AND ``#ifndef`` (the grammar uses one node)
PREPROC_INCLUDE = "preproc_include"  # ``#include ...``
PREPROC_ARG = "preproc_arg"  # the replacement-list text of a #define
IDENTIFIER = "identifier"

# Misc.
TRANSLATION_UNIT = "translation_unit"  # the root node
COMMENT = "comment"  # single type for ``//`` and ``/* */``
