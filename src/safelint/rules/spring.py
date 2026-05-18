"""Spring Boot framework-aware rules: SAFE901-904.

Four rules covering common Spring Boot misuses that vanilla Java static
analysis won't catch because the hazards live in *annotation usage*
rather than in language-level constructs. All four are Java-only
(``language = ("java",)``) and default-disabled under the vanilla Java
preset; the ``[tool.safelint.java] framework = "spring-boot"`` preset
flips ``enabled`` to ``True`` for the set.

* **SAFE901 ``spring_field_injection``** (warning): ``@Autowired`` on a
  field declaration. Spring's own reference docs recommend constructor
  injection (immutable, testable, fail-fast on missing deps).
* **SAFE902 ``spring_missing_transactional``** (error): service-layer
  method with multiple Spring Data write calls but no ``@Transactional``.
  Data-integrity bug class: partial writes leak when one step fails.
* **SAFE903 ``spring_unvalidated_input``** (error): controller method
  parameter annotated ``@RequestBody`` or ``@ModelAttribute`` without
  ``@Valid`` or ``@Validated``. Surfaces the validation gap structurally
  (complements SAFE801 ``tainted_sink`` which catches the same hazard
  via dataflow).
* **SAFE904 ``spring_async_checked_exception``** (warning): ``@Async``
  method declares a ``throws`` clause. Spring returns immediately and
  silently swallows the exception at runtime; the caller never sees it.

Detection is structural-only - no type inference. The shared
:func:`_iter_annotation_names` helper handles both ``@Foo`` (marker
annotation) and ``@Foo(args)`` (annotation with args) forms; both
parse as different node types in tree-sitter-java but resolve to the
same annotation name for the rule check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, node_text, resolve_lang_name, walk
from safelint.languages.java import FUNCTION_TYPES as _JAVA_FUNCTION_TYPES
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------


def _iter_annotation_names(modifiers_node: tree_sitter.Node | None) -> Iterator[str]:
    """Yield every annotation name on a ``modifiers`` node.

    tree-sitter-java emits two annotation shapes:

    * ``marker_annotation`` (``@Foo``) - the name lives directly as
      the first ``identifier`` named child.
    * ``annotation`` (``@Foo(arg=value)``) - the name lives as the
      first ``identifier`` child too; ``annotation_argument_list`` is
      a sibling.

    Both shapes return just the simple annotation name (``"Foo"``);
    fully-qualified ``@org.springframework.stereotype.Service``
    parses with a ``scoped_identifier`` child whose trailing
    identifier is what users actually grep for - we resolve that to
    the bareword too. Yields nothing when *modifiers_node* is None.
    """
    if modifiers_node is None:
        return
    for child in modifiers_node.named_children:
        if child.type not in ("marker_annotation", "annotation"):
            continue
        ident = _annotation_simple_name(child)
        if ident is not None:  # pragma: no cover - defensive: well-formed annotations always resolve to an identifier
            yield ident


def _last_identifier_descendant(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the last ``identifier`` descendant of *node*, or None.

    Used to extract the simple name from a ``scoped_identifier``
    (``a.b.Foo`` → the ``Foo`` identifier at the trailing position).
    """
    last_id = None
    for descendant in walk(node):
        if descendant.type == "identifier":
            last_id = descendant
    return last_id


def _annotation_simple_name(annotation_node: tree_sitter.Node) -> str | None:
    """Return the bareword annotation name from a ``@Foo`` / ``@Foo(args)`` node.

    Handles the fully-qualified form (``@org.springframework.stereotype.Service``)
    by returning the trailing identifier (``"Service"``) - matches how
    users actually write the annotation grep patterns.
    """
    # First named child is the annotation name; could be ``identifier``
    # (bare ``@Foo``) or ``scoped_identifier`` (qualified ``@a.b.Foo``).
    if not annotation_node.named_children:  # pragma: no cover - defensive: well-formed annotations always carry a name
        return None
    name_node = annotation_node.named_children[0]
    if name_node.type == "identifier":
        return node_text(name_node)
    if name_node.type != "scoped_identifier":  # pragma: no cover - only identifier / scoped_identifier shapes exist in tree-sitter-java
        return None
    last_id = _last_identifier_descendant(name_node)
    return node_text(last_id) if last_id is not None else None  # pragma: no cover - defensive: scoped_identifier always has trailing identifier


