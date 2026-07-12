"""Go language definition for safelint.

Registers Go as a supported language and exposes the Tree-sitter node type
constants rules will use for type-checking nodes.

Scope: vanilla Go (any version from 1.x parses; the ``tree-sitter-go``
grammar tracks the current language spec, including generics). Go's
runtime and ``go vet`` already catch a class of issues other languages
leave to safelint, so the rule set is shaped to Go's idioms: function
shape (length / nesting / complexity / args), error-handling discipline
(ignored ``error`` returns via SAFE802, empty ``if err != nil {}`` bodies
via the Go-only SAFE209, ``panic`` outside tests via the Go-only SAFE211),
loop-safety (bare ``for {}`` without a ``break`` is Go's ``while true``),
package-level shared state (SAFE302 on package ``var`` declarations), and
dataflow (unsanitised input into ``os/exec`` / ``database/sql`` /
``plugin`` sinks). Memory management is the runtime's job, so SAFE401
``resource_lifecycle`` ports as ``defer x.Close()`` detection rather than
a manual close/free check.

Comment-prefix scope: line directives only (``// nosafe``,
``// safelint: ignore``). tree-sitter-go emits a single ``comment`` node
type for both ``//`` line comments and ``/* */`` block comments (like
Python's single ``comment`` type, unlike Java / Rust which split the two).
safelint registers ``comment`` with the ``//`` prefix, so block-comment
directives (``/* nosafe */``) parse but never match the prefix and are
silently ignored - the same line-directive-only convention used by every
other registered language.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - Go support ships in the ``[go]`` extra.
# Pure-Python projects don't need to install ``tree-sitter-go`` and
# shouldn't pay the disk / install cost. Module import always succeeds;
# whether the parser can actually be constructed depends on
# ``_GRAMMAR_AVAILABLE``. Same shape as the other language modules.
try:
    import tree_sitter_go  # type: ignore[import-not-found]

    _GO_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_go.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at
# lint time via ``_emit_missing_grammar_warnings``. Logging here would
# noise up every safelint import for users on non-Go extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _GO_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "go"

#: Install hint surfaced by the CLI when a user has ``.go`` files in
#: their project but ``tree-sitter-go`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_go_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Go.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-go`` isn't installed. The registry filters ``.go``
    out of ``supported_extensions()`` when the grammar isn't available,
    so this error is reached only when something bypasses the registry
    (rare in normal flow).
    """
    if _GO_TS_LANGUAGE is None:
        msg = f"tree-sitter-go is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_GO_TS_LANGUAGE)


