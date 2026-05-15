"""Java language definition for safelint.

Registers Java as a supported language and exposes the Tree-sitter node type
constants rules will use for type-checking nodes.

Scope: vanilla Java (any JDK from 11 onwards parses, the grammar is JLS-current).
Spring Boot awareness ships as a *framework preset* configured via
``[tool.safelint.java] framework = "spring-boot"`` in TOML; the preset shifts
rule *defaults* (taint sources, side-effect exemptions, recognised logger
method names) but does not change parsing. The same ``tree-sitter-java``
grammar handles vanilla Java, Spring Boot, Jakarta EE, Android, and any
other framework.

Comment-prefix scope: line directives only (``// nosafe``, ``// safelint: ignore``).
tree-sitter-java emits ``line_comment`` and ``block_comment`` as two
distinct node types; safelint registers ``line_comment`` only, matching the
``//`` line-directive convention already established for JavaScript and
TypeScript. Block-comment directives (``/* nosafe */``) parse but are
silently ignored. Documented as a future enhancement in
``docs/contributing/adding-a-language.md``.
"""

from __future__ import annotations

import tree_sitter

from safelint.languages._types import LanguageDefinition


# Grammar import is *optional* - Java support ships in the ``[java]`` extra.
# Pure-Python projects don't need to install ``tree-sitter-java`` and
# shouldn't pay the disk / install cost. Module import always succeeds;
# whether the parser can actually be constructed depends on
# ``_GRAMMAR_AVAILABLE``.
try:
    import tree_sitter_java  # type: ignore[import-not-found]

    _JAVA_TS_LANGUAGE: tree_sitter.Language | None = tree_sitter.Language(tree_sitter_java.language())
    _GRAMMAR_AVAILABLE = True
# Silent fallback is intentional: the CLI surfaces the install hint at
# lint time via ``_emit_missing_grammar_warnings``. Logging here would
# noise up every safelint import for users on non-Java extras.
# Coverage exclusion: see the note in ``python.py``.
except ImportError:  # nosafe: SAFE203
    _JAVA_TS_LANGUAGE = None
    _GRAMMAR_AVAILABLE = False


#: PEP 621 extra name (matches the key under
#: ``[project.optional-dependencies]`` in ``pyproject.toml``). Used by
#: the CLI to compose multi-language install commands.
EXTRA_NAME = "java"

#: Install hint surfaced by the CLI when a user has ``.java`` files in
#: their project but ``tree-sitter-java`` isn't installed.
GRAMMAR_INSTALL_HINT = f"pip install 'safelint[{EXTRA_NAME}]'"


