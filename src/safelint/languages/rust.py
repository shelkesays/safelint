"""Rust language definition for safelint.

Registers Rust as a supported language and exposes the Tree-sitter node
type constants rules will use for type-checking nodes.

Scope: vanilla Rust (any edition from 2015 onward parses; the
``tree-sitter-rust`` grammar is current with edition 2021 / 2024).
Memory safety in Rust is enforced by ``rustc`` and the borrow checker, so
safelint's rule scope is narrower than for other languages: function
shape (length / nesting / complexity / args), error-handling discipline
(empty ``match`` arms that swallow ``Err``, ignored ``Result`` returns),
loop-safety (`loop` / ``while true`` without ``break``), and dataflow
patterns (unsanitised input into ``std::process::Command`` /
``sqlx::query`` / equivalents). Memory-management rules like SAFE401
(``resource_lifecycle``) are intentionally NOT ported: Rust's RAII drop
semantics guarantee cleanup, so the rule has nothing to add.

Comment-prefix scope: line directives only (``// nosafe``,
``// safelint: ignore``). tree-sitter-rust emits ``line_comment`` and
``block_comment`` as separate node types; safelint registers
``line_comment`` only, matching the ``//`` convention already used by
JavaScript, TypeScript, and Java. Block-comment directives
(``/* nosafe */``) parse but are silently ignored.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - Rust support ships in the ``[rust]`` extra.
# Pure-Python projects don't need to install ``tree-sitter-rust`` and
# shouldn't pay the disk / install cost. Module import always succeeds;
# whether the parser can actually be constructed depends on
# ``_GRAMMAR_AVAILABLE``.
try:
    import tree_sitter_rust  # type: ignore[import-not-found]

    _RUST_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_rust.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at
# lint time via ``_emit_missing_grammar_warnings``. Logging here would
# noise up every safelint import for users on non-Rust extras.
except ImportError:  # nosafe: SAFE203
    _RUST_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "rust"

#: Install hint surfaced by the CLI when a user has ``.rs`` files in
#: their project but ``tree-sitter-rust`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_rust_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Rust.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-rust`` isn't installed. The registry filters ``.rs``
    out of ``supported_extensions()`` when the grammar isn't available,
    so this error is reached only when something bypasses the registry
    (rare in normal flow).
    """
    if _RUST_TS_LANGUAGE is None:
        msg = f"tree-sitter-rust is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_RUST_TS_LANGUAGE)


#: Rust's primitive type names. A macro whose name is one of these defeats
#: ``tree-sitter-rust``: the lexer resolves the word as a type token before it
#: can be a macro identifier, and ``<primitive> !`` is not a valid invocation in
#: the grammar, so the whole FILE gets a ``SAFE000`` and no analysis at all.
#:
#: Not obscure in practice: ``str!`` is snapbox's inline-snapshot macro, so any
#: crate using those loses those files entirely (#174). Confirmed against
#: tree-sitter-rust 0.24.2, which is still the latest release, so this cannot be
#: fixed by a dependency bump today.
_PRIMITIVE_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
        "f32",
        "f64",
        "bool",
        "char",
        "str",
    }
)

_PRIMITIVE_MACRO_ADVICE = (
    "a macro named after a primitive type (such as snapbox's `str!`) cannot be parsed by tree-sitter-rust, "
    "so this file was NOT analysed; the code itself is valid Rust and there is nothing here to fix"
)


