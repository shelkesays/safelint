"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.cpp import CATCH_CLAUSE as _CPP_CATCH_CLAUSE
from safelint.languages.cpp import COMMENT as _CPP_COMMENT
from safelint.languages.cpp import FUNCTION_TYPES as _CPP_FUNCTION_TYPES
from safelint.languages.cpp import THROW_STATEMENT as _CPP_THROW_STATEMENT
from safelint.languages.java import BLOCK_COMMENT as _JAVA_BLOCK_COMMENT
from safelint.languages.java import CATCH_CLAUSE as _JAVA_CATCH_CLAUSE
from safelint.languages.java import EMPTY_STATEMENT as _JAVA_EMPTY_STATEMENT
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.java import LINE_COMMENT as _JAVA_LINE_COMMENT
from safelint.languages.java import THROW_STATEMENT as _JAVA_THROW_STATEMENT
from safelint.languages.javascript import CATCH_CLAUSE as _JS_CATCH_CLAUSE
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import THROW_STATEMENT as _JS_THROW_STATEMENT
from safelint.languages.php import BOOLEAN as _PHP_BOOLEAN
from safelint.languages.php import CATCH_CLAUSE as _PHP_CATCH_CLAUSE
from safelint.languages.php import COMMENT as _PHP_COMMENT
from safelint.languages.php import EMPTY_STATEMENT as _PHP_EMPTY_STATEMENT
from safelint.languages.php import FLOAT as _PHP_FLOAT
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
from safelint.languages.php import INTEGER as _PHP_INTEGER
from safelint.languages.php import NULL as _PHP_NULL
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    EXCEPT_CLAUSE,
    FUNCTION_DEF,
    IDENTIFIER,
    RAISE_STATEMENT,
    TUPLE,
)
from safelint.languages.typescript import CATCH_CLAUSE as _TS_CATCH_CLAUSE
from safelint.languages.typescript import EMPTY_STATEMENT as _TS_EMPTY_STATEMENT
from safelint.languages.typescript import THROW_STATEMENT as _TS_THROW_STATEMENT
from safelint.rules.base import BaseRule, Suggestion, TextEdit


# Per-language: which Tree-sitter node types are "the catch handler clause".
# Python: ``except_clause`` (a child of ``try_statement``).
# JavaScript: ``catch_clause`` (also a child of ``try_statement``).
# Java: ``catch_clause`` (same node name; same shape as JS apart from the
# typed-binding requirement that the language enforces upstream).
_CATCH_CLAUSE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({EXCEPT_CLAUSE}),
    "javascript": frozenset({_JS_CATCH_CLAUSE}),
    "typescript": frozenset({_TS_CATCH_CLAUSE}),
    "java": frozenset({_JAVA_CATCH_CLAUSE}),
    "php": frozenset({_PHP_CATCH_CLAUSE}),
    "cpp": frozenset({_CPP_CATCH_CLAUSE}),
}

# Per-language: function-defining node types (used to skip nested
# function bodies when scanning a catch body - a logging call inside
# a nested ``def`` / ``function`` doesn't count as logging the caught
# error of the enclosing handler).
_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
    "typescript": _JS_FUNCTION_TYPES,
    "java": _JAVA_FUNCTION_TYPES,
    "php": _PHP_FUNCTION_TYPES,
    "cpp": _CPP_FUNCTION_TYPES,
}

# Per-language: re-raise statement types. ``except: raise`` (Python),
# ``catch (e) { throw e; }`` (JavaScript), and ``catch (E e) { throw e; }``
# (Java) all pass the error up the stack, which the logging-on-error
# rule treats as legitimate handling.
_RERAISE_STATEMENT_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({RAISE_STATEMENT}),
    "javascript": frozenset({_JS_THROW_STATEMENT}),
    "typescript": frozenset({_TS_THROW_STATEMENT}),
    "java": frozenset({_JAVA_THROW_STATEMENT}),
    # C++ ``throw;`` (bare rethrow) / ``throw e;`` both re-raise.
    "cpp": frozenset({_CPP_THROW_STATEMENT}),
}

