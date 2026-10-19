"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup, rule_default_list
from safelint.languages import cpp as _cpp
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.rules._test_files import skips_test_code
from safelint.rules.base import BaseRule, Suggestion, TextEdit


# Per-language: which Tree-sitter node types are "the catch handler clause".
# Python: ``except_clause`` (a child of ``try_statement``).
# JavaScript: ``catch_clause`` (also a child of ``try_statement``).
# Java: ``catch_clause`` (same node name; same shape as JS apart from the
# typed-binding requirement that the language enforces upstream).
_CATCH_CLAUSE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.EXCEPT_CLAUSE}),
    "javascript": frozenset({_js.CATCH_CLAUSE}),
    "typescript": frozenset({_ts.CATCH_CLAUSE}),
    "java": frozenset({_java.CATCH_CLAUSE}),
    "php": frozenset({_php.CATCH_CLAUSE}),
    "cpp": frozenset({_cpp.CATCH_CLAUSE}),
}

# Per-language: function-defining node types (used to skip nested
# function bodies when scanning a catch body - a logging call inside
# a nested ``def`` / ``function`` doesn't count as logging the caught
# error of the enclosing handler).
_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}

# Per-language: re-raise statement types. ``except: raise`` (Python),
# ``catch (e) { throw e; }`` (JavaScript), and ``catch (E e) { throw e; }``
# (Java) all pass the error up the stack, which the logging-on-error
# rule treats as legitimate handling.
_RERAISE_STATEMENT_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.RAISE_STATEMENT}),
    "javascript": frozenset({_js.THROW_STATEMENT}),
    "typescript": frozenset({_ts.THROW_STATEMENT}),
    "java": frozenset({_java.THROW_STATEMENT}),
    # C++ ``throw;`` (bare rethrow) / ``throw e;`` both re-raise.
    "cpp": frozenset({_cpp.THROW_STATEMENT}),
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
    "python": frozenset({_py.PASS_STATEMENT, _py.CONTINUE_STATEMENT}),
    "javascript": frozenset({_js.EMPTY_STATEMENT}),
    "typescript": frozenset({_ts.EMPTY_STATEMENT}),
    # Java accepts bare semicolons (``catch (Exception e) { ; }``) as
    # empty statements, same as JS. ``line_comment`` / ``block_comment``
    # cover comment-only bodies (tree-sitter-java emits comments as
    # named block children, unlike JS where they're extras).
    "java": frozenset({_java.EMPTY_STATEMENT, _java.LINE_COMMENT, _java.BLOCK_COMMENT}),
    # PHP: bare ``;`` is ``empty_statement``; tree-sitter-php emits both
    # ``//`` / ``#`` line comments and ``/* */`` block comments as a single
    # ``comment`` node that is a *named* child of the body block (like Java,
    # unlike JS where comments are extras), so a comment-only catch body
    # such as ``catch (\E $e) { /* todo */ }`` matches the empty-handler
    # intent.
    "php": frozenset({_php.EMPTY_STATEMENT, _php.COMMENT}),
    # C++: bare ``;`` is ``empty_statement``; tree-sitter-cpp emits ``//`` and
    # ``/* */`` as a single ``comment`` node that is a *named* child of the
    # catch body (like Java / PHP), so a comment-only body matches.
    "cpp": frozenset({_cpp.EMPTY_STATEMENT, _cpp.COMMENT}),
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
        _js.NUMBER,
        _js.TRUE,
        _js.FALSE,
        _js.NULL,
        _js.UNDEFINED,
    }
)
_JAVA_LITERAL_EXPR_TYPES = frozenset(
    {
        _java.DECIMAL_INTEGER_LITERAL,
        _java.HEX_INTEGER_LITERAL,
        _java.OCTAL_INTEGER_LITERAL,
        _java.BINARY_INTEGER_LITERAL,
        _java.DECIMAL_FLOATING_POINT_LITERAL,
        _java.HEX_FLOATING_POINT_LITERAL,
        _java.TRUE,
        _java.FALSE,
        _java.NULL_LITERAL,
        _java.CHARACTER_LITERAL,
    }
)
_LITERAL_EXPR_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset(
        {
            _py.INTEGER,
            _py.FLOAT,
            _py.CONCATENATED_STRING,
            _py.TRUE,
            _py.FALSE,
            _py.NONE,
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
    "php": frozenset({_php.INTEGER, _php.FLOAT, _php.BOOLEAN, _php.NULL}),
    # C++: ``number_literal`` covers int / float; ``true`` / ``false`` are
    # dedicated nodes; ``nullptr`` / ``null`` and ``char_literal`` round out
    # the single-literal no-op markers. String literals are delegated to
    # ``_cpp_string_is_literal``.
    "cpp": frozenset({_cpp.NUMBER_LITERAL, _cpp.TRUE, _cpp.FALSE, _cpp.NULL, "nullptr", _cpp.CHAR_LITERAL}),
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
    if lang_name in (_java.EXTRA_NAME, _php.EXTRA_NAME, _cpp.EXTRA_NAME):
        return all(_stmt_is_noop(child, lang_name) for child in children)
    if len(children) != 1:
        return False
    return _stmt_is_noop(children[0], lang_name)


def _stmt_is_noop(stmt: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *stmt* is a no-op statement under the active language's grammar."""
    if stmt.type in _NOOP_STATEMENT_TYPES_BY_LANG[lang_name]:
        return True
    if stmt.type != _py.EXPRESSION_STATEMENT:
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
    return node.type == _py.STRING and all(child.type != _py.INTERPOLATION for child in node.named_children) and bool(node_text(node))


def _js_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a JS / TS ``string`` or ``template_string`` with no interpolation."""
    if node.type not in (_js.STRING, _js.TEMPLATE_STRING):
        return False
    return all(child.type != _js.TEMPLATE_SUBSTITUTION for child in node.named_children) and bool(node_text(node))


def _java_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a Java ``string_literal`` with no nested template markers.

    Java 21 preview / final string templates introduce interpolation as
    nested ``string_fragment`` / template marker shapes. Plain literals
    have only string-content children (anonymous tokens, not named),
    so a ``string_literal`` with no named children is a plain literal.
    """
    return node.type == _java.STRING_LITERAL and not node.named_children and bool(node_text(node))


def _cpp_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a plain C++ string literal used as a no-op ``// TODO`` marker.

    C++ has no string interpolation (pre-C++26), so any ``string_literal`` /
    ``concatenated_string`` (adjacent literals) / ``raw_string_literal`` with
    text is a plain literal.
    """
    return node.type in (_cpp.STRING_LITERAL, _cpp.CONCATENATED_STRING, _cpp.RAW_STRING_LITERAL) and bool(node_text(node))


def _php_string_is_literal(node: tree_sitter.Node) -> bool:
    """Return True for a PHP plain string literal with no interpolation.

    Single-quoted ``'TODO'`` (``string``) never interpolates. Double-quoted
    ``"TODO"`` (``encapsed_string``) interpolates only when it contains a
    variable / expression child, so a plain double-quoted literal whose only
    named children are ``string_content`` counts as a no-op marker, while
    ``"$err"`` (with a ``variable_name`` child) does not.
    """
    if node.type == _php.STRING:
        return bool(node_text(node))
    if node.type != _php.ENCAPSED_STRING:
        return False
    return all(child.type == _php.STRING_CONTENT for child in node.named_children) and bool(node_text(node))


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
    return next((c for c in catch_node.named_children if c.type == _java.CATCH_FORMAL_PARAMETER), None)


def _js_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    """Return the JS / TS ``catch (e)`` binding, or None for ``catch {}`` (optional-binding)."""
    param_node = catch_node.child_by_field_name("parameter")
    if param_node is None or param_node.type != _py.IDENTIFIER:
        return None
    return node_text(param_node)


def _php_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    r"""Return the PHP ``catch (\Type $e)`` binding (``$e``), or None for the non-capturing form."""
    name_node = catch_node.child_by_field_name("name")
    if name_node is None or name_node.type != _php.VARIABLE_NAME:
        return None
    return node_text(name_node)


def _java_caught_binding_name(catch_node: tree_sitter.Node) -> str | None:
    """Return the Java ``catch (Type e)`` binding from its ``catch_formal_parameter``, or None."""
    formal = _java_catch_formal_parameter(catch_node)
    if formal is None:
        return None
    name_node = formal.child_by_field_name("name")
    if name_node is None or name_node.type != _java.IDENTIFIER:
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
    decl = next((c for c in params.named_children if c.type == _cpp.PARAMETER_DECLARATION), None)
    if decl is None:  # pragma: no cover - defensive: only reached for a ``throw e;`` inside a typed catch, which has a parameter_declaration
        return None
    declarator = decl.child_by_field_name("declarator")
    if declarator is None:  # pragma: no cover - defensive: a re-raised binding comes from a named ``catch (E& e)``
        return None
    return next((node_text(node) for node in walk(declarator) if node.type == _cpp.IDENTIFIER), None)


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
    return not any(c.type == _cpp.PARAMETER_DECLARATION for c in params.named_children)


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
    if operand.type == _cpp.IDENTIFIER:
        return node_text(operand)
    if operand.type == _cpp.QUALIFIED_IDENTIFIER:
        name = operand.child_by_field_name("name")
        return node_text(name) if name is not None and name.type == _cpp.IDENTIFIER else None
    return None  # pragma: no cover - defensive: a stream-insertion chain's leftmost operand is a stream name, not another shape


def _cpp_chain_leftmost(expr: tree_sitter.Node) -> tree_sitter.Node | None:
    r"""Descend a ``<<`` chain's left spine to its leftmost operand (bounded loop).

    ``std::cerr << e.what() << "\\n"`` nests left, so the deepest left operand
    is ``std::cerr``. Never recurses (SAFE105).
    """
    operand: tree_sitter.Node | None = expr
    for _ in range(64):
        if operand is None or operand.type != _cpp.BINARY_EXPRESSION:
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
        if node.type != _cpp.BINARY_EXPRESSION:
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
    real = [s for s in stmts if s.type != _php.COMMENT]
    if len(real) != 1 or real[0].type != _php.EXPRESSION_STATEMENT:
        return False
    stmts = real
    inner = stmts[0].named_children
    if len(inner) != 1 or inner[0].type != _php.THROW_EXPRESSION:
        return False
    operand = inner[0].named_children
    if len(operand) != 1:
        return False
    # PHP 8 allows a binding-less ``catch (Throwable)``, which leaves no name to
    # re-throw, so nothing in such a handler can propagate the caught value.
    bound = _caught_binding_name(catch_node, _php.EXTRA_NAME)
    if bound is None:
        return False
    # ``throw new RuntimeException('ctx', 0, $e);`` attaches the caught value as
    # the ``$previous`` argument, so the original stays reachable - the PHP
    # spelling of ``raise ... from err``.
    return _thrown_value_carries_binding(operand[0], bound, _php.VARIABLE_NAME, _WRAPPING_THROW_TYPES)


#: Node types a C-family ``throw`` uses to construct the thrown value:
#: ``new Error(..)`` (JS / TS ``new_expression``) and ``new RuntimeException(..)``
#: (Java / PHP ``object_creation_expression``).
_WRAPPING_THROW_TYPES = frozenset({"new_expression", "object_creation_expression"})

#: C++ throws a value, not a ``new``, so ``throw std::runtime_error(e.what())``
#: parses its construction as a plain call. Kept out of the shared set so that a
#: JavaScript ``throw someFactory(e)`` - which throws whatever that returns, not
#: necessarily a wrapper - is not exempted on the same rule.
_CPP_WRAPPING_THROW_TYPES = frozenset({"call_expression"})


def _wrapping_throw_types(lang_name: str) -> frozenset[str]:
    """Return the construction node types a ``throw`` can wrap the caught value in."""
    if lang_name == _cpp.EXTRA_NAME:
        return _WRAPPING_THROW_TYPES | _CPP_WRAPPING_THROW_TYPES
    return _WRAPPING_THROW_TYPES


def _thrown_value_carries_binding(thrown: tree_sitter.Node, bound: str, identifier_type: str, wrapping_types: frozenset[str]) -> bool:
    """Return True when the value being thrown is, or wraps, the caught binding.

    Two shapes, and they are the same question in both language families:

    * ``throw e`` / ``throw $e`` - the binding itself, re-raised;
    * ``throw new RuntimeException("loading config", e)`` - a FRESH error that
      carries the original along. This is the C-family spelling of Python's
      ``raise RuntimeError(msg) from err``: the caller sees the new error, but the
      original is attached to it and stays reachable, so nothing is swallowed.
      Demanding a log there is the double-reporting #159 is about, and exempting
      the Python form while reporting the Java one would be the one-act-judged-two-ways
      problem #199 is about.

    The binding has to actually appear in the construction arguments:
    ``throw new Error("x")`` discards the original and still requires logging,
    which is the distinction the rule has always drawn and still draws.

    *identifier_type* is the node type the binding appears as - ``identifier`` in
    the JS / TS / Java / C++ grammars, ``variable_name`` in PHP.
    """
    if thrown.type in wrapping_types:
        return any(node.type == identifier_type and node_text(node) == bound for node in walk(thrown))
    return thrown.type == identifier_type and node_text(thrown) == bound


def _throw_reraises_caught_binding(throw_stmt: tree_sitter.Node, catch_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True for a JS / TS / Java / C++ ``throw`` that passes the caught error on.

    Either ``throw <e>;`` of the precise name bound by the ``catch`` clause, or a
    thrown fresh error that wraps it. Without a caught binding (``catch {}``)
    there is no name to re-raise or wrap, so any throw there is a fresh error and
    the rule still requires logging.
    """
    children = throw_stmt.named_children
    if len(children) != 1:
        return False
    bound = _caught_binding_name(catch_node, lang_name)
    if bound is None:
        return False
    return _thrown_value_carries_binding(children[0], bound, _py.IDENTIFIER, _wrapping_throw_types(lang_name))


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
    return any(c.type in (_py.IDENTIFIER, _py.ATTRIBUTE, _py.TUPLE, _py.AS_PATTERN) for c in except_node.named_children)


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
    language = (_py.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every catch-all handler with no exception type specified."""
        if resolve_lang_name(filepath) == "cpp":
            return self._cpp_check(filepath, tree)
        return self._python_check(filepath, tree)

    def _cpp_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every C++ ``catch (...)`` catch-all clause."""
        return [
            self._make_violation_for_node(filepath, clause, "Catch-all `catch (...)` - catch a specific exception type instead")
            for clause in _iter_catch_clauses(tree, _cpp.EXTRA_NAME)
            if _cpp_is_catch_all(clause)
        ]

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every Python bare ``except:`` clause with no exception type specified."""
        violations: list[Violation] = []
        for clause in _iter_catch_clauses(tree, _py.EXTRA_NAME):
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
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _php.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every catch handler whose body is effectively empty."""
        lang_name = resolve_lang_name(filepath)
        # Match the violation message to the source language's terminology -
        # JavaScript / Java / PHP developers don't write ``except`` blocks.
        # Same message-selection pattern as ``LoggingOnErrorRule``.
        block_word = "catch" if lang_name in (_js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _php.EXTRA_NAME, _cpp.EXTRA_NAME) else "except"
        message = f"Empty {block_word} block - add error handling or a logging call"
        return [self._make_violation_for_node(filepath, clause, message) for clause in _iter_catch_clauses(tree, lang_name) if _is_noop_body(_catch_body(clause), lang_name)]


#: Block nodes, across the six grammars SAFE203 covers. Python ``block``,
#: JS / TS ``statement_block``, C++ ``compound_statement``, Java ``block``.
_HANDLER_BLOCK_TYPES: frozenset[str] = frozenset({"block", "statement_block", "compound_statement"})

#: Conditional nodes that carry their own obligation to cover every path. An
#: ``else if`` reaches the analysis as one of these: Python makes it an
#: ``elif_clause`` sibling, PHP an ``else_if_clause``, Java a bare nested
#: ``if_statement``, and JS / C++ an ``else_clause`` wrapping an ``if_statement``.
_CONDITIONAL_TYPES: frozenset[str] = frozenset({"if_statement", "elif_clause", "else_if_clause"})

#: The wrapper an ``else`` arm may arrive in before its body.
_ELSE_WRAPPER_TYPES: frozenset[str] = frozenset({"else_clause"})

#: ``else if`` arms that belong to the SAME chain as their ``if`` - the chain's
#: final ``else`` is their sibling, not their child, so they close nothing alone.
_CHAIN_ARM_TYPES: frozenset[str] = frozenset({"elif_clause", "else_if_clause"})


def _unwrap_else(node: tree_sitter.Node) -> tree_sitter.Node:
    """Return an ``else`` arm's payload, which may itself be a nested conditional.

    JavaScript and C++ spell ``else if`` as an ``else_clause`` wrapping an
    ``if_statement``, so unwrapping first is what lets one test serve all four
    grammar shapes.
    """
    if node.type not in _ELSE_WRAPPER_TYPES:
        return node
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    return node.named_children[0] if node.named_children else node


def _conditional_arms(conditional: tree_sitter.Node) -> tuple[list[tree_sitter.Node], bool]:
    """Return a conditional's arms and whether a terminal ``else`` covers the no-match path.

    The grammars split ``else if`` two ways, and the difference decides who owes
    the final ``else``:

    * Python's ``elif_clause`` and PHP's ``else_if_clause`` are **sibling arms of
      the same chain** - the chain's ``else`` is a sibling of theirs under the same
      ``if``, so an elif contributes its branch and closes nothing by itself;
    * Java's bare nested ``if_statement`` and the JS / C++ ``else_clause`` wrapping
      one are **nested chains** that carry their own obligation, so they are
      deferred whole and must be covered by an ``else`` of their own.

    Treating an ``elif`` as the second kind made ``if / elif / else`` where every
    arm raises report as swallowing: analysed alone, the elif looked like a
    conditional with no else.
    """
    arms: list[tree_sitter.Node] = []
    for field in ("consequence", "body"):
        branch = conditional.child_by_field_name(field)
        if branch is not None:
            arms.append(branch)
            break
    has_else = False
    for alternative in conditional.children_by_field_name("alternative"):
        if alternative.type in _CHAIN_ARM_TYPES:
            arms.extend(_chain_arm_branches(alternative))
            continue
        # Any non-chain alternative covers this conditional's no-match path. When
        # it is itself a nested conditional (JS / C++ ``else { if ... }``, Java's
        # bare ``else if``) the obligation is DELEGATED rather than discharged:
        # it is pushed as an arm and must carry its own ``else``, which is what
        # makes a chain ending without one still report - from the innermost
        # link, where the gap actually is.
        arms.append(_unwrap_else(alternative))
        has_else = True
    return arms, has_else


def _chain_arm_branches(arm: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the body of a same-chain ``elif`` / ``elseif`` arm."""
    for field in ("consequence", "body"):
        branch = arm.child_by_field_name(field)
        if branch is not None:
            return [branch]
    return []


def _propagation_leak_step(node: tree_sitter.Node, catch_node: tree_sitter.Node, lang_name: str, pending: list[tree_sitter.Node]) -> tree_sitter.Node | None:
    """Advance one node of the exit-path walk; return it if this path falls through.

    Blocks defer to their last statement, conditionals to their arms. Anything
    else terminates the path, so it propagates only if it raises.
    """
    if node.type in _HANDLER_BLOCK_TYPES:
        statements = [child for child in node.named_children if child.type != "comment"]
        if not statements:
            return node
        pending.append(statements[-1])
        return None
    if _statement_propagates(node, catch_node, lang_name):
        return None
    if node.type in _CONDITIONAL_TYPES:
        arms, has_else = _conditional_arms(node)
        pending.extend(arms)
        return None if has_else else node
    return node


def _statement_propagates(statement: tree_sitter.Node, catch_node: tree_sitter.Node, lang_name: str) -> bool:
    """Return True if *statement* leaves the handler with the caught error intact.

    Propagating is not enough on its own: throwing a **fresh** error discards the
    original, so the failure that actually happened is gone and logging it is
    still warranted. That distinction is already the rule's position and is
    pinned by tests in four languages, so this reuses the same predicates rather
    than reading the node type alone.

    Python is the exception, and genuinely so: a ``raise`` inside an ``except``
    block chains the active exception onto the new one automatically
    (``__context__``, or ``__cause__`` with an explicit ``from``), so the original
    stays reachable whichever form is used. That is what makes
    ``raise RuntimeError(msg) from err`` safe to exempt (#159) while
    ``throw new Error(msg)`` is not.
    """
    if lang_name == _py.EXTRA_NAME:
        return statement.type == _py.RAISE_STATEMENT
    if lang_name == _php.EXTRA_NAME:
        return _php_only_reraises(catch_node, [statement])
    if statement.type not in _RERAISE_STATEMENT_TYPES_BY_LANG.get(lang_name, frozenset()):
        return False
    if lang_name == _cpp.EXTRA_NAME and not statement.named_children:
        # Bare ``throw;`` rethrows the active exception.
        return True
    return _throw_reraises_caught_binding(statement, catch_node, lang_name)


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except / catch block that does not simply re-raise.

    Cross-language: walks Python ``except_clause`` and JavaScript
    ``catch_clause`` uniformly. Re-raise (Python ``raise``, JavaScript
    ``throw``) is exempted in either language.
    """

    name = "logging_on_error"
    code = "SAFE203"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _php.EXTRA_NAME, _cpp.EXTRA_NAME)

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

    def _log_methods(self, lang_name: str) -> frozenset[str]:
        """Return the call names that count as making the failure visible.

        Read from config rather than a hard-coded class attribute, so the list has
        one owner and users can adjust it - it previously had no config key at all.
        """
        raw, error_key = resolve_lang_config_lookup(self.config, "log_methods", lang_name, default=rule_default_list(self.name, "log_methods", lang_name))
        return frozenset(_validated_string_list(raw, error_key))

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
        if lang_name == _cpp.EXTRA_NAME and not stmts[0].named_children:
            # Bare ``throw;`` rethrows the active exception. A ``throw e;`` with
            # an operand falls through to the caught-binding check below.
            return True
        return _throw_reraises_caught_binding(stmts[0], except_node, lang_name)

    def _is_unlogged(self, except_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> bool:
        """Return True when this catch clause swallows an error without logging."""
        body_node = _catch_body(except_node)
        # Empty body (no named children) means this rule's job is done by
        # ``empty_except`` (SAFE202); skip here. ``body_node is None`` is
        # the same defensive case as elsewhere.
        if body_node is None or not body_node.named_children:  # pragma: no branch
            return False
        if self._only_reraises(except_node, lang_name):
            return False
        if self._has_log_call(except_node, function_types, lang_name):
            return False
        return self._propagation_leak(except_node, lang_name) is not None

    @staticmethod
    def _propagation_leak(except_node: tree_sitter.Node, lang_name: str) -> tree_sitter.Node | None:
        """Return the node where a path leaves the handler WITHOUT propagating, or None.

        ``_only_reraises`` asked whether the body was *exactly* one bare ``raise``,
        which is far narrower than the message's claim, so three shapes were
        reported as swallowing an error they do not swallow:

        * ``raise RuntimeError(msg) from err`` - the idiomatic add-context
          re-raise. Logging there yields two reports of one failure (#159);
        * report-then-propagate::

              except ValueError as exc:
                  print(f"failed: {exc}")
                  raise

          both statements make the failure observable, but the body is two
          statements (#199);
        * a branch where **every** arm raises::

              if recoverable:
                  raise Retry() from err
              else:
                  raise

          nothing is swallowed on any path, yet it was reported.

        Containment is not the test - this body really does swallow::

            if never_true:
                raise
            return None

        so the question is whether every *exit path* propagates. A block
        propagates when its last statement does; a conditional propagates when
        every arm does **and** an ``else`` exists, since without one the no-match
        path falls straight through.

        Returning the leaking node rather than a bool is what lets the violation
        point at the branch that falls through instead of at the ``except`` line.
        On a handler with several arms, "something in here leaks" makes the reader
        re-derive which; naming it is the difference between a finding that is
        acted on and one that is scrolled past.
        """
        body_node = _catch_body(except_node)
        if body_node is None or not body_node.named_children:  # pragma: no cover - guarded by the caller
            return None
        leaks: list[tree_sitter.Node] = []
        # Iterative, not recursive: SAFE105 polices this codebase.
        pending: list[tree_sitter.Node] = [body_node]
        while len(pending) > 0:
            block = pending.pop()
            leak = _propagation_leak_step(block, except_node, lang_name, pending)
            if leak is not None:
                leaks.append(leak)
        if not leaks:
            return None
        return min(leaks, key=lambda node: node.start_byte)

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
        log_methods = self._log_methods(lang_name)
        if any(call_name(node) in log_methods for node in walk(body, skip_types=tuple(function_types)) if node.type in CALL_TYPES):
            return True
        if lang_name != "cpp":
            return False
        return _cpp_body_has_stream_log(body, function_types) or _cpp_body_has_stderr_log(body, function_types)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag catch blocks that handle an error without any logging call."""
        lang_name = resolve_lang_name(filepath)
        # #198: the patterns this rule flags are conventional in test code, where
        # they were the overwhelming majority of its findings and were burying the
        # ones in library code. Whole-file answer, resolved before any walk.
        if skips_test_code(self.config, filepath, lang_name):
            return []
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
            if lang_name in (_js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _php.EXTRA_NAME, _cpp.EXTRA_NAME)
            else "Except block missing logging call - errors must be logged before being swallowed"
        )
        violations: list[Violation] = []
        for clause in _iter_catch_clauses(tree, lang_name):
            if not self._is_unlogged(clause, lang_name, function_types):
                continue
            violations.append(self._unlogged_violation(filepath, clause, lang_name, function_types, message))
        return violations

    def _unlogged_violation(self, filepath: str, clause: tree_sitter.Node, lang_name: str, function_types: frozenset[str], blanket_message: str) -> Violation:
        """Build the violation, anchored at the path that leaks when only some do.

        When the whole handler falls through, the clause is the right anchor - the
        handler as a unit is the problem. When it branches and only some arms
        propagate, pointing at the clause says "something in here leaks" and leaves
        the reader to find which; on a four-arm handler that is most of the work.
        Anchoring at the arm that falls through names it.

        The per-path message asserts that the OTHER paths re-raise, so it is used
        only when at least one statement in the handler actually propagates. A
        branching handler where NO arm raises is reported at the clause: there the
        per-path wording would state a fact about the code that is not true.
        """
        leak = self._propagation_leak(clause, lang_name)
        body = _catch_body(clause)
        branching = body is not None and bool(body.named_children) and body.named_children[-1].type in _CONDITIONAL_TYPES
        if leak is None or not branching or not self._has_propagating_statement(clause, lang_name, function_types):
            return self._make_violation_for_node(filepath, clause, blanket_message)
        return self._make_violation_for_node(
            filepath,
            leak,
            "This path leaves the error handler without logging or re-raising - other paths here do re-raise, so only this one swallows the error",
        )

    @staticmethod
    def _has_propagating_statement(clause: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> bool:
        """Return True if any statement in the handler propagates the caught error.

        Containment is the right test here, unlike in the verdict: this only
        chooses the wording. If something in the handler raises and some path
        still leaks, "other paths here do re-raise" is a true statement about the
        code; if nothing raises anywhere, it is not.
        """
        body = _catch_body(clause)
        if body is None:  # pragma: no cover - callers reach here only with a body
            return False
        return any(_statement_propagates(node, clause, lang_name) for node in walk(body, skip_types=tuple(function_types)))
