"""C++ language definition for safelint.

Registers C++ as a supported language and exposes the Tree-sitter node type
constants rules will use for type-checking nodes.

Scope: C++ builds on C. It ports the cross-language rule set, widens the five
C-only rules (SAFE106/310/311/312/313) to ``("c", "cpp")``, gives SAFE201
``bare_except`` its first non-Python home (``catch (...)``), and adds two
C++-only rules: SAFE315 ``raw_new_delete`` (the modern-ownership rule) and
SAFE316 ``dangerous_casts`` (``reinterpret_cast`` / ``const_cast``).

``.h`` ownership: ``.h`` headers register to C (a documented limitation - a C++
project's ``.h`` files lint as C; content sniffing is out of scope). C++ keeps
the C++-only header extensions ``.hpp`` / ``.hxx`` / ``.hh``.

Comment-prefix scope: line directives only, same as C - tree-sitter-cpp emits a
single ``comment`` node for ``//`` and ``/* */`` alike, and safelint registers
``comment`` with the ``//`` prefix.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - C++ support ships in the ``[cpp]`` extra.
# Module import always succeeds; whether the parser can be built depends on
# ``_GRAMMAR_AVAILABLE``. Same shape as the other language modules.
try:
    import tree_sitter_cpp  # type: ignore[import-not-found]

    _CPP_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_cpp.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at lint
# time. Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _CPP_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the ``[project.optional-dependencies]`` key).
EXTRA_NAME = "cpp"

#: Install hint surfaced by the CLI when a project has C++ files but
#: ``tree-sitter-cpp`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_cpp_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for C++.

    Raises :class:`ImportError` with a clear install hint if ``tree-sitter-cpp``
    isn't installed. The registry filters the C++ extensions out of
    ``supported_extensions()`` when the grammar is unavailable, so this error is
    reached only when something bypasses the registry (rare in normal flow).
    """
    if _CPP_TS_LANGUAGE is None:
        msg = f"tree-sitter-cpp is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_CPP_TS_LANGUAGE)


CPP: LanguageDefinition = LanguageDefinition(
    name="cpp",
    file_extensions=frozenset({".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"}),
    comment_node_type="comment",
    comment_prefix="//",
    create_parser=_create_cpp_parser,
)


# Node type constants - verified by probing the installed tree-sitter-cpp
# grammar (not from memory). tree-sitter-cpp is a superset of tree-sitter-c, so
# most C node types carry over identically.

# Function-defining nodes. A C++ ``function_definition`` covers BOTH free
# functions and methods (the declarator distinguishes ``S::m`` from ``f``); a
# ``lambda_expression`` body is its own function. A ``template_declaration``
# *wraps* a ``function_definition``, so the inner node is what the walks find -
# templates need no special casing.
FUNCTION_DEFINITION = "function_definition"
LAMBDA_EXPRESSION = "lambda_expression"

#: Aggregate of every C++ node type that defines a function.
FUNCTION_TYPES = frozenset({FUNCTION_DEFINITION, LAMBDA_EXPRESSION})

# Calls. ``call_expression`` exposes the callee on the ``function`` field.
CALL_EXPRESSION = "call_expression"

# Control flow (shared with C).
IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"
WHILE_STATEMENT = "while_statement"
DO_STATEMENT = "do_statement"
SWITCH_STATEMENT = "switch_statement"
CASE_STATEMENT = "case_statement"
BREAK_STATEMENT = "break_statement"
CONTINUE_STATEMENT = "continue_statement"
RETURN_STATEMENT = "return_statement"
GOTO_STATEMENT = "goto_statement"  # SAFE106; loop-exit for SAFE501
LABELED_STATEMENT = "labeled_statement"

# Exceptions (SAFE201/202/203). ``catch (...)`` is the ellipsis catch-all.
TRY_STATEMENT = "try_statement"
CATCH_CLAUSE = "catch_clause"
THROW_STATEMENT = "throw_statement"