# Statement-only no-op nodes: their presence means "developer wrote something
# to satisfy the parser but didn't actually handle the exception".
# Python: ``pass`` / ``continue`` (continue inside an except is rare but
# valid mid-loop). JavaScript: ``empty_statement`` (the bare ``;``);
# ``continue`` is a continue_statement that's only valid in loops, so it's
# unlikely to appear inside catch. Java: tree-sitter-java emits ``line_comment``
# and ``block_comment`` as *named* children of a block (unlike JS where
# comments are extras), so a Java catch body containing only a ``// todo``
# would have a single named child of comment type. Counting comments as
# no-op statements lets ``catch (Throwable t) { /* todo */ }`` match the
# empty-handler intent the way ``catch (Throwable t) {}`` already does.
_NOOP_STATEMENT_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({"pass_statement", "continue_statement"}),
    "javascript": frozenset({"empty_statement"}),
    "typescript": frozenset({_TS_EMPTY_STATEMENT}),
    # Java accepts bare semicolons (``catch (Exception e) { ; }``) as
    # empty statements, same as JS. ``line_comment`` / ``block_comment``
    # cover comment-only bodies (tree-sitter-java emits comments as
    # named block children, unlike JS where they're extras).
    "java": frozenset({_JAVA_EMPTY_STATEMENT, _JAVA_LINE_COMMENT, _JAVA_BLOCK_COMMENT}),
    # PHP: bare ``;`` is ``empty_statement``; tree-sitter-php emits both
    # ``//`` / ``#`` line comments and ``/* */`` block comments as a single
    # ``comment`` node that is a *named* child of the body block (like Java,
    # unlike JS where comments are extras), so a comment-only catch body
    # such as ``catch (\E $e) { /* todo */ }`` matches the empty-handler
    # intent.
    "php": frozenset({_PHP_EMPTY_STATEMENT, _PHP_COMMENT}),
    # C++: bare ``;`` is ``empty_statement``; tree-sitter-cpp emits ``//`` and
    # ``/* */`` as a single ``comment`` node that is a *named* child of the
    # catch body (like Java / PHP), so a comment-only body matches.
    "cpp": frozenset({"empty_statement", _CPP_COMMENT}),
}

# Per-language: literal expression node types that count as "comment-like"
# when they're the *sole* statement in a handler body (e.g. ``except: 0``,
# ``except: ...``, ``catch (e) { 0; }``, ``catch { null; }``).
# Python ``string`` is handled separately via :func:`_is_string_literal_expression`
# to distinguish plain strings from f-strings; JS template strings carry
# similar interpolation risk so are also delegated to the helper.
# Java ``string_literal`` is delegated too (Java 21+ string templates carry
# the same interpolation hazard as JS template strings).
_JS_LITERAL_EXPR_TYPES = frozenset(
    {
        "number",
        "true",
        "false",
        "null",
        "undefined",
    }
)
_JAVA_LITERAL_EXPR_TYPES = frozenset(
    {
        "decimal_integer_literal",
        "hex_integer_literal",
        "octal_integer_literal",
        "binary_integer_literal",
        "decimal_floating_point_literal",
        "hex_floating_point_literal",
        "true",
        "false",
        "null_literal",
        "character_literal",
    }
)
_LITERAL_EXPR_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset(
        {
            "integer",
            "float",
            "concatenated_string",
            "true",
            "false",
            "none",
            "ellipsis",
        }
    ),
    "javascript": _JS_LITERAL_EXPR_TYPES,
    "typescript": _JS_LITERAL_EXPR_TYPES,
    "java": _JAVA_LITERAL_EXPR_TYPES,
    # PHP: ``integer`` / ``float`` numeric literals, ``boolean`` (one node
    # type for both ``true`` and ``false``), and ``null``. Plain string
    # literals (``'TODO'`` / ``"TODO"``) are delegated to
    # ``_php_string_is_literal`` so interpolating double-quoted strings are
    # not treated as no-op markers.
    "php": frozenset({_PHP_INTEGER, _PHP_FLOAT, _PHP_BOOLEAN, _PHP_NULL}),
    # C++: ``number_literal`` covers int / float; ``true`` / ``false`` are
    # dedicated nodes; ``nullptr`` / ``null`` and ``char_literal`` round out
    # the single-literal no-op markers. String literals are delegated to
    # ``_cpp_string_is_literal``.
    "cpp": frozenset({"number_literal", "true", "false", "null", "nullptr", "char_literal"}),
}