def _has_annotation(modifiers_node: tree_sitter.Node | None, name: str) -> bool:
    """Return True if *modifiers_node* contains an annotation named *name*."""
    return name in set(_iter_annotation_names(modifiers_node))


def _has_any_annotation(modifiers_node: tree_sitter.Node | None, names: frozenset[str]) -> bool:
    """Return True if *modifiers_node* contains any annotation whose name is in *names*."""
    return bool(set(_iter_annotation_names(modifiers_node)) & names)


def _modifiers_of(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the ``modifiers`` child of *node* if any, else None.

    Class / method / field / formal_parameter declarations all expose
    their modifier block as a ``modifiers`` named child (not on a
    field). When absent, the declaration has no annotations and no
    keyword modifiers (``public`` / ``static`` / etc.).
    """
    return next((c for c in node.named_children if c.type == "modifiers"), None)


def _enclosing_class(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Walk parent chain to the nearest enclosing ``class_declaration``, or None.

    Stops at the program root or the first class scope encountered.
    Skips through ``interface_declaration`` / ``enum_declaration`` /
    ``record_declaration`` since methods inside those don't carry the
    Spring stereotype this rule cares about (services / components are
    classes by Spring convention).
    """
    cur = node.parent
    while cur is not None:
        if cur.type == "class_declaration":
            return cur
        cur = cur.parent
    return None


# ---------------------------------------------------------------------------
# SAFE901 spring_field_injection
# ---------------------------------------------------------------------------


class SpringFieldInjectionRule(BaseRule):
    """Reject ``@Autowired`` on a field declaration; recommend constructor injection.

    Spring's own reference documentation has recommended constructor
    injection over field injection since 4.3. The rule fires on every
    ``@Autowired`` field, which is the simplest and most reliable
    detection pattern: walk every ``field_declaration``, check its
    ``modifiers``, and report if ``@Autowired`` is present.

    Constructor injection has three advantages the docs cite:

    * **Immutability** - the injected dependency can be ``final``,
      preventing later reassignment from breaking invariants.
    * **Testability** - tests can construct the class directly with
      mocks, no reflection / Spring context needed.
    * **Fail-fast on missing deps** - the constructor signature makes
      the dependency graph explicit; missing deps surface at
      instantiation time, not at first use.

    Java-only. Default-disabled under the vanilla preset; the
    ``spring-boot`` framework preset flips ``enabled`` to True.
    """

    name = "spring_field_injection"
    code = "SAFE901"
    language = ("java",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every ``@Autowired`` field declaration."""
        if resolve_lang_name(filepath) != "java":  # pragma: no cover - engine dispatch already filters by language tuple
            return []
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "field_declaration":
                continue
            if not _has_annotation(_modifiers_of(node), "Autowired"):
                continue
            field_name = _first_field_variable_name(node) or "<field>"
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'Field "{field_name}" uses @Autowired field injection - use constructor injection instead (immutable, testable, fail-fast on missing deps)',
                )
            )
        return violations


def _first_field_variable_name(field_node: tree_sitter.Node) -> str | None:
    """Return the first declared variable name on a ``field_declaration``.

    Returns ``None`` only on malformed AST that tree-sitter-java's
    grammar otherwise rejects: a ``field_declaration`` with no
    ``variable_declarator`` child, or one whose ``name`` field is
    absent / non-identifier. Callers (currently ``check_file`` in
    SAFE901) fall back to a ``"<field>"`` placeholder so the
    violation message stays informative.
    """
    decl = next((c for c in field_node.named_children if c.type == "variable_declarator"), None)
    if decl is None:  # pragma: no cover - defensive: valid Java field_declaration always has at least one variable_declarator
        return None
    name_node = decl.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":  # pragma: no cover - defensive: valid declarator always has an identifier name
        return None
    return node_text(name_node)


# ---------------------------------------------------------------------------
# SAFE902 spring_missing_transactional
# ---------------------------------------------------------------------------


# Spring Data CrudRepository / JpaRepository write-method names. ``call_name``
# strips the receiver, so ``userRepo.save(u)`` resolves to ``"save"``.
_SPRING_REPO_WRITE_METHODS: frozenset[str] = frozenset(
    {
        "save",
        "saveAll",
        "saveAndFlush",
        "delete",
        "deleteAll",
        "deleteById",
        "deleteAllById",
        "deleteAllInBatch",
        "deleteAllByIdInBatch",
        "update",  # Spring 6.1+ ListCrudRepository / custom updates
    }
)

# Receiver-name substrings that signal a repository-like object. The
# rule constrains write-method matching to receivers whose name contains
# one of these (case-insensitive). Without this guard, ``call_name``
# strips the receiver and every ``.save(...)`` / ``.delete(...)`` /
# ``.update(...)`` call in the method body matches - including
# unrelated calls like ``file.delete()``, ``cache.delete()``, or
# ``session.update()``. The heuristic accepts the conservative miss
# (a write on a repository named ``crud`` or ``store`` won't count)
# in exchange for eliminating the false-positive class.
#
# ``jdbctemplate`` (case-insensitive substring) catches
# ``jdbcTemplate.update(...)`` and ``namedParameterJdbcTemplate.update(...)``
# - the raw-SQL Spring write paths that don't share the CrudRepository
# naming convention. The bare substring ``template`` was deliberately
# REPLACED with ``jdbctemplate`` because ``template`` also matched
# ``restTemplate`` / ``kafkaTemplate`` / ``redisTemplate`` and other
# non-database Spring templates, making SAFE902 count their writes
# (``restTemplate.delete(...)`` etc.) toward the 2+ transactional-write
# threshold even though ``@Transactional`` cannot make a remote HTTP
# call or message-broker call atomic with a JDBC write.
_SPRING_REPO_RECEIVER_PATTERNS: tuple[str, ...] = ("repo", "dao", "jdbctemplate")

# Class-level annotations that mark a Spring-managed bean carrying
# transactional business logic. ``@Service`` is the canonical stereotype;
# ``@Component`` is broader; ``@Repository`` is also a stereotype but
# repository methods are usually transactional-per-method by Spring Data
# convention, so we focus on @Service / @Component.
_SPRING_SERVICE_ANNOTATIONS: frozenset[str] = frozenset({"Service", "Component"})


class SpringMissingTransactionalRule(BaseRule):
    """Flag service-layer methods doing multiple repository writes without ``@Transactional``.

    Heuristic, intentionally conservative to avoid false positives:

    1. Find every ``method_declaration`` whose enclosing class is
       annotated ``@Service`` or ``@Component``.
    2. Count direct ``method_invocation`` calls inside the body whose
       method name matches a Spring Data write verb
       (``save`` / ``saveAll`` / ``delete`` / ``deleteAll`` /
       ``deleteById`` / ``update`` / etc.).
    3. If the count is >= 2 AND neither the method nor the enclosing
       class carries ``@Transactional``, fire.

    The "count >= 2" gate prevents single-write methods from firing -
    a single ``save`` may not need a transaction (Spring Data wraps
    the single call automatically in most configurations). Two or
    more writes that aren't bracketed by ``@Transactional`` leak
    partial state on failure, which is the bug class this rule
    catches.

    Skipping the body walk into nested function-defining nodes
    (lambdas, anonymous classes) keeps the count scoped to the
    immediate method body - a write inside a callback / executor
    submit() is its own transactional context, not the enclosing
    method's.

    Java-only. Default-disabled under the vanilla preset; the
    ``spring-boot`` framework preset flips ``enabled`` to True.
    """

    name = "spring_missing_transactional"
    code = "SAFE902"
    language = ("java",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag service-layer methods with multiple writes but no @Transactional."""
        if resolve_lang_name(filepath) != "java":  # pragma: no cover - engine dispatch already filters by language tuple
            return []
        violations: list[Violation] = []
        for method in walk(tree.root_node):
            if method.type != "method_declaration":
                continue
            enclosing = _enclosing_class(method)
            if enclosing is None:
                continue
            if not _has_any_annotation(_modifiers_of(enclosing), _SPRING_SERVICE_ANNOTATIONS):
                continue
            # @Transactional on the method itself or on the enclosing
            # class both count as guarding all writes in this method.
            if _has_annotation(_modifiers_of(method), "Transactional"):
                continue
            if _has_annotation(_modifiers_of(enclosing), "Transactional"):
                continue
            write_count = _count_repository_writes(method)
            if write_count < 2:
                continue
            method_name = _method_name(method) or "<method>"
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    method,
                    f'Service method "{method_name}" performs {write_count} repository writes without @Transactional - add @Transactional to bracket the writes in one atomic transaction',
                )
            )
        return violations