def primitive_macro_parse_cause(root: tree_sitter.Node) -> str | None:
    """Return advice if the parse failed on a primitive-named macro, else None.

    The grammar recovers in two shapes, both checked here because the bracket
    and brace forms differ:

    * ``str![1]`` / ``str!(1)`` - the ``ERROR`` holds the bare ``!`` and its
      previous sibling is the name;
    * ``str!{1}`` - the ``ERROR`` holds the name itself.

    Deliberately narrow. A genuine Rust syntax error produces neither shape: a
    missing token carries empty text, and an unbalanced delimiter puts an
    unrelated node either side, so this cannot turn a real mistake into "there
    is nothing here to fix". Verified against both forms of the failure and
    against a stray-brace and missing-semicolon error.

    **Every** error in the file has to be this shape, not merely one of them.
    Returning the advice on a first match was wrong in both directions
    (reported on #275): with a genuine error earlier in the file, ``SAFE000``
    points at THAT line while the message says there is nothing to fix; with
    the macro first, the message is right about its own location but still
    tells the reader a broken file is fine. Saying "nothing here to fix" is
    only honest when nothing else is broken, so any other error - including a
    MISSING token, which carries no text - falls back to the generic advice.

    Prunes subtrees with no error, so a mostly-valid file costs one shallow
    walk rather than a full traversal.
    """
    stack = [root]
    found = False
    while len(stack) > 0:
        node = stack.pop()
        if not node.has_error:
            continue
        if not (node.is_missing or node.type == ERROR):
            stack.extend(node.children)
            continue
        if not _is_primitive_macro_error(node):
            return None
        found = True
    return _PRIMITIVE_MACRO_ADVICE if found else None


def _is_primitive_macro_error(node: tree_sitter.Node) -> bool:
    """Return True when *node* is the ``ERROR`` left by ``<primitive>!``."""
    text = node.text.decode("utf-8", errors="replace") if node.text is not None else ""
    if text in _PRIMITIVE_TYPE_NAMES:
        return True  # the ``str!{...}`` shape: the name itself is the error
    if text != "!":
        return False
    previous = node.prev_sibling
    if previous is None or previous.text is None:
        return False
    return previous.text.decode("utf-8", errors="replace") in _PRIMITIVE_TYPE_NAMES


RUST: LanguageDefinition = LanguageDefinition(
    name="rust",
    file_extensions=frozenset({".rs"}),
    comment_node_type="line_comment",
    comment_prefix="//",
    create_parser=_create_rust_parser,
    # No blanket ``parse_error_hint``: a Rust parse failure usually IS the
    # user's mistake, unlike C and C++ where the preprocessor makes it routine.
    # Only this one recognised construct gets its own wording.
    parse_error_cause=primitive_macro_parse_cause,
)


# Node type constants - use these in rules instead of magic strings.
# Names mirror the tree-sitter-rust grammar's node types.

# Function-defining nodes. Rust splits between concrete ``function_item``
# (body required) and ``function_signature_item`` (trait method
# signatures with no body). Closures are first-class.
FUNCTION_ITEM = "function_item"
FUNCTION_SIGNATURE_ITEM = "function_signature_item"
CLOSURE_EXPRESSION = "closure_expression"
BLOCK = "block"  # generic block; not function-like on its own

#: Aggregate of every Rust node type that defines a function with a body.
#: Use in rules instead of listing the individual constants.
#: ``function_signature_item`` is deliberately NOT included: it has no
#: body, so body-walking rules (SAFE101 function_length, SAFE104
#: complexity, SAFE601 missing_assertions) would either produce
#: trivial / false-positive results on trait-method signatures or
#: would need per-rule body-presence guards. Keeping signatures out
#: of the set avoids both problems. Rules that *do* want to enumerate
#: signatures (e.g. a future "long-arg-list trait method" rule) can
#: reference :data:`FUNCTION_SIGNATURE_ITEM` directly.
FUNCTION_TYPES = frozenset(
    {
        FUNCTION_ITEM,
        CLOSURE_EXPRESSION,
    }
)

# Type-defining nodes. Rust has more shapes than other languages:
# structs, enums, unions, traits, impl blocks, type aliases, modules.
STRUCT_ITEM = "struct_item"
ENUM_ITEM = "enum_item"
UNION_ITEM = "union_item"
TRAIT_ITEM = "trait_item"
IMPL_ITEM = "impl_item"
TYPE_ITEM = "type_item"  # ``type Foo = Bar``
MOD_ITEM = "mod_item"

