"""State & purity rules: global_state (SAFE301, Python-only), global_mutation (SAFE302), and wide_scope_declaration (SAFE305, JS-family - JavaScript and TypeScript)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.javascript import VARIABLE_DECLARATION as _JS_VARIABLE_DECLARATION
from safelint.languages.php import FUNCTION_TYPES as _PHP_FUNCTION_TYPES
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


def _c_declarator_identifier(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the name ``identifier`` from a C declaration's declarator child, or None.

    Direct declarator forms on a ``declaration``: a bare ``identifier``
    (``int x;``), ``init_declarator`` (``int x = 1;``), ``pointer_declarator``
    (``int *p;``), ``array_declarator`` (``int a[10];``), and the
    ``function_declarator`` of a function-pointer variable (``int (*fp)(int);``,
    whose declarator is a ``parenthesized_declarator``). Each wraps its inner
    name on the ``declarator`` field, so the unwrap is an iterative loop
    (bounded; SAFE105 polices recursion in this codebase) down to the
    ``identifier``. Non-declarator children (``primitive_type``,
    ``type_qualifier``, ``storage_class_specifier``) return None.
    """
    if node.type not in ("init_declarator", "pointer_declarator", "array_declarator", "function_declarator", "parenthesized_declarator", "identifier"):
        return None
    cur: tree_sitter.Node | None = node
    for _ in range(16):  # bounded unwrap; never recurse
        if cur is None:
            return None
        if cur.type == "identifier":
            return cur
        nxt = cur.child_by_field_name("declarator")
        # ``parenthesized_declarator`` (``(*fp)``) wraps its inner declarator as
        # a plain named child rather than on a ``declarator`` field.
        if nxt is None and cur.type == "parenthesized_declarator" and cur.named_children:
            nxt = cur.named_children[0]
        cur = nxt
    return None


def _c_is_function_prototype(function_declarator: tree_sitter.Node) -> bool:
    """Return True if a ``function_declarator`` is a real prototype, not a function-pointer variable.

    A prototype (``int foo(void);``) names an ``identifier`` directly; a
    file-scope function-pointer *variable* (``int (*fp)(int);``) wraps a
    ``parenthesized_declarator`` and IS mutable shared state, so it must NOT be
    exempted from SAFE302.
    """
    inner = function_declarator.child_by_field_name("declarator")
    return inner is None or inner.type != "parenthesized_declarator"