def _is_repository_receiver(call_node: tree_sitter.Node) -> bool:
    """Return True if the method_invocation's receiver looks like a repository.

    Receiver must be either:

    * a simple ``identifier`` (``userRepo.save(...)``) whose name
      (lowercased) contains one of ``repo`` / ``dao`` / ``template``,
      OR
    * a ``field_access`` whose ``field`` is an identifier matching
      the same pattern (``this.userRepo.save(...)`` /
      ``self.repo.save(...)``). Service code in real Spring projects
      uses the ``this.`` qualifier extensively, so requiring a bare
      identifier would miss the common case.

    Other receiver shapes (parenthesised expressions, chained
    ``a.b.c.save()`` calls beyond one ``this.field`` level) are
    still rejected conservatively to avoid wrongly classifying
    unrelated objects.
    """
    obj = call_node.child_by_field_name("object")
    if obj is None:
        return False
    if obj.type == "identifier":
        return _name_matches_repo_pattern(node_text(obj))
    if obj.type == "field_access":
        field_node = obj.child_by_field_name("field")
        if field_node is None or field_node.type != "identifier":
            return False
        return _name_matches_repo_pattern(node_text(field_node))
    return False


def _name_matches_repo_pattern(name: str) -> bool:
    """Return True if *name* (case-insensitive) contains any repo-receiver pattern."""
    lowered = name.lower()
    return any(p in lowered for p in _SPRING_REPO_RECEIVER_PATTERNS)