#: Aggregate of every Rust node type that introduces a new type / namespace
#: scope. Rules that need to find the enclosing type for a member walk
#: through these.
TYPE_DECLARATION_TYPES = frozenset(
    {
        STRUCT_ITEM,
        ENUM_ITEM,
        UNION_ITEM,
        TRAIT_ITEM,
        IMPL_ITEM,
    }
)

# Control flow.
IF_EXPRESSION = "if_expression"
ELSE_CLAUSE = "else_clause"  # ``else { .. }`` / the ``else`` of an ``else if`` chain
IF_LET_EXPRESSION = "if_let_expression"
FOR_EXPRESSION = "for_expression"
WHILE_EXPRESSION = "while_expression"
WHILE_LET_EXPRESSION = "while_let_expression"
LOOP_EXPRESSION = "loop_expression"  # ``loop { ... }``
MATCH_EXPRESSION = "match_expression"
MATCH_ARM = "match_arm"
MATCH_PATTERN = "match_pattern"
MATCH_BLOCK = "match_block"
BREAK_EXPRESSION = "break_expression"
CONTINUE_EXPRESSION = "continue_expression"
RETURN_EXPRESSION = "return_expression"
TRY_EXPRESSION = "try_expression"  # the ``?`` operator
YIELD_EXPRESSION = "yield_expression"  # generators (unstable, but parses)
LABEL = "label"  # ``'outer:`` block label

# Statements / declarations.
LET_DECLARATION = "let_declaration"
STATIC_ITEM = "static_item"  # ``static FOO: T = ...`` (module / impl scope)
ATTRIBUTE = "attribute"
CONST_ITEM = "const_item"  # ``const FOO: T = ...``
EXPRESSION_STATEMENT = "expression_statement"
USE_DECLARATION = "use_declaration"
USE_AS_CLAUSE = "use_as_clause"  # ``use p::x as y`` (only ``y`` is bound)
SCOPED_USE_LIST = "scoped_use_list"  # ``use p::q::{a, b}`` - ``path`` plus ``list``
USE_LIST = "use_list"  # the ``{a, b}`` brace group itself
USE_WILDCARD = "use_wildcard"  # ``use p::q::*`` - binds q's contents, not ``q``
SELF = "self"  # the ``self`` entry in ``use p::q::{self, a}``, binding ``q``
ATTRIBUTE_ITEM = "attribute_item"  # outer ``#[attr]``
INNER_ATTRIBUTE_ITEM = "inner_attribute_item"  # inner ``#![attr]``

# Expressions.
CALL_EXPRESSION = "call_expression"
MACRO_INVOCATION = "macro_invocation"  # ``println!(...)``
TOKEN_TREE = "token_tree"  # noqa: S105 - a grammar node name, not a secret
FIELD_EXPRESSION = "field_expression"  # ``obj.field``
INDEX_EXPRESSION = "index_expression"  # ``arr[i]``
ASSIGNMENT_EXPRESSION = "assignment_expression"
COMPOUND_ASSIGNMENT_EXPR = "compound_assignment_expr"  # ``x += 1``
BINARY_EXPRESSION = "binary_expression"
UNARY_EXPRESSION = "unary_expression"
REFERENCE_EXPRESSION = "reference_expression"  # ``&x`` / ``&mut x``
DEREFERENCE_EXPRESSION = "unary_expression"  # ``*ptr`` - shares the unary-expression node
PARENTHESIZED_EXPRESSION = "parenthesized_expression"
RANGE_EXPRESSION = "range_expression"  # ``a..b``
TUPLE_EXPRESSION = "tuple_expression"
ARRAY_EXPRESSION = "array_expression"
STRUCT_EXPRESSION = "struct_expression"  # ``Point { x, y }``
AWAIT_EXPRESSION = "await_expression"  # ``fut.await``
CLOSURE_PARAMETERS = "closure_parameters"  # ``|x, y|`` in ``|x, y| body``

