"""State & purity rules: global_state (SAFE301, Python-only), global_mutation (SAFE302), and wide_scope_declaration (SAFE305, JS-family - JavaScript and TypeScript)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
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
    (``x = 1`` and ``x: int = 1``) as the same ``assignment`` node type.
    The annotated form just adds ``:`` and ``type`` as inline children.
    ``child_by_field_name("left")`` correctly returns the identifier in
    both cases, so a single branch handles both.
    """
    if node.type in (ASSIGNMENT, AUGMENTED_ASSIGNMENT):
        left = node.child_by_field_name("left")
        return left if left is not None and left.type == IDENTIFIER else None
    return None


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
    language = ("python", "javascript", "typescript", "java", "go")

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
        if lang_name == "python":
            return self._python_check(filepath, tree)
        if lang_name == "java":
            return self._java_check(filepath, tree)
        if lang_name == "go":
            return self._go_check(filepath, tree)
        return self._javascript_check(filepath, tree, lang_name)

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
        ``var_spec`` nodes in a ``var_spec_list``. Walking the declaration
        finds the specs in both shapes; each spec can bind several names
        (``var a, b int``), so emit one violation per declared name.
        """
        out: list[Violation] = []
        for spec in walk(var_decl):
            if spec.type == "var_spec":
                out.extend(self._go_spec_violations(filepath, spec))
        return out

    def _go_spec_violations(self, filepath: str, spec: tree_sitter.Node) -> list[Violation]:
        """Return one violation per declared identifier in a ``var_spec``.

        Only the spec's direct ``identifier`` children are names; the type
        (``type_identifier``) and any initializer (nested in
        ``expression_list``) are not direct ``identifier`` children, so they
        are excluded without extra filtering.
        """
        return [
            self._make_violation_for_node(
                filepath,
                ident,
                f'Package-level var "{node_text(ident)}" is shared mutable state - scope it to its consumer, or use `const` if it never changes (Power of Ten rule 6)',
            )
            for ident in spec.named_children
            if ident.type == "identifier"
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