def _count_repository_writes(method_node: tree_sitter.Node) -> int:
    """Count Spring Data write-method calls in the immediate method body.

    Skips into nested function-defining nodes so writes inside lambdas,
    anonymous classes, or inner methods don't count toward the
    enclosing method's total - those are separate transactional
    contexts (or no context at all when run on an executor).

    Also requires the receiver to look like a repository (see
    ``_is_repository_receiver``); without that guard, ``call_name``
    strips the receiver and unrelated calls like ``file.delete()``
    or ``cache.delete()`` would be counted as Spring Data writes.
    """
    count = 0
    for node in walk(method_node, skip_types=tuple(_JAVA_FUNCTION_TYPES)):
        if node is method_node:
            continue
        if node.type != "method_invocation":
            continue
        if call_name(node) not in _SPRING_REPO_WRITE_METHODS:
            continue
        if not _is_repository_receiver(node):
            continue
        count += 1
    return count


def _method_name(method_node: tree_sitter.Node) -> str | None:
    """Return the simple method name from a ``method_declaration``."""
    name_node = method_node.child_by_field_name("name")
    return node_text(name_node) if name_node is not None and name_node.type == "identifier" else None


# ---------------------------------------------------------------------------
# SAFE903 spring_unvalidated_input
# ---------------------------------------------------------------------------


# Controller-stereotype annotations. ``@RestController`` is the modern
# default; ``@Controller`` is the older form (still legal, often paired
# with view-rendering). Both expose methods that receive untrusted
# user input.
_SPRING_CONTROLLER_ANNOTATIONS: frozenset[str] = frozenset({"RestController", "Controller"})

# Request-binding annotations whose value comes from untrusted input
# AND can hold a complex object that benefits from bean validation.
# ``@RequestBody`` is the canonical case (JSON deserialised into a
# POJO). ``@ModelAttribute`` binds form data the same way. We
# deliberately DO NOT list ``@RequestParam`` or ``@PathVariable``:
# those typically bind to primitives (``Long id``, ``String name``)
# where bean validation is a softer requirement than for full
# request bodies.
_VALIDATABLE_BINDINGS: frozenset[str] = frozenset({"RequestBody", "ModelAttribute"})

# Annotations that mark a parameter as validated. ``@Valid`` is the
# JSR-380 standard; ``@Validated`` is Spring's group-aware extension.
# Either one suffices to clear the violation.
_VALIDATION_ANNOTATIONS: frozenset[str] = frozenset({"Valid", "Validated"})