def _is_noop_body(body_node: tree_sitter.Node | None, lang_name: str) -> bool:
    r"""Return True if *body_node* contains only no-op statements.

    Catches (varying by language):

    * Python ``except: pass`` / ``except: continue``     (pass_statement / continue_statement)
    * JavaScript ``catch (e) { ; }``                     (empty_statement)
    * Python ``except: ...``                             (ellipsis-as-expression-statement)
    * Numeric / boolean / null literals as a single statement
      (``except: 0``, ``catch (e) { null; }`` etc.)
    * String-as-comment idiom (``except: "TODO"``, ``catch (e) { "TODO"; }``)
    * Empty body / no statements at all                  (defensive - shouldn't
      happen with valid Tree-sitter output but kept for safety)

    Multi-statement Java bodies are accepted when **every** statement
    is a no-op (the all-comments-are-no-op case). tree-sitter-java emits
    each comment as a named child of the block, so
    ``catch (Exception e) { // a\n // b\n }`` has two named children
    (both ``line_comment``). Without the all-no-op variant, that body
    falls through with False.

    Multi-statement Python / JS / TS bodies are NOT accepted even when
    every statement is a no-op: two no-op statements there signal some
    intentional structure (``except: "log msg"; pass`` etc.), and the
    rule prefers a false negative to flagging legitimate-looking code.
    Python / JS / TS comments live OUTSIDE the block node in Tree-sitter,
    so the "multiple comments" scenario doesn't arise for them.
    """
    if body_node is None or not body_node.named_children:
        return True
    children = body_node.named_children
    # Java and PHP both emit comments as named block children, so a
    # comment-only body has several no-op children; accept when *every*
    # statement is a no-op (covers the multi-comment case).
    if lang_name in ("java", "php", "cpp"):
        return all(_stmt_is_noop(child, lang_name) for child in children)
    if len(children) != 1:
        return False
    return _stmt_is_noop(children[0], lang_name)