# Statements / blocks.
COMPOUND_STATEMENT = "compound_statement"
EXPRESSION_STATEMENT = "expression_statement"
DECLARATION = "declaration"
INIT_DECLARATOR = "init_declarator"
FIELD_DECLARATION = "field_declaration"  # class/struct member declaration (SAFE302 static members)
PARAMETER_LIST = "parameter_list"
PARAMETER_DECLARATION = "parameter_declaration"
OPTIONAL_PARAMETER_DECLARATION = "optional_parameter_declaration"
FOR_RANGE_LOOP = "for_range_loop"
LINKAGE_SPECIFICATION = "linkage_specification"

# Declarators (SAFE313 restricted pointers).
POINTER_DECLARATOR = "pointer_declarator"
FUNCTION_DECLARATOR = "function_declarator"
PARENTHESIZED_DECLARATOR = "parenthesized_declarator"
ARRAY_DECLARATOR = "array_declarator"
REFERENCE_DECLARATOR = "reference_declarator"  # ``int& r`` / ``int&& r`` - not a pointer level
ABSTRACT_FUNCTION_DECLARATOR = "abstract_function_declarator"  # lambda ``[](int x){}`` parameter-list wrapper

# Aggregates / scopes.
CLASS_SPECIFIER = "class_specifier"  # SAFE302: non-const static data members
STRUCT_SPECIFIER = "struct_specifier"
NAMESPACE_DEFINITION = "namespace_definition"
TEMPLATE_DECLARATION = "template_declaration"

# Expressions.
BINARY_EXPRESSION = "binary_expression"  # ``&&`` / ``||`` for complexity; ``<<`` for cerr logging
CONDITIONAL_EXPRESSION = "conditional_expression"
CAST_EXPRESSION = "cast_expression"  # C-style ``(T)x``; the C++ named casts are ``template_function`` calls
ASSIGNMENT_EXPRESSION = "assignment_expression"
UPDATE_EXPRESSION = "update_expression"
ARGUMENT_LIST = "argument_list"
FIELD_EXPRESSION = "field_expression"  # ``s.m`` / ``p->m`` / ``this->m``
NEW_EXPRESSION = "new_expression"  # SAFE310 (widened) + SAFE315
DELETE_EXPRESSION = "delete_expression"  # SAFE310 (widened) + SAFE315
TEMPLATE_FUNCTION = "template_function"  # ``reinterpret_cast<T>`` callee shape (SAFE316)
QUALIFIED_IDENTIFIER = "qualified_identifier"  # ``std::cerr`` (SAFE203 stream logging)

# Qualifiers / specifiers (SAFE302: ``const`` / ``constexpr`` exempt).
TYPE_QUALIFIER = "type_qualifier"  # ``const`` / ``volatile`` / ``constexpr`` (grammar emits constexpr here)
STORAGE_CLASS_SPECIFIER = "storage_class_specifier"  # ``static`` / ``extern``
PRIMITIVE_TYPE = "primitive_type"
TYPE_DESCRIPTOR = "type_descriptor"

# Preprocessor (SAFE311 / SAFE312, shared with C).
PREPROC_DEF = "preproc_def"
PREPROC_FUNCTION_DEF = "preproc_function_def"
PREPROC_IF = "preproc_if"
PREPROC_IFDEF = "preproc_ifdef"
PREPROC_INCLUDE = "preproc_include"
PREPROC_ARG = "preproc_arg"
PREPROC_CALL = "preproc_call"  # ``#pragma`` (SAFE312 include-guard skip)
IDENTIFIER = "identifier"

# Misc.
TRANSLATION_UNIT = "translation_unit"  # the root node
COMMENT = "comment"
# added for node-constant refactor
EMPTY_STATEMENT = "empty_statement"
NUMBER_LITERAL = "number_literal"
TRUE = "true"
FALSE = "false"
NULL = "null"
CHAR_LITERAL = "char_literal"
STRING_LITERAL = "string_literal"
CONCATENATED_STRING = "concatenated_string"
RAW_STRING_LITERAL = "raw_string_literal"
# added for node-constant refactor
THIS = "this"
ARGUMENT = "argument"
# added for node-constant refactor
FIELD_IDENTIFIER = "field_identifier"