GO: LanguageDefinition = LanguageDefinition(
    name="go",
    file_extensions=frozenset({".go"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_go_parser,
)


# Node type constants - use these in rules instead of magic strings.
# Names mirror the tree-sitter-go grammar's node types.

# Function-defining nodes. Go has three: top-level / package functions
# (``function_declaration``), methods with a receiver
# (``method_declaration``), and anonymous closures (``func_literal``).
# All three carry a ``block`` body.
FUNCTION_DECLARATION = "function_declaration"
METHOD_DECLARATION = "method_declaration"
FUNC_LITERAL = "func_literal"

#: Aggregate of every Go node type that defines a function with a body.
#: Use in rules instead of listing the individual constants. Every Go
#: function form has a body, so (unlike Rust's signature split) there is
#: nothing to exclude here.
FUNCTION_TYPES = frozenset(
    {
        FUNCTION_DECLARATION,
        METHOD_DECLARATION,
        FUNC_LITERAL,
    }
)

# Type-defining nodes.
TYPE_DECLARATION = "type_declaration"  # ``type Foo struct { ... }`` / ``type Bar interface { ... }``
TYPE_SPEC = "type_spec"
STRUCT_TYPE = "struct_type"
INTERFACE_TYPE = "interface_type"

# Control flow.
IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"  # Go's only loop keyword - all four loop forms
FOR_CLAUSE = "for_clause"  # three-clause header ``for i := 0; i < n; i++``
RANGE_CLAUSE = "range_clause"  # ``for k, v := range coll``
EXPRESSION_SWITCH_STATEMENT = "expression_switch_statement"
TYPE_SWITCH_STATEMENT = "type_switch_statement"
EXPRESSION_CASE = "expression_case"
TYPE_CASE = "type_case"
DEFAULT_CASE = "default_case"
SELECT_STATEMENT = "select_statement"
COMMUNICATION_CASE = "communication_case"  # ``case <-ch:`` arm of a select
GO_STATEMENT = "go_statement"  # ``go f()``
DEFER_STATEMENT = "defer_statement"  # ``defer x.Close()``
RETURN_STATEMENT = "return_statement"
BREAK_STATEMENT = "break_statement"
CONTINUE_STATEMENT = "continue_statement"
GOTO_STATEMENT = "goto_statement"
LABELED_STATEMENT = "labeled_statement"
LABEL_NAME = "label_name"  # the label child of ``break outer`` / a ``labeled_statement``

# Statements / declarations.
VAR_DECLARATION = "var_declaration"  # ``var x int`` (package- or block-scope)
VAR_SPEC = "var_spec"
CONST_DECLARATION = "const_declaration"  # ``const c = 1``
CONST_SPEC = "const_spec"
SHORT_VAR_DECLARATION = "short_var_declaration"  # ``x := 1`` (block-scope only)
ASSIGNMENT_STATEMENT = "assignment_statement"  # ``x = 1`` / ``_ = f()``
EXPRESSION_STATEMENT = "expression_statement"  # bare ``f()`` as a statement
INC_STATEMENT = "inc_statement"  # ``i++``
DEC_STATEMENT = "dec_statement"  # ``i--``
BLOCK = "block"
STATEMENT_LIST = "statement_list"

# Expressions.
CALL_EXPRESSION = "call_expression"
SELECTOR_EXPRESSION = "selector_expression"  # ``pkg.Fn`` / ``recv.Method`` (operand + field)
BINARY_EXPRESSION = "binary_expression"  # has an ``operator`` field (``&&`` / ``||`` / ``!=`` / ...)
UNARY_EXPRESSION = "unary_expression"
INDEX_EXPRESSION = "index_expression"  # ``arr[i]``
ARGUMENT_LIST = "argument_list"
EXPRESSION_LIST = "expression_list"
PARENTHESIZED_EXPRESSION = "parenthesized_expression"
COMPOSITE_LITERAL = "composite_literal"  # ``T{...}``

# Parameters.
PARAMETER_LIST = "parameter_list"  # both the receiver list and the params list on a method
PARAMETER_DECLARATION = "parameter_declaration"  # ``a, b int`` - can bind several names
VARIADIC_PARAMETER_DECLARATION = "variadic_parameter_declaration"  # ``args ...T``

# Identifiers / literals.
IDENTIFIER = "identifier"
FIELD_IDENTIFIER = "field_identifier"  # the ``.Method`` part of a selector
PACKAGE_IDENTIFIER = "package_identifier"
TYPE_IDENTIFIER = "type_identifier"
BLANK_IDENTIFIER = "_"  # the discard identifier text (``_ = f()`` / ``x, _ := f()``)
NIL = "nil"  # the ``nil`` literal node
TRUE = "true"
FALSE = "false"
INT_LITERAL = "int_literal"
FLOAT_LITERAL = "float_literal"
INTERPRETED_STRING_LITERAL = "interpreted_string_literal"  # ``"..."``
RAW_STRING_LITERAL = "raw_string_literal"  # `` `...` ``

# Types.
POINTER_TYPE = "pointer_type"  # ``*T`` (receiver / field types)
SLICE_TYPE = "slice_type"
MAP_TYPE = "map_type"
QUALIFIED_TYPE = "qualified_type"  # ``pkg.Type``

# Misc.
SOURCE_FILE = "source_file"  # the root node
PACKAGE_CLAUSE = "package_clause"
IMPORT_DECLARATION = "import_declaration"
COMMENT = "comment"  # single type for both ``//`` and ``/* */``

# Node-type constants added for the rules node-constant refactor
# (per-language literal -> imported-constant sweep).
AMP_AMP = "&&"
PIPE_PIPE = "||"
VAR_SPEC_LIST = "var_spec_list"
BANG_EQ = "!="
EQ_EQ = "=="
EQ = "="