class SpringUnvalidatedInputRule(BaseRule):
    """Flag controller method parameters that receive untrusted input without @Valid / @Validated.

    Detection is structural (annotation-presence check, no type or
    method-body inspection):

    1. Find every ``method_declaration`` whose enclosing class is
       annotated ``@RestController`` or ``@Controller``.
    2. For each ``formal_parameter`` in the method, check whether its
       annotations include ``@RequestBody`` or ``@ModelAttribute``.
    3. If yes AND the parameter does NOT also carry ``@Valid`` or
       ``@Validated``, fire on the parameter.

    Deliberately narrow: only ``@RequestBody`` / ``@ModelAttribute``,
    not ``@RequestParam`` / ``@PathVariable``. The latter two
    typically bind to primitives where bean validation has limited
    value; the former two bind to full deserialised objects where
    skipping validation is the canonical bug. Users who want
    ``@RequestParam`` validation enforced can suppress with
    ``// nosafe`` (Java's comment prefix) or extend via the
    rule's config (future knob).

    Complements SAFE801 ``tainted_sink``: SAFE801 catches user input
    flowing into a dangerous sink via dataflow; SAFE903 catches the
    structural absence of validation at the input boundary
    *regardless* of where the data later flows. Both fire on the same
    bug class from different angles; a Spring user benefits from
    enabling both.

    Java-only. Default-disabled under the vanilla preset; the
    ``spring-boot`` framework preset flips ``enabled`` to True.
    """

    name = "spring_unvalidated_input"
    code = "SAFE903"
    language = ("java",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unvalidated @RequestBody / @ModelAttribute parameters in controller methods."""
        if resolve_lang_name(filepath) != "java":  # pragma: no cover - engine dispatch already filters by language tuple
            return []
        violations: list[Violation] = []
        for method in walk(tree.root_node):
            if not _is_controller_method(method):
                continue
            violations.extend(self._check_method(filepath, method))
        return violations

    def _check_method(self, filepath: str, method: tree_sitter.Node) -> list[Violation]:
        """Per-method scan for unvalidated request-binding parameters."""
        params_node = method.child_by_field_name("parameters")
        if params_node is None:  # pragma: no cover - defensive: tree-sitter-java always emits a formal_parameters node for valid method_declaration
            return []
        method_name = _method_name(method) or "<method>"
        violations: list[Violation] = []
        for param in params_node.named_children:
            if param.type != "formal_parameter":  # pragma: no cover - defensive: receiver_parameter / spread_parameter rarely appear in controllers
                continue
            v = self._check_param(filepath, param, method_name)
            if v is not None:
                violations.append(v)
        return violations

    def _check_param(self, filepath: str, param: tree_sitter.Node, method_name: str) -> Violation | None:
        """Return a violation if *param* binds untrusted input without validation, else None."""
        modifiers = _modifiers_of(param)
        binding = _validatable_binding_on(modifiers)
        if binding is None:
            return None
        if _has_any_annotation(modifiers, _VALIDATION_ANNOTATIONS):
            return None
        param_name = _formal_param_name(param) or "<param>"
        return self._make_violation_for_node(
            filepath,
            param,
            f'Controller "{method_name}" parameter "{param_name}" uses @{binding} without @Valid or @Validated - bean validation must run on deserialised request bodies',
        )


def _is_async_method(method: tree_sitter.Node) -> bool:
    """Return True if *method* is annotated ``@Async`` directly or via its enclosing class.

    Spring honours ``@Async`` at both the method level and the class /
    type level. A class-level ``@Async class Job { void run() throws
    IOException { ... } }`` will execute every method asynchronously
    and silently swallow the checked exception just like a method-level
    annotation would, so the throws clause is misleading either way.
    """
    if _has_annotation(_modifiers_of(method), "Async"):
        return True
    enclosing = _enclosing_class(method)
    return enclosing is not None and _has_annotation(_modifiers_of(enclosing), "Async")


def _is_controller_method(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a ``method_declaration`` inside a Spring controller class."""
    if node.type != "method_declaration":
        return False
    enclosing = _enclosing_class(node)
    if enclosing is None:  # pragma: no cover - defensive: orphan methods at program root don't exist in valid Java
        return False
    return _has_any_annotation(_modifiers_of(enclosing), _SPRING_CONTROLLER_ANNOTATIONS)


def _validatable_binding_on(modifiers_node: tree_sitter.Node | None) -> str | None:
    """Return the matched binding annotation name (``RequestBody`` / ``ModelAttribute``) or None."""
    for name in _iter_annotation_names(modifiers_node):
        if name in _VALIDATABLE_BINDINGS:
            return name
    return None


def _formal_param_name(param_node: tree_sitter.Node) -> str | None:
    """Return the bound variable name from a ``formal_parameter`` node."""
    name_node = param_node.child_by_field_name("name")
    return node_text(name_node) if name_node is not None and name_node.type == "identifier" else None


# ---------------------------------------------------------------------------
# SAFE904 spring_async_checked_exception
# ---------------------------------------------------------------------------


class SpringAsyncCheckedExceptionRule(BaseRule):
    """Flag @Async methods that declare a throws clause.

    Detection is structural:

    1. Find every ``method_declaration`` annotated ``@Async``.
    2. If the method has a ``throws`` clause with any type listed,
       fire.

    The rule fires on **any** throws (checked or unchecked) for
    simplicity. The reason: Spring's ``@Async`` schedules the method
    to run on a separate thread and returns immediately to the caller
    (either ``void`` or a ``Future`` / ``CompletableFuture``). If the
    method throws, the exception is propagated through the executor's
    uncaught-exception handler (defaulting to log-and-continue) -
    the caller never sees it, regardless of the declared throws
    clause. Declaring throws on an ``@Async`` method is therefore
    always misleading: it implies the caller can handle the
    exception, when in fact they cannot.

    The fix is to wrap potentially-throwing code in a try/catch
    inside the method body and either swallow with logging or
    convert to a ``CompletableFuture.failedFuture(...)`` if the
    method returns a Future.

    Detecting checked-vs-unchecked would require type inference we
    don't do today; we err on the noisier side because the rule fires
    on legitimate ``@Async`` patterns rarely (most are ``void`` with
    no throws), and the surface that DOES fire is usually the bug
    pattern this rule targets.

    Java-only. Default-disabled under the vanilla preset; the
    ``spring-boot`` framework preset flips ``enabled`` to True.
    """

    name = "spring_async_checked_exception"
    code = "SAFE904"
    language = ("java",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every @Async method that declares a throws clause."""
        if resolve_lang_name(filepath) != "java":  # pragma: no cover - engine dispatch already filters by language tuple
            return []
        violations: list[Violation] = []
        for method in walk(tree.root_node):
            if method.type != "method_declaration":
                continue
            if not _is_async_method(method):
                continue
            throws_node = next((c for c in method.named_children if c.type == "throws"), None)
            if throws_node is None:
                continue
            throws_types = _throws_type_names(throws_node)
            if not throws_types:  # pragma: no cover - defensive: throws clause always carries at least one type in valid Java
                continue
            method_name = _method_name(method) or "<method>"
            throws_listing = ", ".join(throws_types)
            message = (
                f'@Async method "{method_name}" declares "throws {throws_listing}" - '
                "Spring runs @Async methods on a separate thread and swallows exceptions; "
                "the caller never sees them. Catch inside the body or return "
                "CompletableFuture.failedFuture(...)"
            )
            violations.append(self._make_violation_for_node(filepath, throws_node, message))
        return violations


def _throws_type_simple_name(child: tree_sitter.Node) -> str | None:
    """Return the simple class name from a ``throws``-clause child node, or None.

    Handles both ``type_identifier`` (bare ``IOException``) and
    ``scoped_type_identifier`` (qualified ``java.io.IOException``);
    returns the trailing simple name in the qualified case.
    """
    if child.type == "type_identifier":
        return node_text(child)
    if child.type != "scoped_type_identifier":  # pragma: no cover - throws types are always type_identifier or scoped_type_identifier
        return None
    # Walk for the last ``type_identifier`` descendant - the simple name
    # at the end of the qualified chain.
    last_id = None
    for descendant in walk(child):
        if descendant.type == "type_identifier":
            last_id = descendant
    return node_text(last_id) if last_id else None


def _throws_type_names(throws_node: tree_sitter.Node) -> list[str]:
    """Return the declared exception type names from a ``throws`` clause.

    A ``throws X, Y`` clause has ``type_identifier`` named children (or
    ``scoped_type_identifier`` for fully-qualified forms). Returns the
    simple name (last identifier component) so output reads naturally.
    """
    names: list[str] = []
    for child in throws_node.named_children:
        name = _throws_type_simple_name(child)
        if name is not None:
            names.append(name)
    return names
