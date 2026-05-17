"""Tests for the four Spring Boot framework-aware rules (SAFE901-904).

Each rule has a positive case (fires when it should) and a negative
case (does NOT fire when properly configured), exercised via a
hand-crafted Java source string parsed through ``JAVA.create_parser()``.
The rules are Java-only and default-disabled; ``[tool.safelint.java]
framework = "spring-boot"`` flips ``enabled`` for the set, but for
direct rule invocation the tests construct the rule with
``enabled=True`` explicitly.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from safelint.languages.java import JAVA
from safelint.rules.spring import (
    SpringAsyncCheckedExceptionRule,
    SpringFieldInjectionRule,
    SpringMissingTransactionalRule,
    SpringUnvalidatedInputRule,
)


if TYPE_CHECKING:
    import tree_sitter


def _parse(src: str) -> tree_sitter.Tree:
    """Parse *src* as Java and return the tree."""
    return JAVA.create_parser().parse(textwrap.dedent(src).encode("utf-8"))


# ---------------------------------------------------------------------------
# SAFE901 spring_field_injection
# ---------------------------------------------------------------------------


def test_safe901_fires_on_autowired_field() -> None:
    """``@Autowired private Foo foo;`` should produce one SAFE901 violation."""
    tree = _parse(
        """
        class UserService {
            @Autowired
            private UserRepository userRepo;
        }
        """
    )
    rule = SpringFieldInjectionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("UserService.java", tree)
    assert len(violations) == 1
    assert violations[0].code == "SAFE901"
    assert "userRepo" in violations[0].message


def test_safe901_does_not_fire_on_constructor_injection() -> None:
    """A field assigned via constructor (no ``@Autowired``) is the recommended pattern."""
    tree = _parse(
        """
        class UserService {
            private final UserRepository userRepo;
            public UserService(UserRepository userRepo) {
                this.userRepo = userRepo;
            }
        }
        """
    )
    rule = SpringFieldInjectionRule({"enabled": True, "severity": "warning"})
    assert rule.check_file("UserService.java", tree) == []


def test_safe901_skips_non_java_files() -> None:
    """The rule is Java-only; calling it on a ``.py`` filepath returns no violations."""
    tree = _parse("class Foo { @Autowired private Bar b; }")
    rule = SpringFieldInjectionRule({"enabled": True, "severity": "warning"})
    assert rule.check_file("Foo.py", tree) == []


# ---------------------------------------------------------------------------
# SAFE902 spring_missing_transactional
# ---------------------------------------------------------------------------


def test_safe902_fires_on_two_writes_without_transactional() -> None:
    """A @Service method doing 2+ repository writes without @Transactional fires."""
    tree = _parse(
        """
        @Service
        class UserService {
            private UserRepository userRepo;
            private AuditRepository auditRepo;
            public void register(User u, Audit a) {
                userRepo.save(u);
                auditRepo.save(a);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    violations = rule.check_file("UserService.java", tree)
    assert len(violations) == 1
    assert "register" in violations[0].message
    assert "2 repository writes" in violations[0].message


def test_safe902_does_not_fire_with_transactional_on_method() -> None:
    """Method-level @Transactional clears the violation."""
    tree = _parse(
        """
        @Service
        class UserService {
            private UserRepository userRepo;
            private AuditRepository auditRepo;
            @Transactional
            public void register(User u, Audit a) {
                userRepo.save(u);
                auditRepo.save(a);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserService.java", tree) == []


def test_safe902_does_not_fire_with_transactional_on_class() -> None:
    """Class-level @Transactional covers every method - no per-method annotation needed."""
    tree = _parse(
        """
        @Service
        @Transactional
        class UserService {
            private UserRepository userRepo;
            private AuditRepository auditRepo;
            public void register(User u, Audit a) {
                userRepo.save(u);
                auditRepo.save(a);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserService.java", tree) == []


def test_safe902_does_not_fire_on_single_write() -> None:
    """A single ``save`` may be safe without @Transactional - rule fires only on >= 2 writes."""
    tree = _parse(
        """
        @Service
        class UserService {
            private UserRepository userRepo;
            public void register(User u) {
                userRepo.save(u);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserService.java", tree) == []


def test_safe902_does_not_fire_outside_service_class() -> None:
    """A plain class (no @Service / @Component) is not service-layer - rule skips it."""
    tree = _parse(
        """
        class PlainHelper {
            private UserRepository userRepo;
            private AuditRepository auditRepo;
            public void register(User u, Audit a) {
                userRepo.save(u);
                auditRepo.save(a);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("PlainHelper.java", tree) == []


# ---------------------------------------------------------------------------
# SAFE903 spring_unvalidated_input
# ---------------------------------------------------------------------------


def test_safe903_fires_on_requestbody_without_valid() -> None:
    """@RequestBody without @Valid in a controller method fires."""
    tree = _parse(
        """
        @RestController
        class UserController {
            public User create(@RequestBody UserDto dto) {
                return null;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    violations = rule.check_file("UserController.java", tree)
    assert len(violations) == 1
    assert "create" in violations[0].message
    assert "dto" in violations[0].message
    assert "@RequestBody" in violations[0].message


def test_safe903_does_not_fire_with_valid_annotation() -> None:
    """@RequestBody @Valid clears the violation."""
    tree = _parse(
        """
        @RestController
        class UserController {
            public User create(@RequestBody @Valid UserDto dto) {
                return null;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserController.java", tree) == []


def test_safe903_does_not_fire_with_validated_annotation() -> None:
    """Spring's @Validated also satisfies the rule (alternative to JSR @Valid)."""
    tree = _parse(
        """
        @RestController
        class UserController {
            public User create(@RequestBody @Validated UserDto dto) {
                return null;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserController.java", tree) == []


def test_safe903_does_not_fire_on_pathvariable() -> None:
    """``@PathVariable`` is deliberately NOT covered - typically binds to primitives."""
    tree = _parse(
        """
        @RestController
        class UserController {
            public User getOne(@PathVariable Long id) {
                return null;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserController.java", tree) == []


def test_safe903_does_not_fire_outside_controller() -> None:
    """A plain class (no @RestController / @Controller) is not request-handling - rule skips."""
    tree = _parse(
        """
        class Helper {
            public User create(@RequestBody UserDto dto) {
                return null;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("Helper.java", tree) == []


# ---------------------------------------------------------------------------
# SAFE904 spring_async_checked_exception
# ---------------------------------------------------------------------------


def test_safe904_fires_on_async_with_throws() -> None:
    """@Async method declaring throws fires - Spring swallows the exception silently."""
    tree = _parse(
        """
        class JobRunner {
            @Async
            public void runJob() throws InterruptedException {
                Thread.sleep(1000);
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("JobRunner.java", tree)
    assert len(violations) == 1
    assert "runJob" in violations[0].message
    assert "InterruptedException" in violations[0].message


def test_safe904_does_not_fire_without_throws() -> None:
    """@Async without a throws clause is the safe pattern (catch internally)."""
    tree = _parse(
        """
        class JobRunner {
            @Async
            public void runJob() {
                try { Thread.sleep(1000); } catch (InterruptedException e) { }
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    assert rule.check_file("JobRunner.java", tree) == []


def test_safe904_fires_on_class_level_async() -> None:
    """``@Async class Job { void run() throws IOException }`` fires.

    Spring honours ``@Async`` at the class / type level too - every
    method in the class runs asynchronously. The rule must walk to
    the enclosing class's annotations, not only the method's
    immediate modifiers, otherwise this whole pattern is silently
    missed even though Spring will swallow the checked exception
    just like a method-level annotation would.
    """
    tree = _parse(
        """
        @Async
        class Job {
            public void run() throws java.io.IOException {
                doWork();
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("Job.java", tree)
    assert len(violations) == 1, "class-level @Async should propagate to every method"
    assert "run" in violations[0].message
    assert "IOException" in violations[0].message


def test_safe904_does_not_fire_without_async() -> None:
    """A method with throws but no @Async is fine - the caller will see the exception."""
    tree = _parse(
        """
        class JobRunner {
            public void runJob() throws InterruptedException {
                Thread.sleep(1000);
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    assert rule.check_file("JobRunner.java", tree) == []


# ---------------------------------------------------------------------------
# Multi-throws and scoped-annotation edge cases
# ---------------------------------------------------------------------------


def test_safe904_lists_all_thrown_types() -> None:
    """Multiple types in throws are all surfaced in the message."""
    tree = _parse(
        """
        class JobRunner {
            @Async
            public void runJob() throws InterruptedException, java.io.IOException {
                Thread.sleep(1000);
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("JobRunner.java", tree)
    assert len(violations) == 1
    assert "InterruptedException" in violations[0].message
    assert "IOException" in violations[0].message


def test_safe901_fires_on_fully_qualified_autowired() -> None:
    """``@org.springframework.beans.factory.annotation.Autowired`` is also recognised."""
    tree = _parse(
        """
        class UserService {
            @org.springframework.beans.factory.annotation.Autowired
            private UserRepository userRepo;
        }
        """
    )
    rule = SpringFieldInjectionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("UserService.java", tree)
    assert len(violations) == 1


@pytest.mark.parametrize(
    "stereotype",
    ("Service", "Component"),
)
def test_safe902_recognises_both_service_stereotypes(stereotype: str) -> None:
    """Both ``@Service`` and ``@Component`` mark a class as service-layer."""
    tree = _parse(
        f"""
        @{stereotype}
        class UserService {{
            private UserRepository userRepo;
            private AuditRepository auditRepo;
            public void register(User u, Audit a) {{
                userRepo.save(u);
                auditRepo.save(a);
            }}
        }}
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert len(rule.check_file("UserService.java", tree)) == 1


@pytest.mark.parametrize(
    "stereotype",
    ("RestController", "Controller"),
)
def test_safe903_recognises_both_controller_stereotypes(stereotype: str) -> None:
    """Both ``@RestController`` and ``@Controller`` mark a class as request-handling."""
    tree = _parse(
        f"""
        @{stereotype}
        class UserController {{
            public User create(@RequestBody UserDto dto) {{
                return null;
            }}
        }}
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert len(rule.check_file("UserController.java", tree)) == 1


# ---------------------------------------------------------------------------
# Edge cases for shared helpers + Java grammar shapes
# ---------------------------------------------------------------------------


def test_safe901_message_includes_field_name() -> None:
    """The SAFE901 message identifies which @Autowired field the violation refers to.

    Happy-path coverage of ``_first_field_variable_name`` for a normal
    ``field_declaration`` with one named ``variable_declarator``. The
    ``or "<field>"`` fallback in ``check_file`` is genuinely defensive
    (tree-sitter-java's grammar guarantees at least one declarator on a
    valid ``field_declaration``); reaching it would require malformed
    AST that the grammar otherwise rejects, so the branch is annotated
    for coverage in ``rules/spring.py`` rather than exercised here.
    """
    tree = _parse(
        """
        class Service {
            @Autowired
            private UserRepository userRepo;
        }
        """
    )
    rule = SpringFieldInjectionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("Service.java", tree)
    assert len(violations) == 1
    assert "userRepo" in violations[0].message


def test_safe902_does_not_fire_on_non_repository_receivers() -> None:
    """``file.delete()`` and ``cache.delete()`` are NOT Spring Data writes.

    Reviewer's example: a @Service method calling unrelated ``delete``
    methods on file / cache objects must not be counted as repository
    writes. The receiver-name heuristic rejects identifiers that don't
    contain ``repo`` / ``dao`` / ``template``.
    """
    tree = _parse(
        """
        @Service
        class FileCleanupService {
            private FileHandle file;
            private CacheManager cache;
            public void purge() {
                file.delete();
                cache.delete();
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("FileCleanupService.java", tree) == [], "Non-repository receivers (file / cache) must not be counted as Spring Data writes"


def test_safe902_does_not_fire_on_mixed_repo_and_non_repo_receivers() -> None:
    """Only the repo-receiver write counts; the non-repo one is ignored.

    Confirms the heuristic is applied per-call rather than aggregated:
    one ``userRepo.save()`` + one ``file.delete()`` = 1 counted write,
    below the 2+ threshold, no violation.
    """
    tree = _parse(
        """
        @Service
        class MixedService {
            private UserRepository userRepo;
            private FileHandle file;
            public void doStuff(User u) {
                userRepo.save(u);
                file.delete();
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    assert rule.check_file("MixedService.java", tree) == []


def test_safe902_fires_on_jdbctemplate_writes() -> None:
    """``jdbcTemplate.update(...)`` matches via the ``template`` receiver pattern.

    JdbcTemplate is the raw-SQL Spring write path that doesn't follow
    the CrudRepository naming convention but is still genuinely
    transactional. Two updates without @Transactional should fire.
    """
    tree = _parse(
        """
        @Service
        class LegacyService {
            private JdbcTemplate jdbcTemplate;
            public void migrate() {
                jdbcTemplate.update("INSERT INTO audit ...");
                jdbcTemplate.update("UPDATE user SET ...");
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    violations = rule.check_file("LegacyService.java", tree)
    assert len(violations) == 1
    assert "2 repository writes" in violations[0].message


def test_safe902_skips_method_outside_class() -> None:
    """``_enclosing_class`` returns None for orphan methods → rule skips.

    Defensive - real Java files always nest methods in classes /
    interfaces / enums / records, but the helper walks the parent
    chain explicitly. This test would only fire if a method
    somehow lived at the program root (currently impossible with
    valid Java source).
    """
    tree = _parse(
        """
        interface UserRepo {
            User save(User u);
        }
        class Service {
            private UserRepo repo;
            // Method inside an interface body would be enclosed by
            // interface_declaration, not class_declaration - the
            // rule's _enclosing_class helper deliberately skips
            // through interface_declaration / enum_declaration /
            // record_declaration so methods there don't fire.
            public void noTransactional() {
                repo.save(null);
            }
        }
        """
    )
    rule = SpringMissingTransactionalRule({"enabled": True, "severity": "error"})
    # The interface-method is enclosed by an interface_declaration
    # (which _enclosing_class skips), so it doesn't trip the rule.
    # The class-method has only one save() call which is below the
    # 2+ write threshold. Net: zero violations.
    assert rule.check_file("Service.java", tree) == []


def test_safe903_skips_method_with_empty_parameters() -> None:
    """A controller method with zero formal parameters yields no SAFE903 hits.

    tree-sitter-java always emits a ``formal_parameters`` node for
    every ``method_declaration`` (the parens themselves), even when
    the parameter list is empty - so this test exercises the "loop
    body never executes because params_node.named_children is empty"
    path, NOT the defensive ``params_node is None`` branch (that
    branch fires only on malformed AST that the grammar otherwise
    rejects and is annotated for coverage purposes separately).

    The negative-control assertion stands either way: zero formal
    parameters means zero @RequestBody parameters to validate.
    """
    tree = _parse(
        """
        @RestController
        class UserController {
            @GetMapping("/")
            public String list() {
                return "all";
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserController.java", tree) == []


def test_safe903_skips_param_with_no_validatable_binding() -> None:
    """A formal_parameter whose annotation isn't @RequestBody / @ModelAttribute doesn't fire."""
    tree = _parse(
        """
        @RestController
        class UserController {
            @GetMapping("/")
            public String list(@CookieValue("session") String session) {
                return session;
            }
        }
        """
    )
    rule = SpringUnvalidatedInputRule({"enabled": True, "severity": "error"})
    assert rule.check_file("UserController.java", tree) == []


def test_safe904_handles_throws_with_scoped_type() -> None:
    """Fully-qualified throws (``throws java.io.IOException``) is surfaced as the simple name."""
    tree = _parse(
        """
        class Job {
            @Async
            public void run() throws java.io.IOException {
                /* body */
            }
        }
        """
    )
    rule = SpringAsyncCheckedExceptionRule({"enabled": True, "severity": "warning"})
    violations = rule.check_file("Job.java", tree)
    assert len(violations) == 1
    assert "IOException" in violations[0].message
