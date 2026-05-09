"""State & purity rules: global_state and global_mutation."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import VARIABLE_DECLARATION as _JS_VARIABLE_DECLARATION
from safelint.languages.python import (
    ASSIGNMENT,
    ASYNC_FUNCTION_DEF,
    AUGMENTED_ASSIGNMENT,
    CLASS_DEF,
    FUNCTION_DEF,
    GLOBAL_STATEMENT,
    IDENTIFIER,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _func_name(func_node: tree_sitter.Node) -> str:
    """Return the declared name of *func_node*, or ``"<anonymous>"``."""
    name_node = func_node.child_by_field_name("name")
    return node_text(name_node) if name_node else "<anonymous>"


def _iter_python_functions(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every Python function (sync or async) definition in *tree*."""
    for node in walk(tree.root_node):
        if node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
            yield node


def _iter_javascript_functions(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every JavaScript function definition in *tree*."""
    for node in walk(tree.root_node):
        if node.type in _JS_FUNCTION_TYPES:
            yield node


# Class bodies are their own scope: a `global X` declared inside a nested
# class belongs to that class body, not the enclosing function. Same for
# nested function definitions. Stop the per-function walk at any of these.
_PY_NESTED_SCOPE_TYPES = (FUNCTION_DEF, ASYNC_FUNCTION_DEF, CLASS_DEF)


def _iter_global_statements(func_node: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
    """Yield every ``global X, Y`` statement found inside *func_node*.

    Stops at nested function definitions: a ``global`` declared in an inner
    function belongs to that inner function's scope, not the outer one's.
    """
    for child in walk(func_node, skip_types=_PY_NESTED_SCOPE_TYPES):
        if child.type == GLOBAL_STATEMENT:
            yield child


def _global_identifiers(global_stmt: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the identifier nodes named in a ``global`` statement."""
    return [c for c in global_stmt.named_children if c.type == IDENTIFIER]


def _python_assignment_target(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the bare identifier target of *node* if it is one, else None.

    tree-sitter-python parses both regular and *annotated* assignments
    (``x = 1`` and ``x: int = 1``) as the same ``assignment`` node type
    — annotated form just adds ``:`` and ``type`` as inline children.
    ``child_by_field_name("left")`` correctly returns the identifier in
    both cases, so a single branch handles both.
    """
    if node.type in (ASSIGNMENT, AUGMENTED_ASSIGNMENT):
        left = node.child_by_field_name("left")
        return left if left is not None and left.type == IDENTIFIER else None
    return None


def _javascript_global_namespace_root(member_expr: tree_sitter.Node) -> str | None:
    """Walk a ``member_expression`` chain leftward and return the root identifier name.

    For ``globalThis.x``                  → ``"globalThis"``.
    For ``window.config``                 → ``"window"``.
    For ``process.env.NODE_ENV``          → ``"process"`` (walks past ``process.env``).
    For ``somelocal.field``               → ``"somelocal"`` (caller filters by namespace list).
    For ``arr[0].field``                  → ``None`` (subscript breaks the bare-identifier chain).

    Returns ``None`` if the chain doesn't terminate in a bare identifier
    (e.g. the receiver is a call result, a subscript, ``this``, etc.).
    """
    cur: tree_sitter.Node | None = member_expr
    while cur is not None and cur.type == "member_expression":  # nosafe: SAFE501
        cur = cur.child_by_field_name("object")
    if cur is None or cur.type != "identifier":
        return None
    return node_text(cur)


class GlobalStateRule(BaseRule):
    """Reject use of the ``global`` keyword inside functions.

    Python-only: there is no JavaScript equivalent of the ``global``
    keyword. JavaScript's ``global_mutation`` (SAFE302) covers JS's
    "writes to module-level state" cases; SAFE301 has no JS analogue
    that isn't already covered there.
    """

    name = "global_state"
    code = "SAFE301"

    def _violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return one violation per ``global`` statement inside *func*."""
        func_name = _func_name(func)
        return [
            self._make_violation_for_node(
                filepath,
                stmt,
                f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _global_identifiers(stmt))} - use dependency injection instead',
            )
            for stmt in _iter_global_statements(func)
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function that declares a global variable."""
        violations: list[Violation] = []
        for func in _iter_python_functions(tree):
            violations.extend(self._violations_for_func(filepath, func))
        return violations


class GlobalMutationRule(BaseRule):
    """Reject functions that write to module-level state.

    Python: fires on ``global x; x = ...`` patterns (or, with ``strict =
    true``, on every ``global`` declaration). JavaScript: fires on
    function-body assignments that target a configured global namespace
    member — ``globalThis.x = ...``, ``window.x = ...``, ``global.x = ...``
    (Node), ``self.x = ...`` (Web Workers), or ``process.env.X = ...``.
    The rule's intent ("don't mutate module-level state from inside a
    function") is the same in both languages even though the syntactic
    shape differs.
    """

    name = "global_mutation"
    code = "SAFE302"
    language = ("python", "javascript")

    _DEFAULT_GLOBAL_NAMESPACES_JAVASCRIPT: ClassVar[list[str]] = [
        "globalThis",  # universal — works in browsers, Node, web workers
        "window",  # browser
        "global",  # Node
        "self",  # Web Worker / browser fallback
        "process",  # Node — covers ``process.env.X = ...``, ``process.exitCode = ...``, etc.
    ]

    @staticmethod
    def _python_collect_global_names(func_node: tree_sitter.Node) -> set[str]:
        """Return all names declared via ``global`` inside *func_node*."""
        return {node_text(ident) for stmt in _iter_global_statements(func_node) for ident in _global_identifiers(stmt)}

    @staticmethod
    def _python_mutating_assignments(
        func_node: tree_sitter.Node,
        global_names: set[str],
    ) -> list[tuple[tree_sitter.Node, str]]:
        """Return (assignment_node, name) for each write to a declared global in *func_node*."""
        results: list[tuple[tree_sitter.Node, str]] = []
        for node in walk(func_node, skip_types=_PY_NESTED_SCOPE_TYPES):
            target = _python_assignment_target(node)
            if target is not None and node_text(target) in global_names:
                results.append((node, node_text(target)))
        return results

    def _python_violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return violations for global writes inside *func* (Python)."""
        global_names = self._python_collect_global_names(func)
        if not global_names:
            return []
        func_name = _func_name(func)
        if self.config.get("strict", False):
            # strict mode: fire on the ``global`` statement itself,
            # regardless of whether the name is later written to.
            return [
                self._make_violation_for_node(
                    filepath,
                    stmt,
                    f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _global_identifiers(stmt))} - globals must not be used (strict mode)',
                )
                for stmt in _iter_global_statements(func)
            ]
        return [
            self._make_violation_for_node(
                filepath,
                assignment,
                f'Function "{func_name}" writes to global "{name}" - globals must not be mutated',
            )
            for assignment, name in self._python_mutating_assignments(func, global_names)
        ]

    def _javascript_violations_for_func(
        self, filepath: str, func: tree_sitter.Node, namespaces: frozenset[str]
    ) -> list[Violation]:
        """Return violations for global-namespace writes inside *func* (JavaScript).

        Walks the function body for ``assignment_expression`` and
        ``augmented_assignment_expression`` nodes whose LHS is a
        ``member_expression`` rooted in one of *namespaces*. Skips nested
        function bodies (assignments there belong to that inner scope).
        """
        func_name = _func_name(func)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(_JS_FUNCTION_TYPES)):
            if node is func:
                continue
            if node.type not in ("assignment_expression", "augmented_assignment_expression"):
                continue
            left = node.child_by_field_name("left")
            if left is None or left.type != "member_expression":
                continue
            root = _javascript_global_namespace_root(left)
            if root is None or root not in namespaces:
                continue
            target_text = node_text(left)
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'Function "{func_name}" writes to global "{target_text}" - globals must not be mutated',
                )
            )
        return violations

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every write to a module-level state binding inside a function."""
        lang_name = resolve_lang_name(filepath)
        if lang_name == "python":
            return self._python_check(filepath, tree)
        return self._javascript_check(filepath, tree)

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the Python-specific check (``global`` keyword + write)."""
        violations: list[Violation] = []
        for func in _iter_python_functions(tree):
            violations.extend(self._python_violations_for_func(filepath, func))
        return violations

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the JavaScript-specific check (assignment to ``globalThis.*`` / ``window.*`` / etc.)."""
        namespaces = frozenset(
            self.config.get(
                "global_namespaces_javascript",
                self._DEFAULT_GLOBAL_NAMESPACES_JAVASCRIPT,
            )
        )
        violations: list[Violation] = []
        for func in _iter_javascript_functions(tree):
            violations.extend(self._javascript_violations_for_func(filepath, func, namespaces))
        return violations


class WideScopeDeclarationRule(BaseRule):
    """Reject ``var`` declarations — prefer ``let`` / ``const`` for narrower scope.

    Holzmann's Power-of-Ten Rule 6 ("Declare variables at the smallest
    possible scope") is C-flavoured but maps cleanly to a real
    JavaScript hazard: ``var`` is *function-scoped* and hoists to the
    top of the enclosing function (or module), while ``let`` / ``const``
    are *block-scoped*. A ``var`` declared in one branch is visible
    in every other branch of the same function — a classic source
    of accidental cross-branch reads and TDZ-like bugs that block
    scoping eliminates.

    The fix is mechanical: replace ``var`` with ``let`` (when the
    binding is reassigned) or ``const`` (when it isn't). The rule
    fires once per ``variable_declaration`` node — a multi-binding
    form like ``var x = 1, y = 2;`` produces a single violation
    (the line is the unit of fix, not each name).

    JavaScript-only: Python has no ``var`` / ``let`` / ``const``
    distinction. Python users get nothing from this rule; it's
    registered with ``language = ("javascript",)`` and the engine's
    per-language dispatch correctly skips it on ``.py`` / ``.pyw``
    files.
    """

    name = "wide_scope_declaration"
    code = "SAFE305"
    language = ("javascript",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every ``var`` declaration in the file."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _JS_VARIABLE_DECLARATION:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    "`var` declaration uses function-scope hoisting — replace with `let` or `const` for block scope",
                )
            )
        return violations