# Parameters.
PARAMETERS = "parameters"  # the ``(...)`` container on a function
PARAMETER = "parameter"  # individual ``name: Type``
SELF_PARAMETER = "self_parameter"  # ``self`` / ``&self`` / ``&mut self``
VARIADIC_PARAMETER = "variadic_parameter"  # ``...`` in extern fn

# Identifiers / paths.
IDENTIFIER = "identifier"
TYPE_IDENTIFIER = "type_identifier"
FIELD_IDENTIFIER = "field_identifier"
SCOPED_IDENTIFIER = "scoped_identifier"  # ``std::fs::read``
SCOPED_TYPE_IDENTIFIER = "scoped_type_identifier"
SHORTHAND_FIELD_IDENTIFIER = "shorthand_field_identifier"  # ``Point { x }``

# Patterns.
MUT_PATTERN = "mut_pattern"  # ``mut x`` binding
REF_PATTERN = "ref_pattern"  # ``ref x`` binding
TUPLE_PATTERN = "tuple_pattern"  # ``(a, b)``
TUPLE_STRUCT_PATTERN = "tuple_struct_pattern"  # ``Some(x)`` / ``Point(x, y)``
STRUCT_PATTERN = "struct_pattern"  # ``Point { x, y }``
CAPTURED_PATTERN = "captured_pattern"  # ``name @ sub_pattern``
FIELD_PATTERN = "field_pattern"  # ``field: pattern`` inside a struct pattern

# Operator tokens (the ``operator`` field of a ``binary_expression``).
PLUS = "+"
MINUS = "-"
STAR = "*"

# Comments.
LINE_COMMENT = "line_comment"  # ``// ...``
BLOCK_COMMENT = "block_comment"  # ``/* ... */``

# Misc node types.
GENERIC_FUNCTION = "generic_function"  # ``foo::<T>()`` turbofish call
LET_CONDITION = "let_condition"  # the ``let`` condition in ``if let Some(x) = opt``
MUTABLE_SPECIFIER = "mutable_specifier"  # the ``mut`` token in ``let mut`` / ``&mut``
TYPE_CAST_EXPRESSION = "type_cast_expression"  # ``x as u32``
UNIT_EXPRESSION = "unit_expression"  # ``()``

# Types.
PRIMITIVE_TYPE = "primitive_type"  # ``i32`` / ``u64`` / ``f64`` / ``bool`` etc.
#: Tree-sitter's error node. Named in CAPS by the grammar, unlike every other
#: node type. Used by the parse-error cause detector above.
ERROR = "ERROR"
GENERIC_TYPE = "generic_type"  # ``Result<T, E>``
REFERENCE_TYPE = "reference_type"  # ``&T`` / ``&mut T``
POINTER_TYPE = "pointer_type"  # ``*const T`` / ``*mut T``
TUPLE_TYPE = "tuple_type"
ARRAY_TYPE = "array_type"
DYNAMIC_TYPE = "dynamic_type"  # ``dyn Trait``
UNIT_TYPE = "unit_type"  # ``()``

# Literals.
INTEGER_LITERAL = "integer_literal"
FLOAT_LITERAL = "float_literal"
STRING_LITERAL = "string_literal"
CHAR_LITERAL = "char_literal"
BOOLEAN_LITERAL = "boolean_literal"  # text is ``"true"`` or ``"false"``
RAW_STRING_LITERAL = "raw_string_literal"

# Misc.
UNSAFE_BLOCK = "unsafe_block"  # ``unsafe { ... }``
ASYNC_BLOCK = "async_block"
CONST_BLOCK = "const_block"
ENUM_VARIANT = "enum_variant"
FIELD_DECLARATION = "field_declaration"
DECLARATION_LIST = "declaration_list"  # body of ``impl`` / ``trait`` / ``mod``
SOURCE_FILE = "source_file"  # the root node
# added for node-constant refactor
AMP_AMP = "&&"
PIPE_PIPE = "||"
