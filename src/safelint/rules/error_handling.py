"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    CALL,
    EXCEPT_CLAUSE,
    FUNCTION_DEF,
    IDENTIFIER,
    RAISE_STATEMENT,
    TUPLE,
)
from safelint.rules.base import BaseRule, Suggestion, TextEdit


# Statement-only no-op nodes: their presence means "developer wrote something
# to satisfy the parser but didn't actually handle the exception".
_NOOP_STATEMENT_TYPES = frozenset({"pass_statement", "continue_statement"})

# Literal expression node types we treat as "comment-like" when they are the
# *sole* statement in an except body (e.g. ``except: 0``, ``except: "TODO"``,
# ``except: ...``). All produce no observable behaviour.
_LITERAL_EXPR_TYPES = frozenset(
    {
        "integer",
        "float",
        "string",
        "concatenated_string",
        "true",
        "false",
        "none",
        "ellipsis",
    }
)


def _is_noop_body(body_node: tree_sitter.Node | None) -> bool:
    """Return True if *body_node* contains only no-op statements.

    Catches:

    * ``except: pass``                     (pass_statement)
    * ``except: continue``                 (continue_statement)
    * ``except: ...``                      (ellipsis as expression_statement)
    * ``except: 0`` / ``except: None``    (literal expression statements)
    * ``except: "TODO"`` / ``except: ""``  (string-as-comment idiom)
    * ``except:`` with no body at all      (defensive — shouldn't happen with
      valid Tree-sitter output but kept for safety)

    Bodies with multiple statements never match — even if every statement is
    a literal, two literals signal *some* intentional structure (rare edge
    case, but preferable to false positives).

    Comments inside the body don't affect the result because Tree-sitter
    treats comments as separate nodes outside the block.
    """
    if body_node is None or not body_node.named_children:
        return True
    if len(body_node.named_children) != 1:
        return False
    stmt = body_node.named_children[0]
    if stmt.type in _NOOP_STATEMENT_TYPES:
        return True
    if stmt.type != "expression_statement":
        return False
    # expression_statement may wrap a single inner expression. Reach into it.
    inner = stmt.named_children[0] if stmt.named_children else None
    if inner is None:  # pragma: no cover — defensive; valid Python always has an inner expr
        return False
    return inner.type in _LITERAL_EXPR_TYPES or _is_string_literal_expression(inner)


def _is_string_literal_expression(node: tree_sitter.Node) -> bool:
    """Return True for f-strings or constant-string literals serving as no-op markers.

    Tree-sitter wraps formatted strings differently from regular strings; this
    helper accepts both so ``except: f""`` is also treated as a no-op body.
    Walks the underlying text to ensure no interpolated expressions
    (interpolated f-strings have side effects in principle, so we conservatively
    treat them as non-empty).
    """
    if node.type != "string":
        return False
    # Pure string literals (no f-string interpolation) have only string-content
    # children. f-strings include ``interpolation`` nodes — those carry side
    # effects so we don't treat them as no-ops.
    return all(child.type != "interpolation" for child in node.named_children) and bool(node_text(node))


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _iter_except_clauses(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every ``except_clause`` node in *tree*."""
    # except_clauses only appear inside try_statements in tree-sitter-python,
    # so a flat walk suffices; no need to filter by parent.
    for node in walk(tree.root_node):
        if node.type == EXCEPT_CLAUSE:
            yield node


def _except_body(except_node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the body block of *except_node*, or None if it has no body.

    The first branch (body field present) hits in normal code; the
    fallback (last named child) is defensive for AST shapes where the
    field isn't directly populated. Empty children should never happen
    in valid Python (an except always has a body or a single ``pass``).
    """
    body_node = except_node.child_by_field_name("body")
    if body_node is not None:
        return body_node
    named = except_node.named_children
    return named[-1] if named else None  # pragma: no cover


def _has_typed_exception(except_node: tree_sitter.Node) -> bool:
    """Return True when the except clause specifies one or more exception types."""
    # ``except ValueError as e:`` puts the type inside an ``as_pattern`` named child.
    return any(c.type in (IDENTIFIER, ATTRIBUTE, TUPLE, "as_pattern") for c in except_node.named_children)


def _bare_except_suggestion(except_node: tree_sitter.Node) -> Suggestion | None:
    """Build the "replace with ``except Exception:``" suggestion for a bare except clause.

    Returns ``None`` when the AST shape doesn't expose the colon child
    (defensive — Tree-sitter always produces it for valid Python).
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
    """Reject bare ``except:`` clauses that silently catch SystemExit and KeyboardInterrupt."""

    name = "bare_except"
    code = "SAFE201"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every except handler with no exception type specified."""
        violations: list[Violation] = []
        for clause in _iter_except_clauses(tree):
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
    """Reject except blocks whose body is empty (silent failure)."""

    name = "empty_except"
    code = "SAFE202"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every except handler whose body is effectively empty.

        Catches the obvious ``pass`` / ``continue`` no-ops plus the
        comment-like literal idioms (``except: ...``, ``except: 0``,
        ``except: "TODO"``) where the developer satisfied the parser
        without actually handling the exception.
        """
        return [
            self._make_violation_for_node(
                filepath,
                clause,
                "Empty except block - add error handling or a logging call",
            )
            for clause in _iter_except_clauses(tree)
            if _is_noop_body(_except_body(clause))
        ]


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except block that does not simply re-raise."""

    name = "logging_on_error"
    code = "SAFE203"

    _LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})

    def _only_reraises(self, except_node: tree_sitter.Node) -> bool:
        """Return True when the handler body is just a bare ``raise``."""
        body_node = _except_body(except_node)
        # Defensive — ``_except_body`` only returns None for malformed AST
        # that this rule can't sensibly classify anyway.
        if body_node is None:  # pragma: no cover
            return False
        stmts = body_node.named_children
        if len(stmts) != 1 or stmts[0].type != RAISE_STATEMENT:
            return False
        return not stmts[0].named_children

    def _has_log_call(self, except_node: tree_sitter.Node) -> bool:
        """Return True when the handler body contains at least one logging call.

        Walks only the body block (skipping the exception-type spec) and
        prunes nested ``def`` / ``async def`` so a logging call inside an
        inner function definition — which the except handler never actually
        executes — does not count as logging the caught error.
        """
        body = _except_body(except_node)
        if body is None:  # pragma: no cover
            return False
        return any(call_name(node) in self._LOG_METHODS for node in walk(body, skip_types=(FUNCTION_DEF, ASYNC_FUNCTION_DEF)) if node.type == CALL)

    def _is_unlogged(self, except_node: tree_sitter.Node) -> bool:
        """Return True when this except clause swallows an error without logging."""
        body_node = _except_body(except_node)
        # Empty body (no named children) means this rule's job is done by
        # ``empty_except`` (SAFE202); skip here. ``body_node is None`` is
        # the same defensive case as elsewhere.
        if body_node is None or not body_node.named_children:  # pragma: no branch
            return False
        return not self._only_reraises(except_node) and not self._has_log_call(except_node)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag except blocks that handle an error without any logging call."""
        return [
            self._make_violation_for_node(
                filepath,
                clause,
                "Except block missing logging call - errors must be logged before being swallowed",
            )
            for clause in _iter_except_clauses(tree)
            if self._is_unlogged(clause)
        ]