def _create_java_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Java.

    Raises :class:`ImportError` with a clear install hint if
    ``tree-sitter-java`` isn't installed. The registry filters ``.java``
    out of ``supported_extensions()`` when the grammar isn't available,
    so this error is reached only when something bypasses the registry
    (rare in normal flow).
    """
    if _JAVA_TS_LANGUAGE is None:
        msg = f"tree-sitter-java is not installed. Run: {GRAMMAR_INSTALL_HINT}"
        raise ImportError(msg)
    return tree_sitter.Parser(_JAVA_TS_LANGUAGE)


JAVA: LanguageDefinition = LanguageDefinition(
    name="java",
    file_extensions=frozenset({".java"}),
    comment_node_type="line_comment",
    comment_prefix="//",
    create_parser=_create_java_parser,
)


# Node type constants - use these in rules instead of magic strings.
#
# Names mirror the tree-sitter-java grammar's node types. Where Java has a
# concept that splits across multiple node types (function-like things,
# in particular: methods, constructors, lambdas), we expose tuples so rules
# can match them with ``node.type in JAVA_FUNCTION_TYPES``.

# Function-defining nodes. Java's "method" is the common shape; constructors
# look similar but use a different node type; lambdas are first-class in
# tree-sitter-java since Java 8.
METHOD_DECLARATION = "method_declaration"
CONSTRUCTOR_DECLARATION = "constructor_declaration"
LAMBDA_EXPRESSION = "lambda_expression"
# Static / instance initialiser blocks (``static { ... }`` / ``{ ... }`` at class scope).
# Treated like functions for length / nesting / complexity purposes.
STATIC_INITIALIZER = "static_initializer"
BLOCK = "block"  # generic statement block; not function-like on its own

#: Aggregate of every Java node type that defines a function. Use in rules
#: instead of listing the individual constants - keeps porting consistent.
FUNCTION_TYPES = frozenset(
    {
        METHOD_DECLARATION,
        CONSTRUCTOR_DECLARATION,
        LAMBDA_EXPRESSION,
        STATIC_INITIALIZER,
    }
)

# Type-defining nodes. Java has more than JS / Python: enums, interfaces,
# records (Java 14+), annotation type declarations.
CLASS_DECLARATION = "class_declaration"
INTERFACE_DECLARATION = "interface_declaration"
ENUM_DECLARATION = "enum_declaration"
RECORD_DECLARATION = "record_declaration"
ANNOTATION_TYPE_DECLARATION = "annotation_type_declaration"
CLASS_BODY = "class_body"
INTERFACE_BODY = "interface_body"
ENUM_BODY = "enum_body"
RECORD_BODY = "record_body"

#: Aggregate of every Java node type that introduces a new type scope.
TYPE_DECLARATION_TYPES = frozenset(
    {
        CLASS_DECLARATION,
        INTERFACE_DECLARATION,
        ENUM_DECLARATION,
        RECORD_DECLARATION,
        ANNOTATION_TYPE_DECLARATION,
    }
)

# Control flow.
IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"
ENHANCED_FOR_STATEMENT = "enhanced_for_statement"  # ``for (T x : iterable)``
WHILE_STATEMENT = "while_statement"
DO_STATEMENT = "do_statement"
SWITCH_EXPRESSION = "switch_expression"  # Java 14+ unified switch (both statement and expression)
SWITCH_BLOCK = "switch_block"
SWITCH_BLOCK_STATEMENT_GROUP = "switch_block_statement_group"
SWITCH_RULE = "switch_rule"  # arrow-form switch case (``case X -> ...``)
TRY_STATEMENT = "try_statement"
TRY_WITH_RESOURCES_STATEMENT = "try_with_resources_statement"
CATCH_CLAUSE = "catch_clause"
FINALLY_CLAUSE = "finally_clause"
CATCH_FORMAL_PARAMETER = "catch_formal_parameter"
CATCH_TYPE = "catch_type"

# Statements.
RETURN_STATEMENT = "return_statement"
THROW_STATEMENT = "throw_statement"
BREAK_STATEMENT = "break_statement"
CONTINUE_STATEMENT = "continue_statement"
EXPRESSION_STATEMENT = "expression_statement"
LABELED_STATEMENT = "labeled_statement"
ASSERT_STATEMENT = "assert_statement"
SYNCHRONIZED_STATEMENT = "synchronized_statement"
YIELD_STATEMENT = "yield_statement"  # Java 14+ switch-expression yield

# Expressions.
METHOD_INVOCATION = "method_invocation"
OBJECT_CREATION_EXPRESSION = "object_creation_expression"  # ``new Foo(...)``
FIELD_ACCESS = "field_access"
ARRAY_ACCESS = "array_access"
CAST_EXPRESSION = "cast_expression"
INSTANCEOF_EXPRESSION = "instanceof_expression"
ASSIGNMENT_EXPRESSION = "assignment_expression"
BINARY_EXPRESSION = "binary_expression"
UNARY_EXPRESSION = "unary_expression"
UPDATE_EXPRESSION = "update_expression"
TERNARY_EXPRESSION = "ternary_expression"
PARENTHESIZED_EXPRESSION = "parenthesized_expression"
ARRAY_CREATION_EXPRESSION = "array_creation_expression"
METHOD_REFERENCE = "method_reference"  # ``Foo::bar``

# Identifiers / literals.
IDENTIFIER = "identifier"
TYPE_IDENTIFIER = "type_identifier"
NULL_LITERAL = "null_literal"
TRUE = "true"
FALSE = "false"
DECIMAL_INTEGER_LITERAL = "decimal_integer_literal"
HEX_INTEGER_LITERAL = "hex_integer_literal"
OCTAL_INTEGER_LITERAL = "octal_integer_literal"
BINARY_INTEGER_LITERAL = "binary_integer_literal"
DECIMAL_FLOATING_POINT_LITERAL = "decimal_floating_point_literal"
HEX_FLOATING_POINT_LITERAL = "hex_floating_point_literal"
STRING_LITERAL = "string_literal"
CHARACTER_LITERAL = "character_literal"
LINE_COMMENT = "line_comment"
BLOCK_COMMENT = "block_comment"

# Variable declarations.
LOCAL_VARIABLE_DECLARATION = "local_variable_declaration"
FIELD_DECLARATION = "field_declaration"  # class-scope; static or instance
VARIABLE_DECLARATOR = "variable_declarator"

# Parameters / formal lists.
FORMAL_PARAMETERS = "formal_parameters"
FORMAL_PARAMETER = "formal_parameter"
SPREAD_PARAMETER = "spread_parameter"  # ``T... args`` varargs
RECEIVER_PARAMETER = "receiver_parameter"  # ``Foo this`` (rare; method-on-self idiom)
INFERRED_PARAMETERS = "inferred_parameters"  # lambda parameter list with no types

# Annotations - the key signal for Spring Boot framework detection.
ANNOTATION = "annotation"  # full ``@Foo(arg=value)`` form
MARKER_ANNOTATION = "marker_annotation"  # bare ``@Foo``
ANNOTATION_ARGUMENT_LIST = "annotation_argument_list"
ELEMENT_VALUE_PAIR = "element_value_pair"  # ``key = value`` inside annotation args

#: Aggregate of every Java annotation shape. Use when scanning for the
#: presence of a specific annotation regardless of whether it carries args.
ANNOTATION_TYPES = frozenset({ANNOTATION, MARKER_ANNOTATION})

# Modifiers (``public``, ``static``, ``final``, ``abstract``, etc.) - shared
# parent node that wraps the keyword set and any annotations on the
# declaration. Annotations live inside this node, so a rule looking for
# ``@Autowired`` on a field walks the declaration's ``modifiers`` child.
MODIFIERS = "modifiers"

# Types.
GENERIC_TYPE = "generic_type"
ARRAY_TYPE = "array_type"
SCOPED_TYPE_IDENTIFIER = "scoped_type_identifier"  # ``Foo.Bar``
VOID_TYPE = "void_type"
INTEGRAL_TYPE = "integral_type"  # ``int``, ``long``, ``byte``, ``short``, ``char``
FLOATING_POINT_TYPE = "floating_point_type"  # ``float``, ``double``
BOOLEAN_TYPE = "boolean_type"

# Throws clause and resource specification (try-with-resources).
THROWS = "throws"
RESOURCE_SPECIFICATION = "resource_specification"
RESOURCE = "resource"

# Imports.
IMPORT_DECLARATION = "import_declaration"
PACKAGE_DECLARATION = "package_declaration"
SCOPED_IDENTIFIER = "scoped_identifier"  # ``com.example.Foo``

# Composite expressions that propagate taint between operands.
STRING_CONCATENATION = BINARY_EXPRESSION  # Java uses ``+`` for string concat; binary_expression covers it
ARGUMENT_LIST = "argument_list"