def _stmt_is_noop(stmt: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *stmt* is a no-op statement under the active language's grammar."""
    if stmt.type in _NOOP_STATEMENT_TYPES_BY_LANG[lang_name]:
        return True
    if stmt.type != "expression_statement":
        return False
    # expression_statement may wrap a single inner expression. Reach into it.
    inner = stmt.named_children[0] if stmt.named_children else None
    if inner is None:  # pragma: no cover - defensive
        return False
    if inner.type in _LITERAL_EXPR_TYPES_BY_LANG[lang_name]:
        return True
    return _is_string_literal_expression(inner, lang_name)


def _python_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a Python ``string`` node with no interpolation."""
    return node.type == "string" and all(child.type != "interpolation" for child in node.named_children) and bool(node_text(node))


def _js_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a JS / TS ``string`` or ``template_string`` with no interpolation."""
    if node.type not in ("string", "template_string"):
        return False
    return all(child.type != "template_substitution" for child in node.named_children) and bool(node_text(node))


def _java_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a Java ``string_literal`` with no nested template markers.

    Java 21 preview / final string templates introduce interpolation as
    nested ``string_fragment`` / template marker shapes. Plain literals
    have only string-content children (anonymous tokens, not named),
    so a ``string_literal`` with no named children is a plain literal.
    """
    return node.type == "string_literal" and not node.named_children and bool(node_text(node))


def _cpp_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a plain C++ string literal used as a no-op ``// TODO`` marker.

    C++ has no string interpolation (pre-C++26), so any ``string_literal`` /
    ``concatenated_string`` (adjacent literals) / ``raw_string_literal`` with
    text is a plain literal.
    """
    return node.type in ("string_literal", "concatenated_string", "raw_string_literal") and bool(node_text(node))


def _php_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a PHP plain string literal with no interpolation.

    Single-quoted ``'TODO'`` (``string``) never interpolates. Double-quoted
    ``"TODO"`` (``encapsed_string``) interpolates only when it contains a
    variable / expression child, so a plain double-quoted literal whose only
    named children are ``string_content`` counts as a no-op marker, while
    ``"$err"`` (with a ``variable_name`` child) does not.
    """
    if node.type == "string":
        return bool(node_text(node))
    if node.type != "encapsed_string":
        return False
    return all(child.type == "string_content" for child in node.named_children) and bool(node_text(node))


_STRING_LITERAL_PREDICATES: dict[str, Callable[[tree_sitter.Node], bool]] = {
    "python": _python_string_is_literal,
    "javascript": _js_string_is_literal,
    "typescript": _js_string_is_literal,
    "java": _java_string_is_literal,
    "php": _php_string_is_literal,
    "cpp": _cpp_string_is_literal,
}


def _is_string_literal_expression(node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True for plain string / template-string literals serving as no-op markers.

    Python / JavaScript / Java strings can all contain interpolation
    forms (Python f-strings, JS template literals, Java 21+ string
    templates); the per-language helpers above conservatively treat
    those as non-empty. Plain literal strings used as a "TODO" comment
    are treated as no-ops. Languages not in the dispatch table return
    False (unrecognised language).
    """
    predicate = _STRING_LITERAL_PREDICATES.get(lang_name)
    return predicate(node) if predicate is not None else False


if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _java_catch_formal_parameter(catch_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the ``catch_formal_parameter`` child of a Java ``catch_clause``, or None."""
    return next((c for c in catch_node.named_children if c.type == "catch_formal_parameter"), None)


def _js_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    """Return the JS / TS ``catch (e)`` binding, or None for ``catch {}`` (optional-binding)."""
    param_node = catch_node.child_by_field_name("parameter")
    if param_node is None or param_node.type != "identifier":
        return None
    return node_text(param_node)


def _php_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    r"""Return the PHP ``catch (\Type $e)`` binding (``$e``), or None for the non-capturing form."""
    name_node = catch_node.child_by_field_name("name")
    if name_node is None or name_node.type != "variable_name":
        return None
    return node_text(name_node)


def _java_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    """Return the Java ``catch (Type e)`` binding from its ``catch_formal_parameter``, or None."""
    formal = _java_catch_formal_parameter(catch_node)
    if formal is None:
        return None
    name_node = formal.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return None
    return node_text(name_node)


def _cpp_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    """Return the C++ ``catch (const E& e)`` binding (``e``), or None for ``catch (...)`` / unnamed.

    The parameter lives on the ``parameters`` field (a ``parameter_list``) as a
    single ``parameter_declaration``. The binding name is the sole ``identifier``
    inside that declaration's ``declarator`` subtree - the exception *type*
    (``const std::exception``) sits on the separate ``type`` field, so no type
    identifier leaks in. A ``reference_declarator`` (``E& e``) nests its name as
    a plain child rather than on a ``declarator`` field, so a subtree walk (not a
    field-chain unwrap) is used; the walk is iterative (SAFE105 polices
    recursion). ``catch (const E&)`` (no binding) and ``catch (...)`` return None.
    """
    params = catch_node.child_by_field_name("parameters")
    if params is None:  # pragma: no cover - defensive: a catch clause always has a parameter list
        return None
    decl = next((c for c in params.named_children if c.type == "parameter_declaration"), None)
    if decl is None:  # pragma: no cover - defensive: only reached for a ``throw e;`` inside a typed catch, which has a parameter_declaration
        return None
    declarator = decl.child_by_field_name("declarator")
    if declarator is None:  # pragma: no cover - defensive: a re-raised binding comes from a named ``catch (E& e)``
        return None
    return next((node_text(node) for node in walk(declarator) if node.type == "identifier"), None)


def _cpp_is_catch_all(catch_node: tree_sitter.Node) -> bool:
    """Return True for a C++ ``catch (...)`` catch-all (the bare-except analogue).

    The ellipsis handler catches every exception - including ones the code has
    no way to inspect or re-raise meaningfully - the same way Python's bare
    ``except:`` swallows ``SystemExit`` / ``KeyboardInterrupt``. It is
    distinguished from a typed ``catch (const E& e)`` by the absence of a
    ``parameter_declaration`` in its ``parameter_list`` (the ``...`` is an
    anonymous token, not a named child).
    """
    params = catch_node.child_by_field_name("parameters")
    if params is None:  # pragma: no cover - valid source always has a parameter list
        return False
    return not any(c.type == "parameter_declaration" for c in params.named_children)


#: C++ standard error / log streams whose ``<<`` insertion counts as a logging
#: call for SAFE203 (``std::cerr`` / ``std::clog`` / ``std::cout`` and their
#: unqualified ``using``-imported forms). Stream insertion is a ``<<`` binary
#: expression, not a call, so the generic ``call_name`` scan cannot see it.
_CPP_LOG_STREAMS = frozenset({"cerr", "clog", "cout"})


def _cpp_stream_target_name(operand: tree_sitter.Node) -> str | None:
    """Return the stream name of a ``<<`` chain's leftmost operand, or None.

    ``std::cerr`` parses as a ``qualified_identifier`` (trailing ``name`` field);
    an unqualified ``cerr`` (via ``using std::cerr``) is a bare ``identifier``.
    """
    if operand.type == "identifier":
        return node_text(operand)
    if operand.type == "qualified_identifier":
        name = operand.child_by_field_name("name")
        return node_text(name) if name is not None and name.type == "identifier" else None
    return None  # pragma: no cover - defensive: a stream-insertion chain's leftmost operand is a stream name, not another shape


def _cpp_chain_leftmost(expr: tree_sitter.Node) -> tree_sitter.Node | None:
    r"""Descend a ``<<`` chain's left spine to its leftmost operand (bounded loop).

    ``std::cerr << e.what() << "\\n"`` nests left, so the deepest left operand
    is ``std::cerr``. Never recurses (SAFE105).
    """
    operand: tree_sitter.Node | None = expr
    for _ in range(64):
        if operand is None or operand.type != "binary_expression":
            return operand
        operand = operand.child_by_field_name("left")
    return operand  # pragma: no cover - defensive: a ``<<`` chain deeper than 64 does not occur


def _cpp_body_has_stream_log(body: tree_sitter.Node, function_types: frozenset[str]) -> bool:
    """Return True if *body* contains a ``std::cerr << ...`` style stream-log expression.

    Scans every ``<<`` binary expression (pruning nested function / lambda
    bodies); if the leftmost operand of the insertion chain names a known log
    stream, the handler is treated as logging the caught error.
    """
    for node in walk(body, skip_types=tuple(function_types)):
        if node.type != "binary_expression":
            continue
        operator = node.child_by_field_name("operator")
        if operator is None or node_text(operator) != "<<":
            continue
        leftmost = _cpp_chain_leftmost(node)
        if leftmost is not None and _cpp_stream_target_name(leftmost) in _CPP_LOG_STREAMS:
            return True
    return False


#: C-family stderr writers that count as logging, mapped to the 0-based argument
#: position that carries the ``FILE*`` stream. The stream is NOT always the first
#: argument: ``fprintf(stream, fmt, ...)`` / ``vfprintf(stream, fmt, ap)`` put it
#: first, but ``fputs(s, stream)`` puts it second and
#: ``fwrite(ptr, size, nmemb, stream)`` fourth. ``perror`` always writes to
#: stderr and is handled separately (no argument check).
_CPP_STDERR_STREAM_ARG: dict[str, int] = {"fprintf": 0, "vfprintf": 0, "fputs": 1, "fwrite": 3}


def _cpp_call_arg_is_stderr(call_node: tree_sitter.Node, position: int) -> bool:
    """Return True if *call_node*'s argument at *position* (0-based) is the ``stderr`` stream."""
    args = call_node.child_by_field_name("arguments")
    if args is None:  # pragma: no cover - defensive: a call_expression always has an argument list
        return False
    named = args.named_children
    return position < len(named) and node_text(named[position]) == "stderr"


def _cpp_body_has_stderr_log(body: tree_sitter.Node, function_types: frozenset[str]) -> bool:
    """Return True if *body* logs via ``perror(...)`` or a ``stderr`` stream write.

    These are the idiomatic no-framework C / C++ error-logging calls; without
    them a catch that logs only through stderr would be a SAFE203 false
    positive. ``perror`` always writes to stderr; the ``fprintf`` / ``fputs`` /
    ``fwrite`` / ``vfprintf`` family counts only when its stream argument (at the
    per-function position in :data:`_CPP_STDERR_STREAM_ARG`) is ``stderr`` - a
    ``fprintf(logfile, ...)`` is not error logging. Nested function / lambda
    bodies are pruned.
    """
    for node in walk(body, skip_types=tuple(function_types)):
        if node.type not in CALL_TYPES:
            continue
        name = call_name(node)
        if name is None:
            continue
        if name == "perror":
            return True
        stream_arg = _CPP_STDERR_STREAM_ARG.get(name)
        if stream_arg is not None and _cpp_call_arg_is_stderr(node, stream_arg):
            return True
    return False


def _caught_binding_name(catch_node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the variable name bound by the catch clause, or None if there isn't one.

    Dispatches per language: JavaScript / TypeScript expose the binding via
    the ``parameter`` field (``catch (e)``); PHP via the ``name`` field (a
    ``variable_name``, ``catch (Type $e)``); Java via the ``name`` field of
    a ``catch_formal_parameter``. Returns the raw identifier text (e.g.
    ``"e"`` / ``"$e"``) ready for the caller to compare against the body's
    ``throw`` argument - exact byte equality is the contract.
    """
    extractor = _CAUGHT_BINDING_EXTRACTORS.get(lang_name)
    return extractor(catch_node) if extractor is not None else None


_CAUGHT_BINDING_EXTRACTORS: dict[str, Callable[[tree_sitter.Node], str | None]] = {
    "javascript": _js_caught_binding_name,
    "typescript": _js_caught_binding_name,
    "php": _php_caught_binding_name,
    "java": _java_caught_binding_name,
    "cpp": _cpp_caught_binding_name,
}


def _php_only_reraises(catch_node: tree_sitter.Node, stmts: list[tree_sitter.Node]) -> bool:
    """Return True for a PHP catch body that is just ``throw $e;`` of the caught binding.

    PHP 8's ``throw`` is an expression, so the re-raise is nested:
    ``expression_statement`` -> ``throw_expression`` -> ``variable_name``.
    Only re-throwing the *exact* caught variable counts; ``throw new E()``
    or ``throw $other`` constructs / forwards a different value and still
    needs logging.

    Comment children are skipped first: tree-sitter-php emits comments as
    named body nodes, so ``catch (Exception $e) { /* why */ throw $e; }``
    would otherwise reach here with two statements and be misread as a swallow.
    """
    real = [s for s in stmts if s.type != "comment"]
    if len(real) != 1 or real[0].type != "expression_statement":
        return False
    stmts = real
    inner = stmts[0].named_children
    if len(inner) != 1 or inner[0].type != "throw_expression":
        return False
    operand = inner[0].named_children
    if len(operand) != 1 or operand[0].type != "variable_name":
        return False
    bound = _caught_binding_name(catch_node, "php")
    return bound is not None and node_text(operand[0]) == bound


def _throw_reraises_caught_binding(throw_stmt: tree_sitter.Node, catch_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True for a JS / TS / Java ``throw <e>;`` that re-throws the exact caught binding.

    ``throw <identifier>;`` only counts as a re-raise when ``<identifier>`` is
    the precise name bound by the ``catch`` clause. Without a caught binding
    (``catch {}``) there is no name to re-raise, so any throw there is a fresh
    error and the rule still requires logging.
    """
    children = throw_stmt.named_children
    if len(children) != 1 or children[0].type != "identifier":
        return False
    param_text = _caught_binding_name(catch_node, lang_name)
    return param_text is not None and node_text(children[0]) == param_text


def _iter_catch_clauses(tree: tree_sitter.Tree, lang_name: str) -> Iterator[tree_sitter.Node]:
    """Yield every catch-handler clause in *tree*, regardless of source language.

    catch_clauses (JS) / except_clauses (Python) only appear inside
    try_statements in both grammars, so a flat walk suffices; no need
    to filter by parent.
    """
    catch_types = _CATCH_CLAUSE_TYPES_BY_LANG[lang_name]
    for node in walk(tree.root_node):
        if node.type in catch_types:
            yield node


def _catch_body(catch_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the body block of *catch_node*, or None if it has no body.

    Both Python ``except_clause`` and JavaScript ``catch_clause`` expose
    the body via the ``body`` field name - the API is uniform once
    indirected through ``child_by_field_name``. The fallback (last
    named child) is defensive for AST shapes where the field isn't
    populated; valid source always has a body.
    """
    body_node = catch_node.child_by_field_name("body")
    if body_node is not None:
        return body_node
    named = catch_node.named_children
    return named[-1] if named else None


def _has_typed_exception(except_node: tree_sitter.Node) -> bool:
    """Return True when an *except_clause* (Python) specifies one or more exception types.

    JavaScript ``catch_clause`` is *always* "typed" in the sense that
    the value variable is bound (``catch (e)``) - the Python-only
    SAFE201 rule (which fires on ``except:`` with no type) doesn't
    map cleanly to JS, so this helper only needs to handle the Python
    grammar.
    """
    # ``except ValueError as e:`` puts the type inside an ``as_pattern`` named child.
    return any(c.type in (IDENTIFIER, ATTRIBUTE, TUPLE, "as_pattern") for c in except_node.named_children)


def _bare_except_suggestion(except_node: tree_sitter.Node) -> Suggestion | None:
    """Build the "replace with ``except Exception:``" suggestion for a bare except clause.

    Returns ``None`` when the AST shape doesn't expose the colon child
    (defensive - Tree-sitter always produces it for valid Python).
    """
    # except_clause.children: ['except', ':', block, ...]. Find the ``:``
    # child and use its end_point as the end of the header range.
    colon = next((c for c in except_node.children if c.type == ":"), None)
    if colon is None:  # pragma: no cover
        return None
    edit = TextEdit(
        start_line=except_node.start_point[0] + 1,
        start_column=except_node.start_point[1] + 1,
        end_line=colon.end_point[0] + 1,
        end_column=colon.end_point[1] + 1,
        replacement="except Exception:",
    )
    return Suggestion(
        description="Catch ``Exception`` instead of using a bare ``except:``",
        edits=(edit,),
    )


class BareExceptRule(BaseRule):
    """Reject catch-all handlers that silently swallow every exception.

    Python ``except:`` catches ``SystemExit`` / ``KeyboardInterrupt`` and
    C++ ``catch (...)`` catches every thrown value with no binding to
    inspect or re-raise meaningfully - both hide the failure the same way.
    JavaScript / Java ``try/catch`` always binds the caught error (or uses
    JS's optional-binding ``catch {}``), so there is no equivalent
    unspecified-type form to flag there.
    """

    name = "bare_except"
    code = "SAFE201"
    language = ("python", "cpp")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every catch-all handler with no exception type specified."""
        if resolve_lang_name(filepath) == "cpp":
            return self._cpp_check(filepath, tree)
        return self._python_check(filepath, tree)

    def _cpp_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every C++ ``catch (...)`` catch-all clause."""
        return [
            self._make_violation_for_node(filepath, clause, "Catch-all `catch (...)` - catch a specific exception type instead")
            for clause in _iter_catch_clauses(tree, "cpp")
            if _cpp_is_catch_all(clause)
        ]

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every Python bare ``except:`` clause with no exception type specified."""
        violations: list[Violation] = []
        for clause in _iter_catch_clauses(tree, "python"):
            if _has_typed_exception(clause):
                continue
            base = self._make_violation_for_node(filepath, clause, "Bare except clause - specify the exception type(s)")
            suggestion = _bare_except_suggestion(clause)
            if suggestion is not None:
                # Attach the advisory suggestion. ``Violation`` is frozen, so
                # we rebuild via ``replace`` keeping the position fields intact.
                from dataclasses import replace  # noqa: PLC0415

                base = replace(base, suggestions=(suggestion,))
            violations.append(base)
        return violations


class EmptyExceptRule(BaseRule):
    """Reject except blocks whose body is empty (silent failure).

    Cross-language: fires on Python ``except: pass`` / ``except: ...`` /
    ``except: 0`` / ``except: "TODO"`` and on JavaScript
    ``catch (e) {}`` / ``catch { ; }`` / ``catch (e) { 0; }`` /
    ``catch (e) { "TODO"; }``.
    """

    name = "empty_except"
    code = "SAFE202"
    language = ("python", "javascript", "typescript", "java", "php", "cpp")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every catch handler whose body is effectively empty."""
        lang_name = resolve_lang_name(filepath)
        # Match the violation message to the source language's terminology -
        # JavaScript / Java / PHP developers don't write ``except`` blocks.
        # Same message-selection pattern as ``LoggingOnErrorRule``.
        block_word = "catch" if lang_name in ("javascript", "typescript", "java", "php", "cpp") else "except"
        message = f"Empty {block_word} block - add error handling or a logging call"
        return [self._make_violation_for_node(filepath, clause, message) for clause in _iter_catch_clauses(tree, lang_name) if _is_noop_body(_catch_body(clause), lang_name)]


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except / catch block that does not simply re-raise.

    Cross-language: walks Python ``except_clause`` and JavaScript
    ``catch_clause`` uniformly. Re-raise (Python ``raise``, JavaScript
    ``throw``) is exempted in either language.
    """

    name = "logging_on_error"
    code = "SAFE203"
    language = ("python", "javascript", "typescript", "java", "php", "cpp")

    # Union of method names treated as "logging" across registered
    # languages. Python stdlib ``logging`` exposes ``debug`` / ``info`` /
    # ``warning`` / ``error`` / ``exception`` / ``critical``; JavaScript's
    # ``console`` exposes ``log`` / ``error`` / ``warn`` / ``info`` /
    # ``debug`` / ``trace``; Java's SLF4J / log4j / java.util.logging
    # adds ``severe`` / ``fine`` / ``finer`` / ``finest`` for the JUL
    # severity levels (the other JUL levels overlap with names already
    # listed). ``call_name`` already strips the receiver
    # (``logger.error()`` and ``console.error()`` both resolve to
    # ``"error"``) so a single set covers every language without ambiguity.
    _LOG_METHODS = frozenset(
        {
            # Python stdlib logging.
            "debug",
            "info",
            "warning",
            "error",
            "exception",
            "critical",
            # JavaScript console + common logger libraries (winston, pino, bunyan).
            "log",
            "warn",
            "trace",
            # Java java.util.logging severity-level methods (SLF4J / log4j
            # share names with the JS / Python set above).
            "severe",
            "fine",
            "finer",
            "finest",
            # PHP: the ``error_log`` builtin plus the PSR-3 severity levels
            # not already listed (``info`` / ``warning`` / ``error`` /
            # ``debug`` / ``critical`` overlap with the Python set above).
            # ``$logger->notice($e)`` resolves via ``call_name`` to
            # ``"notice"``; ``error_log($e)`` to ``"error_log"``.
            "error_log",
            "notice",
            "alert",
            "emergency",
        }
    )

    def _only_reraises(self, except_node: tree_sitter.Node, lang_name: str) -> bool:
        """Return True when the handler body just propagates the caught error.

        Python: ``raise`` with no operand. ``raise Exception()`` raises a
        *new* error and so logging is still expected.

        JavaScript: ``throw <caught-binding>;`` where ``<caught-binding>``
        is the exact identifier introduced by the ``catch (e)`` clause
        - only ``catch (e) { throw e; }`` counts as a re-raise.
        ``catch (e) { throw freshError; }`` is throwing a *different*
        value (the original ``e`` may even still be in scope) and so
        logging is still expected; ``catch { throw x; }`` (no caught
        binding - ES2019 optional-binding form) can't be a re-raise
        of the caught value at all, so any throw there requires
        logging. ``throw new Error(...)`` / ``throw {code: 1}`` etc.
        construct fresh values and are always non-re-raises.

        Java: ``throw <caught-binding>;`` where ``<caught-binding>`` is
        the variable name from the ``catch (Type e)`` clause's
        ``catch_formal_parameter``. Same semantics as JS, except the
        parameter lives inside a ``catch_formal_parameter`` child (with
        a ``name`` field) rather than directly under the catch clause.
        Multi-catch ``catch (A | B e)`` follows the same shape, the
        binding is one identifier regardless of how many types are
        listed.
        """
        body_node = _catch_body(except_node)
        # Defensive - ``_catch_body`` only returns None for malformed AST
        # that this rule can't sensibly classify anyway.
        if body_node is None:  # pragma: no cover
            return False
        stmts = body_node.named_children
        # PHP's ``throw`` is an expression nested under expression_statement,
        # so it does not fit the flat statement-type check below.
        if lang_name == "php":
            return _php_only_reraises(except_node, stmts)
        reraise_types = _RERAISE_STATEMENT_TYPES_BY_LANG[lang_name]
        if len(stmts) != 1 or stmts[0].type not in reraise_types:
            return False
        if lang_name == "python":
            # Bare ``raise`` (no children) re-raises; ``raise Exception()`` does not.
            return not stmts[0].named_children
        if lang_name == "cpp" and not stmts[0].named_children:
            # Bare ``throw;`` rethrows the active exception. A ``throw e;`` with
            # an operand falls through to the caught-binding check below.
            return True
        return _throw_reraises_caught_binding(stmts[0], except_node, lang_name)

    def _has_log_call(self, except_node: tree_sitter.Node, function_types: frozenset[str], lang_name: str) -> bool:
        """Return True when the handler body contains at least one logging call.

        Walks only the body block (skipping the exception-type spec) and
        prunes nested function bodies so a logging call inside an inner
        function definition - which the catch handler never actually
        executes - does not count as logging the caught error. For C++, a
        ``std::cerr << ...`` stream insertion also counts (it is a ``<<``
        binary expression, not a call, so ``call_name`` alone cannot see it).
        """
        body = _catch_body(except_node)
        if body is None:  # pragma: no cover
            return False
        if any(call_name(node) in self._LOG_METHODS for node in walk(body, skip_types=tuple(function_types)) if node.type in CALL_TYPES):
            return True
        if lang_name != "cpp":
            return False
        return _cpp_body_has_stream_log(body, function_types) or _cpp_body_has_stderr_log(body, function_types)

    def _is_unlogged(self, except_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> bool:
        """Return True when this catch clause swallows an error without logging."""
        body_node = _catch_body(except_node)
        # Empty body (no named children) means this rule's job is done by
        # ``empty_except`` (SAFE202); skip here. ``body_node is None`` is
        # the same defensive case as elsewhere.
        if body_node is None or not body_node.named_children:  # pragma: no branch
            return False
        return not self._only_reraises(except_node, lang_name) and not self._has_log_call(except_node, function_types, lang_name)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag catch blocks that handle an error without any logging call."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        # Same language-specific terminology as ``EmptyExceptRule.check_file``
        # - JavaScript / TypeScript / Java developers write ``catch``,
        # not ``except``. Keeping the Python wording for non-Python
        # languages reads as a stale Python-only message and confuses
        # Java users in particular (Java's catch-clause is far enough
        # from Python's except-clause that the wording mismatch is
        # immediately visible).
        message = (
            "Catch block missing logging call - errors must be logged before being swallowed"
            if lang_name in ("javascript", "typescript", "java", "php", "cpp")
            else "Except block missing logging call - errors must be logged before being swallowed"
        )
        return [self._make_violation_for_node(filepath, clause, message) for clause in _iter_catch_clauses(tree, lang_name) if self._is_unlogged(clause, lang_name, function_types)]