def _c_inner_function_declarator(declarator: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the ``function_declarator`` at the head of *declarator*, or None.

    Unwraps a leading ``init_declarator`` / ``pointer_declarator`` chain: a
    *pointer-returning* prototype (``char *foo(void);``) wraps its
    ``function_declarator`` in a ``pointer_declarator``, so the prototype check
    must look past the pointer. The walk stops at the first non-wrapper node,
    so a function-pointer *variable* (``int (*fp)(int);`` - a ``function_declarator``
    around a ``parenthesized_declarator``) is returned as-is and later classified
    by ``_c_is_function_prototype``. Bounded loop; never recurses.
    """
    cur: tree_sitter.Node | None = declarator
    for _ in range(16):
        if cur is None:
            return None
        if cur.type == "function_declarator":
            return cur
        if cur.type not in ("init_declarator", "pointer_declarator"):
            return None
        cur = cur.child_by_field_name("declarator")
    return None


def _c_unwrap_init(declarator: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the underlying declarator, unwrapping a single ``init_declarator`` (``int *p = 0`` -> ``*p``)."""
    if declarator.type == "init_declarator":
        return declarator.child_by_field_name("declarator")
    return declarator


def _c_is_mutable_pointer(declarator: tree_sitter.Node) -> bool:
    """Return True if *declarator* binds a mutable pointer.

    A ``pointer_declarator`` (``int *p``) whose pointer is not itself
    ``const``-qualified is a mutable pointer. ``const int *p`` declares a *const
    pointee* but a mutable pointer, so the binding is still shared mutable state
    and a declaration-level ``const`` does NOT exempt it. ``const int *const p``
    (the pointer itself is ``const``) carries a ``type_qualifier`` inside the
    ``pointer_declarator`` and is genuinely immutable.
    """
    inner = _c_unwrap_init(declarator)
    if inner is None or inner.type != "pointer_declarator":
        return False
    return not any(c.type == "type_qualifier" and node_text(c) == "const" for c in inner.named_children)


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
    (``x = 1`` and ``x: int = 1``) as the same ``assignment`` node type.
    The annotated form just adds ``:`` and ``type`` as inline children.
    ``child_by_field_name("left")`` correctly returns the identifier in
    both cases, so a single branch handles both.
    """
    if node.type in (ASSIGNMENT, AUGMENTED_ASSIGNMENT):
        left = node.child_by_field_name("left")
        return left if left is not None and left.type == IDENTIFIER else None
    return None


# --- PHP helpers (SAFE301 global_state, SAFE302 global_mutation) -------------
# A ``global`` declared inside a nested closure belongs to that closure, so the
# per-function walks stop at nested PHP function nodes. Methods are separate
# functions (each handled by ``_iter_php_functions``), and a bare ``global``
# only ever appears inside a function/method body, so functions are the only
# scope boundary needed.
_PHP_NESTED_SCOPE_TYPES = tuple(_PHP_FUNCTION_TYPES)


def _iter_php_functions(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every PHP function / method / closure definition in *tree*."""
    for node in walk(tree.root_node):
        if node.type in _PHP_FUNCTION_TYPES:
            yield node


def _iter_php_global_statements(func_node: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
    """Yield every ``global $x, $y;`` statement inside *func_node*.

    Stops at nested function definitions: a ``global`` declared in an inner
    closure belongs to that closure's scope, not the outer function's.
    """
    for child in walk(func_node, skip_types=_PHP_NESTED_SCOPE_TYPES):
        if child.type == "global_declaration":
            yield child


def _php_global_identifiers(global_stmt: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Return the ``variable_name`` nodes named in a PHP ``global`` statement."""
    return [c for c in global_stmt.named_children if c.type == "variable_name"]


def _php_assignment_target(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the mutated target of a PHP assignment / compound assignment / inc-dec, else None.

    ``$x = ...`` / ``$x += ...`` expose the target on the ``left`` field;
    ``$x++`` / ``--$x`` (``update_expression``) expose it on the ``argument``
    field. Catching the increment / decrement forms means a write to a
    declared global via ``$counter++`` is flagged like ``$counter = ...``.
    """
    if node.type in ("assignment_expression", "augmented_assignment_expression"):
        return node.child_by_field_name("left")
    if node.type == "update_expression":
        return node.child_by_field_name("argument")
    return None


def _php_subscript_root(target: tree_sitter.Node) -> str | None:
    """Return the root ``variable_name`` text of a (possibly chained) subscript, else None.

    ``$GLOBALS['x']`` -> ``"$GLOBALS"``; ``$GLOBALS['a']['b']`` -> ``"$GLOBALS"``
    (the outer subscript's base is the inner subscript, so walk leftward to the
    root variable). Returns None when the base is not a bare variable.
    """
    cur: tree_sitter.Node | None = target
    while cur is not None:
        if cur.type != "subscript_expression":
            break
        cur = cur.named_children[0] if cur.named_children else None
    if cur is None or cur.type != "variable_name":
        return None
    return node_text(cur)


#: Node types that are pure compile-time / no-op-at-runtime annotations
#: in the JS-family AST. Unwrapping them recovers the underlying
#: ownership-chain expression - `(globalThis as any).x = 1` writes to
#: the same global as `globalThis.x = 1`, and the `!` non-null
#: assertion / `satisfies` clause / parens are all the same shape.
_PASSTHROUGH_WRAPPER_TYPES = frozenset(
    {
        "type_assertion",  # TS: ``<Foo>x`` (angle-bracket cast, equivalent to ``as``)
        "parenthesized_expression",
        "as_expression",  # TS: ``x as Foo``
        "satisfies_expression",  # TS: ``x satisfies Foo``
        "non_null_expression",  # TS: ``x!``
    }
)


def _unwrap_passthrough_wrappers(node: tree_sitter.Node | None) -> tree_sitter.Node | None:
    """Strip every layer of pass-through wrapper around *node*.

    Pass-through wrappers in the JS family are nodes that don't change
    the underlying ownership chain at runtime - parentheses
    (``(globalThis).x``), TypeScript type assertions
    (``(globalThis as any).x``), ``satisfies`` clauses, and non-null
    assertions (``globalThis!.x``). All of them produce the same write
    at runtime; the wrapping is purely syntactic / type-system metadata.

    Without unwrapping, every left-walk step that lands on one of these
    wrappers would break the bare-identifier check at the end of
    :func:`_javascript_global_namespace_root` (and the LHS-type filter
    in :meth:`GlobalMutationRule._javascript_violations_for_func`) and
    silently skip the violation - particularly painful for TypeScript
    code where the ``(globalThis as any).foo = ...`` pattern is the
    standard escape hatch for adding properties to the global object.
    """
    cur = node
    while cur is not None:
        if cur.type not in _PASSTHROUGH_WRAPPER_TYPES:
            break
        # Pick the expression child. Most wrappers
        # (``parenthesized_expression`` / ``as_expression`` /
        # ``satisfies_expression`` / ``non_null_expression``) have the
        # expression as the FIRST named child - the type (when present)
        # is the second. ``type_assertion`` (TS angle-bracket cast
        # ``<Foo>x``) is the exception: it has the type FIRST and the
        # expression SECOND.
        named = cur.named_children
        if not named:
            return None
        cur = named[1] if cur.type == "type_assertion" and len(named) >= 2 else named[0]
    return cur


def _javascript_global_namespace_root(target: tree_sitter.Node) -> str | None:
    """Walk a member / subscript chain leftward and return the root identifier name.

    For ``globalThis.x``                  → ``"globalThis"``.
    For ``globalThis['x']``               → ``"globalThis"`` (bracket notation).
    For ``window.config``                 → ``"window"``.
    For ``window["config"]["x"]``         → ``"window"`` (chained subscripts).
    For ``process.env.NODE_ENV``          → ``"process"``.
    For ``process.env["NODE_ENV"]``       → ``"process"`` (mixed dot + bracket).
    For ``(globalThis).x``                → ``"globalThis"`` (paren-wrapped root).
    For ``((process).env).NODE_ENV``      → ``"process"`` (nested paren steps).
    For ``somelocal.field``               → ``"somelocal"`` (caller filters by namespace list).
    For ``arr[0]().field``                → ``None`` (call result breaks the bare-identifier chain).

    Returns ``None`` if the chain doesn't terminate in a bare identifier
    (e.g. the receiver is a call result, ``this``, etc.). ``member_expression``
    and ``subscript_expression`` are walked uniformly because they share the
    ``object`` field name and serve the same ownership-chain semantics.
    Parentheses are unwrapped on entry and after each leftward step
    because they do not change the underlying ownership chain.
    """
    cur = _unwrap_passthrough_wrappers(target)
    while cur is not None:
        if cur.type not in ("member_expression", "subscript_expression"):
            break
        cur = _unwrap_passthrough_wrappers(cur.child_by_field_name("object"))
    if cur is None or cur.type != "identifier":
        return None
    return node_text(cur)


class GlobalStateRule(BaseRule):
    """Reject use of the ``global`` keyword inside functions.

    Python and PHP only: both have a literal ``global`` keyword that pulls
    module / file-scope state into a function. JavaScript / TypeScript / Java
    / Rust / Go have no such keyword (their shared-mutable-state shapes are
    covered by ``global_mutation`` SAFE302), so SAFE301 has no analogue
    there. PHP is SAFE301's first non-Python registration.
    """

    name = "global_state"
    code = "SAFE301"
    language = ("python", "php")

    def _violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return one violation per ``global`` statement inside *func* (Python)."""
        func_name = _func_name(func)
        return [
            self._make_violation_for_node(
                filepath,
                stmt,
                f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _global_identifiers(stmt))} - use dependency injection instead',
            )
            for stmt in _iter_global_statements(func)
        ]

    def _php_violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return one violation per ``global`` statement inside *func* (PHP)."""
        func_name = _func_name(func)
        return [
            self._make_violation_for_node(
                filepath,
                stmt,
                f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _php_global_identifiers(stmt))} - use dependency injection instead',
            )
            for stmt in _iter_php_global_statements(func)
        ]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag any function that declares a global variable."""
        violations: list[Violation] = []
        if resolve_lang_name(filepath) == "php":
            for func in _iter_php_functions(tree):
                violations.extend(self._php_violations_for_func(filepath, func))
            return violations
        for func in _iter_python_functions(tree):
            violations.extend(self._violations_for_func(filepath, func))
        return violations


class GlobalMutationRule(BaseRule):
    """Reject shared module-level / global mutable state.

    Python: fires on ``global x; x = ...`` patterns (or, with ``strict =
    true``, on every ``global`` declaration). JavaScript / TypeScript: fires
    on function-body assignments that target a configured global namespace
    member - ``globalThis.x = ...``, ``window.x = ...``, ``global.x = ...``
    (Node), ``self.x = ...`` (Web Workers), or ``process.env.X = ...``.
    Java: fires at the declaration site on non-``final`` ``static`` fields
    (Java's shared-mutable-state shape); ``static final`` fields, instance
    fields, and locals are clean.
    Go: fires at the declaration site on every package-level ``var``
    (Go's shared-mutable-state shape); ``const`` declarations and
    block-scoped ``var`` / ``:=`` inside functions are clean. Sentinel
    errors (``var ErrX = errors.New(...)``) are flagged too - the rule is
    faithful to the declaration site and does not special-case the
    initializer; treat them as immutable by suppressing with a per-file
    ignore or ``//nosafe`` if desired.

    The rule's intent ("don't keep shared mutable state at module / global
    scope", Holzmann rule 6) is the same across languages even though the
    syntactic shape differs.
    """

    name = "global_mutation"
    code = "SAFE302"
    language = ("python", "javascript", "typescript", "java", "go", "php", "c", "cpp")

    _DEFAULT_GLOBAL_NAMESPACES_JAVASCRIPT: ClassVar[list[str]] = [
        "globalThis",  # universal - works in browsers, Node, web workers
        "window",  # browser
        "global",  # Node
        "self",  # Web Worker / browser fallback
        "process",  # Node - covers ``process.env.X = ...``, ``process.exitCode = ...``, etc.
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

    def _javascript_violations_for_func(self, filepath: str, func: tree_sitter.Node, namespaces: frozenset[str]) -> list[Violation]:
        """Return violations for global-namespace writes inside *func* (JavaScript).

        Walks the function body for ``assignment_expression``,
        ``augmented_assignment_expression``, and ``update_expression``
        (``++`` / ``--``) nodes whose target is a ``member_expression``
        rooted in one of *namespaces*. Skips nested function bodies
        (assignments there belong to that inner scope).
        """
        func_name = _func_name(func)
        violations: list[Violation] = []
        for node in walk(func, skip_types=tuple(_JS_FUNCTION_TYPES)):
            if node is func:
                continue
            if node.type not in ("assignment_expression", "augmented_assignment_expression", "update_expression"):
                continue
            # ``assignment_expression`` / ``augmented_assignment_expression`` use
            # the ``left`` field for the LHS; ``update_expression`` (``x++`` /
            # ``--y``) uses ``argument`` for the operand.
            target = node.child_by_field_name("argument") if node.type == "update_expression" else node.child_by_field_name("left")
            # Unwrap a paren-wrapped target so ``(globalThis.x) = 1``
            # and ``((process).exitCode)++`` are recognised - without
            # this the LHS-type filter would reject the
            # ``parenthesized_expression`` wrapper and skip the write
            # entirely.
            target = _unwrap_passthrough_wrappers(target)
            if target is None or target.type not in ("member_expression", "subscript_expression"):
                continue
            root = _javascript_global_namespace_root(target)
            if root is None or root not in namespaces:
                continue
            target_text = node_text(target)
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
        # Dedicated per-language checkers (declaration-site detection); every
        # other language routes through the JS-family assignment-site checker.
        dedicated = {
            "python": self._python_check,
            "java": self._java_check,
            "go": self._go_check,
            "php": self._php_check,
            "c": self._c_check,
            "cpp": self._cpp_check,
        }.get(lang_name)
        if dedicated is not None:
            return dedicated(filepath, tree)
        return self._javascript_check(filepath, tree, lang_name)

    def _cpp_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag file-, namespace-, and class-static translation-unit-scoped mutable state (C++).

        Extends the C shape by descending into ``namespace_definition`` and
        ``extern "C"`` (``linkage_specification``) bodies - a variable declared
        directly there is still translation-unit-scoped shared mutable state -
        and into ``class_specifier`` / ``struct_specifier`` bodies to reach
        ``static`` data members (a ``static`` member is one translation-unit
        location, not per-instance state; non-static fields are per-instance and
        do not fire). The per-declaration exemptions (``const`` / ``constexpr``,
        ``extern`` forward references, function prototypes) are reused from
        ``_c_declaration_violations``. A worklist keeps the traversal iterative
        (SAFE105 polices recursion).
        """
        violations: list[Violation] = []
        scopes: list[tree_sitter.Node] = [tree.root_node]
        while len(scopes) > 0:
            for node in scopes.pop().named_children:
                node_violations, child_scopes = self._cpp_scope_node(filepath, node)
                violations.extend(node_violations)
                scopes.extend(child_scopes)
        return violations

    #: Scope-introducing node types whose body is walked for further declarations.
    #: ``namespace_definition`` / ``linkage_specification`` (``extern "C"``)
    #: expose a ``declaration_list``; ``class_specifier`` / ``struct_specifier``
    #: expose a ``field_declaration_list`` whose ``static`` members are TU-scoped.
    _CPP_SCOPE_BODY_TYPES: ClassVar[tuple[str, ...]] = ("namespace_definition", "linkage_specification", "class_specifier", "struct_specifier")

    def _cpp_scope_node(self, filepath: str, node: tree_sitter.Node) -> tuple[list[Violation], list[tree_sitter.Node]]:
        """Classify one scope node into (violations, child scopes to walk).

        A ``declaration`` yields its file-scope variable violations; a
        ``field_declaration`` yields a violation only when it is a ``static``
        (translation-unit-scoped) data member; the scope-introducing types in
        :data:`_CPP_SCOPE_BODY_TYPES` yield their body as a further scope.
        """
        if node.type == "declaration":
            return self._c_declaration_violations(filepath, node), []
        if node.type == "field_declaration":
            return self._cpp_static_member_violations(filepath, node), []
        if node.type in self._CPP_SCOPE_BODY_TYPES:
            body = node.child_by_field_name("body")
            return [], [body] if body is not None else []
        return [], []

    def _cpp_static_member_violations(self, filepath: str, field_decl: tree_sitter.Node) -> list[Violation]:
        """Return a violation for a ``static`` (non-``const``) data member, else none.

        A ``static`` class / struct data member is one translation-unit-scoped
        mutable location, so it is shared mutable state; a non-static field is
        per-instance and does not fire. ``const`` / ``constexpr`` members are
        immutable and exempt. The member name is a ``field_identifier`` (unlike a
        file-scope ``declaration``'s bare ``identifier``), so it is located by a
        subtree scan; the type sits on a separate ``type`` field, so no type
        identifier leaks in.
        """
        is_static = any(c.type == "storage_class_specifier" and node_text(c) == "static" for c in field_decl.named_children)
        if not is_static:
            return []
        is_immutable = any(c.type == "type_qualifier" and node_text(c) in ("const", "constexpr") for c in field_decl.named_children)
        if is_immutable:
            return []
        # One violation per declared name: ``static int a, b;`` declares two
        # translation-unit-scoped members, so both ``a`` and ``b`` must fire.
        names = [c for c in walk(field_decl) if c.type == "field_identifier"]
        return [
            self._make_violation_for_node(
                filepath,
                name,
                f'Static data member "{node_text(name)}" is translation-unit-shared mutable state - use `const` / `constexpr` if it never changes (Power of Ten rule 6)',
            )
            for name in names
        ]

    def _c_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every file-scope mutable variable declaration (C's shared-mutable-state shape).

        Declaration-site detection (like Java / Go): a file-scope variable IS
        the shared mutable binding regardless of where it is written. Iterating
        the translation unit's direct children excludes block-scoped locals
        structurally (they nest under a ``compound_statement``). ``const``
        declarations are immutable and never fire; function prototypes
        (``int f(void);``), ``typedef``s, and ``extern`` forward references are
        not definitions of state and are skipped. ``static`` file-scope
        variables DO count - they are shared within the translation unit.
        A file-scope function-pointer *variable* (``int (*fp)(int);``) is
        mutable shared state and DOES fire: it is distinguished from a real
        prototype by ``_c_is_function_prototype`` (the function-pointer wraps a
        ``parenthesized_declarator``, a prototype names an identifier directly).
        """
        violations: list[Violation] = []
        for node in tree.root_node.named_children:
            if node.type == "declaration":
                violations.extend(self._c_declaration_violations(filepath, node))
        return violations

    def _c_declaration_violations(self, filepath: str, decl: tree_sitter.Node) -> list[Violation]:
        """Return one violation per declared variable name in a file-scope declaration.

        ``const`` and ``extern`` are declaration-level specifiers but their
        exemptions are per declarator: ``const int *p`` (mutable pointer) still
        fires despite the ``const``, and in a mixed ``extern int a, b = 1;`` the
        forward reference ``a`` is exempt while the definition ``b`` fires.
        """
        # C++ ``constexpr`` is an immutable compile-time binding, exempt like ``const``
        # (a C23 ``constexpr`` is likewise immutable, so this is safe for C too).
        # ``constinit`` is NOT exempt - it only fixes initialisation timing; the
        # variable remains mutable shared state afterwards.
        decl_const = any(child.type == "type_qualifier" and node_text(child) in ("const", "constexpr") for child in decl.named_children)
        decl_extern = any(child.type == "storage_class_specifier" and node_text(child) == "extern" for child in decl.named_children)
        out: list[Violation] = []
        for child in decl.named_children:
            ident = _c_declarator_identifier(child)
            # No ``_`` blank-identifier skip here: unlike Go / Python, C has no
            # blank identifier, so ``int _;`` is a real file-scope mutable variable.
            if ident is not None and not self._c_declarator_is_exempt(child, decl_const=decl_const, decl_extern=decl_extern):
                out.append(
                    self._make_violation_for_node(
                        filepath,
                        ident,
                        f'File-scope variable "{node_text(ident)}" is shared mutable state - scope it to its consumer, or use `const` if it never changes (Power of Ten rule 6)',
                    )
                )
        return out

    @staticmethod
    def _c_declarator_is_exempt(declarator: tree_sitter.Node, *, decl_const: bool, decl_extern: bool) -> bool:
        """Return True if a single *declarator* is not a mutable variable definition.

        A function prototype (``int f(void);`` or the pointer-returning
        ``char *foo(void);``) is never a variable. Under a declaration-level
        ``extern`` a declarator *without* an initialiser is a forward reference,
        not a definition (so ``extern int a, b = 1;`` exempts ``a`` but not the
        initialised ``b``). Under a declaration-level ``const`` an immutable
        object is exempt, but a mutable pointer (``const int *p`` - const
        pointee, mutable pointer) still fires.
        """
        fn = _c_inner_function_declarator(declarator)
        if fn is not None and _c_is_function_prototype(fn):
            return True
        if decl_extern and declarator.type != "init_declarator":
            return True
        if not decl_const:
            return False
        return not _c_is_mutable_pointer(declarator)

    def _go_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every package-level ``var`` declaration (Go's shared-mutable-state shape).

        Declaration-site detection (like Java): a package ``var`` IS the
        shared mutable binding regardless of where it is written, and a
        single pass over the file's top-level ``var_declaration`` children
        has near-zero false positives. ``const`` declarations are immutable
        and never fire. Block-scoped ``var`` / ``:=`` inside function bodies
        are locals - they are nested below a ``block``, never a direct child
        of ``source_file``, so iterating the root's named children excludes
        them structurally.
        """
        violations: list[Violation] = []
        for node in tree.root_node.named_children:
            if node.type == "var_declaration":
                violations.extend(self._go_var_violations(filepath, node))
        return violations

    def _go_var_violations(self, filepath: str, var_decl: tree_sitter.Node) -> list[Violation]:
        """Return violations for every name declared in a package-level ``var`` block.

        The single form ``var x int`` holds the ``var_spec`` directly; the
        grouped form ``var ( a int; b, c string )`` wraps several
        ``var_spec`` nodes in a ``var_spec_list``. Both shapes are handled by
        looking only at the declaration's direct ``var_spec`` children (and
        one level into ``var_spec_list``) - NOT a full ``walk``, which would
        descend into initialiser expressions and wrongly report a ``var``
        declared inside a function-literal initialiser as package-level state.
        """
        out: list[Violation] = []
        for child in var_decl.named_children:
            if child.type == "var_spec":
                out.extend(self._go_spec_violations(filepath, child))
            elif child.type == "var_spec_list":
                out.extend(self._go_spec_list_violations(filepath, child))
        return out

    def _go_spec_list_violations(self, filepath: str, spec_list: tree_sitter.Node) -> list[Violation]:
        """Return violations for every ``var_spec`` inside a grouped ``var ( ... )`` block."""
        out: list[Violation] = []
        for spec in spec_list.named_children:
            if spec.type == "var_spec":
                out.extend(self._go_spec_violations(filepath, spec))
        return out

    def _go_spec_violations(self, filepath: str, spec: tree_sitter.Node) -> list[Violation]:
        """Return one violation per declared identifier in a ``var_spec``.

        Only the spec's direct ``identifier`` children are names; the type
        (``type_identifier``) and any initializer (nested in
        ``expression_list``) are not direct ``identifier`` children, so they
        are excluded without extra filtering. The blank identifier ``_`` is
        skipped - ``var _ io.Reader = (*T)(nil)`` is a compile-time interface
        assertion, not mutable state.
        """
        return [
            self._make_violation_for_node(
                filepath,
                ident,
                f'Package-level var "{node_text(ident)}" is shared mutable state - scope it to its consumer, or use `const` if it never changes (Power of Ten rule 6)',
            )
            for ident in spec.named_children
            if ident.type == "identifier" and node_text(ident) != "_"
        ]

    def _java_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag non-final ``static`` field declarations (Java's shared-mutable-state shape).

        Declaration-site detection (not write-site): a mutable static
        field IS the smallest-scope violation regardless of where it is
        written, and a single tree walk over ``field_declaration`` nodes
        has near-zero false positives. ``static final`` fields are clean
        even when their referent is interiorly mutable (e.g. a
        ``static final List``); detecting interior mutability would need
        type resolution safelint does not do, so it is a documented v1
        exclusion. Interface fields are implicitly ``public static final``
        and parse without a ``static`` modifier here, so they never fire.
        """
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "field_declaration":
                continue
            modifiers = self._java_modifier_set(node)
            if "static" not in modifiers or "final" in modifiers:
                continue
            violations.extend(self._java_field_violations(filepath, node))
        return violations

    def _java_field_violations(self, filepath: str, field_node: tree_sitter.Node) -> list[Violation]:
        """Return one violation per declared variable on a non-final static field.

        A single Java ``field_declaration`` can declare several variables
        (``static int a = 1, b = 2;``); each is its own shared-mutable-state
        violation, so emit one per ``variable_declarator``, positioned on and
        named after that declarator.
        """
        out: list[Violation] = []
        for child in field_node.named_children:
            if child.type != "variable_declarator":
                continue
            name = child.child_by_field_name("name")
            field_name = node_text(name) if name is not None else "<field>"
            out.append(
                self._make_violation_for_node(
                    filepath,
                    child,
                    f'Non-final static field "{field_name}" is shared mutable state - declare it `final`, or scope the state to its consumer (Power of Ten rule 6)',
                )
            )
        return out

    @staticmethod
    def _java_modifier_set(field_node: tree_sitter.Node) -> set[str]:
        """Return the set of plain modifier keywords on a Java ``field_declaration``.

        Only bare keyword children of the ``modifiers`` node are collected
        (``static`` / ``final`` / ``public`` / ...); annotation children
        (``@Autowired`` etc.) are skipped because they are not ``modifier``
        keyword tokens.
        """
        for child in field_node.named_children:
            if child.type == "modifiers":
                return {node_text(kw) for kw in child.children if not kw.is_named}
        return set()

    def _python_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the Python-specific check (``global`` keyword + write)."""
        violations: list[Violation] = []
        for func in _iter_python_functions(tree):
            violations.extend(self._python_violations_for_func(filepath, func))
        return violations

    @staticmethod
    def _php_collect_global_names(func_node: tree_sitter.Node) -> set[str]:
        """Return all variable names declared via ``global`` inside *func_node* (PHP)."""
        return {node_text(ident) for stmt in _iter_php_global_statements(func_node) for ident in _php_global_identifiers(stmt)}

    @staticmethod
    def _php_mutating_assignments(func_node: tree_sitter.Node, global_names: set[str]) -> list[tuple[tree_sitter.Node, str]]:
        """Return (assignment_node, name) for each write to a declared global in *func_node* (PHP)."""
        results: list[tuple[tree_sitter.Node, str]] = []
        for node in walk(func_node, skip_types=_PHP_NESTED_SCOPE_TYPES):
            target = _php_assignment_target(node)
            if target is not None and target.type == "variable_name" and node_text(target) in global_names:
                results.append((node, node_text(target)))
        return results

    def _php_violations_for_func(self, filepath: str, func: tree_sitter.Node) -> list[Violation]:
        """Return violations for ``global $x; $x = ...`` writes inside *func* (PHP).

        Mirrors the Python shape: a ``global`` declaration brings file-scope
        state into the function, and a later write to that name mutates shared
        state. ``strict`` mode fires on the ``global`` declaration itself.
        """
        global_names = self._php_collect_global_names(func)
        if not global_names:
            return []
        func_name = _func_name(func)
        if self.config.get("strict", False):
            return [
                self._make_violation_for_node(
                    filepath,
                    stmt,
                    f'Function "{func_name}" declares global: {", ".join(node_text(c) for c in _php_global_identifiers(stmt))} - globals must not be used (strict mode)',
                )
                for stmt in _iter_php_global_statements(func)
            ]
        return [
            self._make_violation_for_node(
                filepath,
                assignment,
                f'Function "{func_name}" writes to global "{name}" - globals must not be mutated',
            )
            for assignment, name in self._php_mutating_assignments(func, global_names)
        ]

    def _php_globals_writes(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Return violations for ``$GLOBALS[...]`` superglobal writes anywhere in *tree* (PHP).

        ``$GLOBALS['x'] = ...`` mutates shared state without needing a
        ``global`` declaration, so this is a separate, file-wide pass. The
        two PHP shapes are disjoint (bare variable vs ``$GLOBALS`` subscript),
        so there is no double counting with ``_php_violations_for_func``.
        """
        out: list[Violation] = []
        for node in walk(tree.root_node):
            target = _php_assignment_target(node)
            if target is None or target.type != "subscript_expression":
                continue
            if _php_subscript_root(target) != "$GLOBALS":
                continue
            out.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'Write to "{node_text(target)}" mutates the $GLOBALS superglobal - shared state must not be mutated (Power of Ten rule 6)',
                )
            )
        return out

    def _php_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Run the PHP-specific check (``global`` keyword + write, plus ``$GLOBALS[...]`` writes)."""
        violations: list[Violation] = []
        for func in _iter_php_functions(tree):
            violations.extend(self._php_violations_for_func(filepath, func))
        violations.extend(self._php_globals_writes(filepath, tree))
        return violations

    def _javascript_check(self, filepath: str, tree: tree_sitter.Tree, lang_name: str) -> list[Violation]:
        """Run the JS-family (JavaScript / TypeScript) check (assignment to ``globalThis.*`` / ``window.*`` / etc.).

        Validates that the resolved ``global_namespaces`` list is a list of strings
        before building the frozenset. A bare-string typo
        (``global_namespaces_javascript = "globalThis"``) would otherwise
        be silently coerced into a set of single characters and cause
        SAFE302 to stop matching any namespace - fail loud instead.

        TypeScript inherits the JS global namespaces by default;
        users can set ``global_namespaces_typescript`` for TS-only overrides.
        """
        raw, error_key = resolve_lang_config_lookup(
            self.config,
            "global_namespaces",
            lang_name,
            default=self._DEFAULT_GLOBAL_NAMESPACES_JAVASCRIPT,
        )
        namespaces = frozenset(_validated_string_list(raw, error_key))
        violations: list[Violation] = []
        for func in _iter_javascript_functions(tree):
            violations.extend(self._javascript_violations_for_func(filepath, func, namespaces))
        return violations


class WideScopeDeclarationRule(BaseRule):
    """Reject ``var`` declarations - prefer ``let`` / ``const`` for narrower scope.

    Holzmann's Power-of-Ten Rule 6 ("Declare variables at the smallest
    possible scope") is C-flavoured but maps cleanly to a real
    JavaScript hazard: ``var`` is *function-scoped* and hoists to the
    top of the enclosing function (or module), while ``let`` / ``const``
    are *block-scoped*. A ``var`` declared in one branch is visible
    in every other branch of the same function - a classic source
    of accidental cross-branch reads and TDZ-like bugs that block
    scoping eliminates.

    The fix is mechanical: replace ``var`` with ``let`` (when the
    binding is reassigned) or ``const`` (when it isn't). The rule
    fires once per ``variable_declaration`` node - a multi-binding
    form like ``var x = 1, y = 2;`` produces a single violation
    (the line is the unit of fix, not each name).

    JS-family only (JavaScript and TypeScript): Python has no ``var`` /
    ``let`` / ``const`` distinction, so Python users get nothing from
    this rule. ``var`` is still legal in TypeScript and carries the
    same function-scoped-and-hoisted hazard there, so the rule
    registers ``language = ("javascript", "typescript")`` and the
    engine's per-language dispatch correctly skips it on ``.py`` /
    ``.pyw`` files.
    """

    name = "wide_scope_declaration"
    code = "SAFE305"
    language = ("javascript", "typescript")

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
                    "`var` declaration uses function-scope hoisting - replace with `let` or `const` for block scope",
                )
            )
        return violations
