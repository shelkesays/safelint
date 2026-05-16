"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    EXCEPT_CLAUSE,
    FUNCTION_DEF,
    IDENTIFIER,
    RAISE_STATEMENT,
    TUPLE,
)
from safelint.rules.base import BaseRule, Suggestion, TextEdit


# Per-language: which Tree-sitter node types are "the catch handler clause".
# Python: ``except_clause`` (a child of ``try_statement``).
# JavaScript: ``catch_clause`` (also a child of ``try_statement``).
# Java: ``catch_clause`` (same node name; same shape as JS apart from the
# typed-binding requirement that the language enforces upstream).
_CATCH_CLAUSE_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({EXCEPT_CLAUSE}),
    "javascript": frozenset({"catch_clause"}),
    "typescript": frozenset({"catch_clause"}),
    "java": frozenset({"catch_clause"}),
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
}

# Per-language: re-raise statement types. ``except: raise`` (Python),
# ``catch (e) { throw e; }`` (JavaScript), and ``catch (E e) { throw e; }``
# (Java) all pass the error up the stack, which the logging-on-error
# rule treats as legitimate handling.
_RERAISE_STATEMENT_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({RAISE_STATEMENT}),
    "javascript": frozenset({"throw_statement"}),
    "typescript": frozenset({"throw_statement"}),
    "java": frozenset({"throw_statement"}),
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
    "typescript": frozenset({"empty_statement"}),
    "java": frozenset({"line_comment", "block_comment"}),
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
}


def _is_noop_body(body_node: tree_sitter.Node | None, lang_name: str) -> bool:
    """Return True if *body_node* contains only no-op statements.

    Catches (varying by language):

    * Python ``except: pass`` / ``except: continue``     (pass_statement / continue_statement)
    * JavaScript ``catch (e) { ; }``                     (empty_statement)
    * Python ``except: ...``                             (ellipsis-as-expression-statement)
    * Numeric / boolean / null literals as a single statement
      (``except: 0``, ``catch (e) { null; }`` etc.)
    * String-as-comment idiom (``except: "TODO"``, ``catch (e) { "TODO"; }``)
    * Empty body / no statements at all                  (defensive - shouldn't
      happen with valid Tree-sitter output but kept for safety)

    Bodies with multiple statements never match - even if every statement is
    a literal, two literals signal *some* intentional structure (rare edge
    case, but preferable to false positives).

    Comments inside the body don't affect the result because Tree-sitter
    treats comments as separate nodes outside the block.
    """
    if body_node is None or not body_node.named_children:
        return True
    if len(body_node.named_children) != 1:
        return False
    return _stmt_is_noop(body_node.named_children[0], lang_name)


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


_STRING_LITERAL_PREDICATES: dict[str, Callable[[tree_sitter.Node], bool]] = {
    "python": _python_string_is_literal,
    "javascript": _js_string_is_literal,
    "typescript": _js_string_is_literal,
    "java": _java_string_is_literal,
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


def _caught_binding_name(catch_node: tree_sitter.Node, lang_name: str) -> str | None:
    """Return the variable name bound by the catch clause, or None if there isn't one.

    * JavaScript / TypeScript: ``catch (e)`` exposes the binding directly
      via the ``parameter`` field on ``catch_clause``. ``catch {}``
      (optional-binding form, ES2019+) has no parameter and returns None.
    * Java: ``catch (Type e)`` exposes the binding via the ``name`` field
      of a ``catch_formal_parameter`` named child of ``catch_clause``.
      Multi-catch ``catch (A | B e)`` follows the same shape - only the
      variable name is needed for the re-raise comparison.

    Returns the raw identifier text (e.g. ``"e"``) ready for the caller
    to compare against the body's ``throw e;`` argument. ``call_name``
    style normalisation is not appropriate here - exact byte equality
    is the contract.
    """
    if lang_name in ("javascript", "typescript"):
        param_node = catch_node.child_by_field_name("parameter")
        if param_node is None or param_node.type != "identifier":
            return None
        return node_text(param_node)
    if lang_name != "java":
        return None
    formal = _java_catch_formal_parameter(catch_node)
    if formal is None:
        return None
    name_node = formal.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return None
    return node_text(name_node)


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
    """Reject bare ``except:`` clauses that silently catch SystemExit and KeyboardInterrupt.

    Python-only: JavaScript ``try/catch`` always binds the caught error
    (or uses the optional-binding form ``catch {}`` which has different
    semantics - no risk of accidentally catching a process-level signal
    the way Python's bare ``except:`` does).
    """

    name = "bare_except"
    code = "SAFE201"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every except handler with no exception type specified."""
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
    language = ("python", "javascript", "typescript", "java")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every catch handler whose body is effectively empty."""
        lang_name = resolve_lang_name(filepath)
        # Match the violation message to the source language's terminology -
        # JavaScript / Java developers don't write ``except`` blocks. Same
        # message-selection pattern as ``LoggingOnErrorRule``.
        message = "Empty catch block - add error handling or a logging call" if lang_name in ("javascript", "typescript", "java") else "Empty except block - add error handling or a logging call"
        return [self._make_violation_for_node(filepath, clause, message) for clause in _iter_catch_clauses(tree, lang_name) if _is_noop_body(_catch_body(clause), lang_name)]


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except / catch block that does not simply re-raise.

    Cross-language: walks Python ``except_clause`` and JavaScript
    ``catch_clause`` uniformly. Re-raise (Python ``raise``, JavaScript
    ``throw``) is exempted in either language.
    """

    name = "logging_on_error"
    code = "SAFE203"
    language = ("python", "javascript", "typescript", "java")

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
        reraise_types = _RERAISE_STATEMENT_TYPES_BY_LANG[lang_name]
        if len(stmts) != 1 or stmts[0].type not in reraise_types:
            return False
        children = stmts[0].named_children
        if lang_name == "python":
            # Bare ``raise`` has no children.
            return not children
        # JS / TS / Java: ``throw <identifier>;`` only counts as a re-raise
        # when ``<identifier>`` is the exact name bound by the
        # ``catch`` clause. Without a caught binding (``catch {}``)
        # there is no name to re-raise, so any throw there is a fresh
        # error and the rule still requires logging.
        if len(children) != 1 or children[0].type != "identifier":
            return False
        param_text = _caught_binding_name(except_node, lang_name)
        if param_text is None:
            return False
        return node_text(children[0]) == param_text

    def _has_log_call(self, except_node: tree_sitter.Node, function_types: frozenset[str]) -> bool:
        """Return True when the handler body contains at least one logging call.

        Walks only the body block (skipping the exception-type spec) and
        prunes nested function bodies so a logging call inside an inner
        function definition - which the catch handler never actually
        executes - does not count as logging the caught error.
        """
        body = _catch_body(except_node)
        if body is None:  # pragma: no cover
            return False
        return any(call_name(node) in self._LOG_METHODS for node in walk(body, skip_types=tuple(function_types)) if node.type in CALL_TYPES)

    def _is_unlogged(self, except_node: tree_sitter.Node, lang_name: str, function_types: frozenset[str]) -> bool:
        """Return True when this catch clause swallows an error without logging."""
        body_node = _catch_body(except_node)
        # Empty body (no named children) means this rule's job is done by
        # ``empty_except`` (SAFE202); skip here. ``body_node is None`` is
        # the same defensive case as elsewhere.
        if body_node is None or not body_node.named_children:  # pragma: no branch
            return False
        return not self._only_reraises(except_node, lang_name) and not self._has_log_call(except_node, function_types)

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
            if lang_name in ("javascript", "typescript", "java")
            else "Except block missing logging call - errors must be logged before being swallowed"
        )
        return [self._make_violation_for_node(filepath, clause, message) for clause in _iter_catch_clauses(tree, lang_name) if self._is_unlogged(clause, lang_name, function_types)]
