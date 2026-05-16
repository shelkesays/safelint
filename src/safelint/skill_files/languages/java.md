# safelint skill: Java addendum

Language-specific notes for the Java target. Mirrors `src/safelint/languages/java.py` in the safelint source tree. The skill core (`claude/SKILL.md` for Claude Code, each peer client's own file for other agents) handles the universal flow; this file holds Java-specific detail, including the Spring Boot framework preset.

## Install nuance

safelint is a Python package, not a Maven / Gradle artefact. v2.1.0+ ships the Java grammar in the `[java]` extra:

```bash
pip install 'safelint[java]'
# or, in a project that already uses uv:
uv add --dev 'safelint[java]'
# or, kitchen-sink:
pip install 'safelint[all]'
```

After install, `safelint` is on `PATH`. Run it from the Java project's root the same way as for a Python project, it auto-detects the language by file extension. Maven / Gradle plugins are NOT required; safelint is a standalone CLI that reads source files directly.

If you run plain `pip install safelint` (no extra) by mistake, the first run emits `safelint: warning: skipping .java files, install with: pip install 'safelint[java]'` and exits with code 2. Re-install with the extra and retry.

For pre-commit integration, the published hook routes `.java` files via the `java` filetype tag in `types_or` (pre-commit's `identify` library recognises it):

```yaml
- repo: https://github.com/shelkesays/safelint
  rev: v2.1.0  # pin to a release (use the latest GA tag)
  hooks:
    - id: safelint
      additional_dependencies: ['safelint[java]']
      # For a polyglot repo with Python + Java:
      # additional_dependencies: ['safelint[python,java]']
```

## File extensions

safelint lints `.java` files. The skill doesn't need to filter by extension, `safelint check` walks the project and picks up the registered extensions automatically. Kotlin (`.kt`) and Groovy (`.groovy`) are NOT yet registered; they would land as separate language modules with their own extras when added.

## Framework presets

Java source is Java source - the parser, AST, and rule logic are framework-agnostic. But the *defaults* baked into the rules (taint sinks, nullable methods, etc.) shift depending on which framework the project uses. `[tool.safelint.java] framework = "<name>"` selects the preset:

| Framework | When to pick it | What changes |
|---|---|---|
| `vanilla` (default) | Plain Java applications, Jakarta EE services, Android, libraries with no Spring dependency | Stdlib-only defaults: ``Runtime.exec`` / ``forName`` / ``executeQuery`` etc. for SAFE801 sinks; ``Map.get`` / ``getParameter`` / etc. for SAFE803 nullable methods. SAFE9xx Spring-specific rules are disabled. |
| `spring-boot` | Spring Boot 2.x / 3.x applications, including Spring MVC, Spring Data JPA, Spring JDBC, Spring WebFlux | Adds ``JdbcTemplate.query`` / ``queryForObject`` / ``update`` and ``RestTemplate.exchange`` / ``getForObject`` / etc. to SAFE801 sinks (SSRF surface). Adds ``queryForObject`` to SAFE803 nullable methods (returns null on zero rows). Enables the four SAFE901-904 Spring-specific rules. |

Configure via TOML:

```toml
# safelint.toml (standalone) - no [tool.safelint] wrapper
[java]
framework = "spring-boot"

# or, in pyproject.toml:
[tool.safelint.java]
framework = "spring-boot"
```

Explicit per-rule TOML config still wins over the preset; e.g., setting `[tool.safelint.rules.tainted_sink] sinks_java = [...]` overrides whatever the preset planted. The default framework is `vanilla` so existing v2.1.0+ users with no Java config see no surprise behaviour.

## Language-specific rule phrasing

When the user asks "why is this flagged?", the universal rationale in the per-client core is correct, but Java phrasing helps. The table lists every rule that applies to Java; rules deliberately skipped (with rationale) are listed in the next section.

| Code | Rule | Java-specific notes |
|---|---|---|
| SAFE101 | function_length | Counts source lines on `method_declaration` / `constructor_declaration` / `lambda_expression` / `static_initializer` (the four function-shaped nodes in Java). Default cap is 60 source lines. Lambda bodies count toward their own size, not the enclosing method's. |
| SAFE102 | nesting_depth | Counts `if` / `for` / `enhanced_for` (for-each) / `while` / `do` / `try` / `try_with_resources` / `switch_expression` (Java 14+ unified switch). `synchronized` blocks are NOT counted (visual indentation but not a control-flow branch). Default max is 2. |
| SAFE103 | max_arguments | Counts `formal_parameter` and `spread_parameter` (varargs `T... args`) children. The `receiver_parameter` form (`Foo this`) is excluded (it's the explicit form of the implicit `this`, analogous to Python's `self`). Default cap is 7. |
| SAFE104 | complexity | Cyclomatic complexity: every `if` / `for` / `enhanced_for` / `while` / `do` / `catch` / `ternary` adds one. Both Java switch shapes count their cases: colon-form (`switch_block_statement_group`) and arrow-form (`switch_rule`, Java 14+). `&&` / `\|\|` short-circuit operators inside `binary_expression` add one each (no `??`; Java uses `Objects.requireNonNullElse` / `Optional` for null-coalescing). Default cap is 10. |
| SAFE202 | empty_except | Fires on `catch (Exception e) {}` and on catch bodies containing only a single literal expression (`{ 0; }`, `{ "TODO"; }`, `{ null; }`) or a single comment (`{ // todo }`, `{ /* nope */ }`). tree-sitter-java emits comments as named children of blocks (unlike JS where they're extras), so a Java catch body containing only a `// todo` correctly registers as empty. |
| SAFE203 | logging_on_error | Requires a logging call in every catch block that doesn't re-raise. Recognised logger method names cover SLF4J / Log4j / java.util.logging: `error` / `warn` / `info` / `debug` / `trace` / `severe` / `fine` / `finer` / `finest` / `log` / `exception`. `call_name` strips the receiver, so `logger.error(...)` and `LoggerFactory.getLogger(Foo.class).error(...)` both resolve to `"error"`. Re-raise detection: `catch (Type e) { throw e; }` is recognised when the thrown identifier exactly matches the catch-parameter binding (`_caught_binding_name` walks the `catch_formal_parameter`'s `name` field). |
| SAFE302 | global_mutation | **NOT ported to Java in v2.1.0rc1.** Python's `global` keyword and JS's `globalThis.x = ...` patterns have no clean Java analogue. The natural Java equivalent (writes to non-final static fields from outside the declaring class's own static initialiser) needs class-scope analysis the rule doesn't currently do. Deferred to a future release. |
| SAFE303 | side_effects_hidden | Fires when a method with a "pure" name prefix (`get` / `compute` / `is` / `has` / `validate` / `parse` / etc.) calls an I/O primitive. Java default `io_functions_java` set covers `PrintStream` (`println` / `print` / `printf`), `Scanner` / `BufferedReader` stdin readers, file IO via `new` (`FileInputStream` / `FileOutputStream` / `FileReader` / `FileWriter` / `Scanner` / `PrintWriter`), `java.nio.file.Files` static methods (`readAllBytes` / `readAllLines` / `writeString` / `write`), and network (`Socket` / `HttpClient`). |
| SAFE304 | side_effects | Same I/O primitive set as SAFE303 but fires on any method whose name doesn't *signal* I/O (no `log` / `write` / `read` / `save` / `load` / `send` / `fetch` keyword). Note: under the `spring-boot` preset, `@Bean` factory methods that legitimately create side-effectful resources (DB connections, HTTP clients) are NOT exempted by the preset alone - suppress with `# nosafe: SAFE304` on each factory method until a future `skip_functions_annotated_with` config knob lands. |
| SAFE401 | resource_lifecycle | Tracks file streams, sockets, JDBC connections that need cleanup. Java's idiom is try-with-resources (`try (Resource r = ...) { ... }`) which auto-closes any `AutoCloseable`; the classic `try { ... } finally { r.close(); }` form is accepted too. Default tracked acquirers: `FileInputStream` / `FileOutputStream` / `FileReader` / `FileWriter` / `BufferedReader` / `BufferedWriter` / `Scanner` / `PrintWriter` / `RandomAccessFile` (via `new`), `Files.newBufferedReader` / `newBufferedWriter` / `newInputStream` / `newOutputStream` (static factory), `Socket` / `ServerSocket`, JDBC `getConnection`, `FileChannel.open`. |
| SAFE501 | unbounded_loops | Fires on `while (true)` without a `break`. Java has labelled-break (`outer: while (true) { for (...) { break outer; } }`) - the rule detects this via `labeled_statement` parent traversal and recognises `identifier` (NOT JS's `statement_identifier`) as the label-token type. `enhanced_for_statement` (for-each) and `switch_expression` are break-scope boundaries so a `break` inside a Java foreach or arrow-switch doesn't count toward an enclosing `while`. |
| SAFE601 | missing_assertions | Hybrid: counts both the built-in `assert` keyword (parsed as `assert_statement`, Java 1.4+) AND JUnit / AssertJ / Hamcrest method-call assertions. Default `assertion_calls_java` set covers JUnit 5 `Assertions.*` (assertEquals / assertTrue / assertThrows / assertAll / assertTimeout / assertInstanceOf / etc.), AssertJ / Hamcrest `assertThat`, and `fail`. `call_name` strips the receiver - `Assertions.assertEquals` and `assertEquals` both resolve to `"assertEquals"`. |
| SAFE701 | test_existence | Looks for `<ClassName>Test.java` (JUnit unit-test default), `<ClassName>Tests.java` (Spring's preferred form), `<ClassName>IT.java` (Maven Surefire / Failsafe integration tests), and `Test<ClassName>.java` (legacy prefix form). Default `test_dirs` is `["tests"]`; Maven / Gradle projects should override to `["src/test/java"]` (or both). |
| SAFE702 | test_coupling | Same candidate filenames as SAFE701; fires when a source file changes in the commit but no paired test does. |
| SAFE801 | tainted_sink | Vanilla sinks: `Runtime.exec` / `ProcessBuilder` / `forName` / `invoke` / `eval` (JSR-223) / `executeQuery` / `execute` / `executeUpdate` / `openConnection` / `openStream`. Vanilla sources: `getenv` / `getProperty` / `readLine` / `nextLine` / Servlet API `getParameter` / `getHeader` / `getQueryString` / `getCookies` / `getPathInfo` / `getRemoteUser`. Vanilla sanitizers: Apache Commons Text (`escapeHtml*` / `escapeXml` / `escapeJava` / `escapeJson`), URL encoding (`encode` / `encodeURIComponent`), generic (`sanitize` / `validate` / `quote`), Spring (`htmlEscape`), OWASP Java Encoder (`forHtml` / `forJavaScript` / `forCssString` / `forUri` / `forXml`). Method parameters are seeded as tainted on function entry (every `formal_parameter` / `spread_parameter` name); `receiver_parameter` (`Foo this`) is excluded. The `spring-boot` preset extends sinks with `JdbcTemplate.query` / `queryForObject` / `queryForList` / `queryForMap` / `update` / `batchUpdate` and `RestTemplate.exchange` / `getForObject` / `getForEntity` / `postForObject` / `postForEntity` / `put` / `delete` for SSRF. |
| SAFE802 | return_value_ignored | Fires on bare expression statements whose call discards a meaningful return. Vanilla `flagged_calls_java`: `java.io.File` boolean-returning mutators (`delete` / `mkdir` / `mkdirs` / `renameTo` / `setLastModified` / `setReadOnly` / `setWritable` / `setReadable` / `setExecutable` / `createNewFile`), `String` / `BigDecimal` / `BigInteger` immutables (`trim` / `strip` / `toUpperCase` / `toLowerCase` / `replace` / `replaceAll` / `substring` / `add` / `subtract` / etc. - immutable types where calling a mutator without using the result is always a bug), and `Future.cancel`. |
| SAFE803 | null_dereference | Fires on chained access (`field_access` / `array_access` / `method_invocation` with chained receiver) where the receiver is a nullable-returning call. Vanilla `nullable_methods_java`: `Map` / `Properties` (`get` / `getOrDefault` / `remove` / `put` / `putIfAbsent`), Servlet-request (`getParameter` / `getHeader` / `getCookie` / `getAttribute` / `getSession`), `getProperty` (System), reflection (`getAnnotation` / `getDeclaredAnnotation` / `getEnclosingClass` / `getEnclosingMethod`). Pass-through wrappers `parenthesized_expression` and `cast_expression` (`((Foo) map.get(k)).bar`) are peeled so the rule sees through them. Java has NO optional-chaining operator (`?.` doesn't exist) - the only safe guards are `if (result != null)` or `Optional.ofNullable(...)`. The `spring-boot` preset adds `queryForObject` (returns null on zero rows; the newer `JdbcClient.findOne` returns `Optional` and is deliberately NOT listed). |
| SAFE901 | spring_field_injection | *Java + Spring Boot only, enabled by `framework = "spring-boot"`.* Fires on `@Autowired` on a field. Spring's reference docs recommend constructor injection (immutable, testable, fail-fast on missing deps). Both bare `@Autowired` and fully-qualified `@org.springframework.beans.factory.annotation.Autowired` are recognised. |
| SAFE902 | spring_missing_transactional | *Java + Spring Boot only.* Fires when a `@Service` or `@Component` method does 2+ Spring Data repository writes (`save` / `saveAll` / `saveAndFlush` / `delete` / `deleteAll` / `deleteById` / `update` etc.) without `@Transactional` (on the method or the class). Single-write methods are exempt (Spring Data wraps single calls in their own transaction by default). |
| SAFE903 | spring_unvalidated_input | *Java + Spring Boot only.* Fires when a `@RestController` or `@Controller` method parameter binds `@RequestBody` or `@ModelAttribute` without `@Valid` or `@Validated`. `@PathVariable` and `@RequestParam` are deliberately NOT covered (they typically bind to primitives where bean validation has limited value). Complements SAFE801 - SAFE903 catches the validation gap structurally, SAFE801 catches the same hazard via dataflow. |
| SAFE904 | spring_async_checked_exception | *Java + Spring Boot only.* Fires on `@Async` methods that declare a `throws` clause. Spring runs `@Async` on a separate thread and silently swallows exceptions; the caller never sees them, regardless of what the throws clause declares. Fix: catch inside the body, log, and either return normally (`void`) or return `CompletableFuture.failedFuture(...)`. |

## Deliberately skipped rules

These rules are NOT registered for Java in v2.1.0rc1 because the Python / JS-family semantics don't translate cleanly:

| Code | Rule | Why skipped for Java |
|---|---|---|
| SAFE201 | bare_except | Python-only construct. Java's `catch (Throwable t)` is the closest analogue but is already covered by SAFE202 (empty body check) and SAFE203 (missing logging). A bare-catch rule for Java would duplicate those checks without adding new coverage. |
| SAFE301 | global_state | Python-only (`global` keyword). Java has no statement-level "this references module state" annotation; the closest analogue is `static` field access, but distinguishing legitimate constants from mutable globals requires class-scope analysis we don't yet do. |
| SAFE302 | global_mutation | See SAFE302 row in the rule table above. Deferred to a future release once class-scope analysis is in place. |
| SAFE305 | wide_scope_declaration | JavaScript / TypeScript only (`var` hoisting). Java's `var` (Java 10+) is local-only and block-scoped - no hoisting hazard. |

## Idiomatic fix patterns

When offering to walk the user through fixes, use these Java-native patterns:

### SAFE101 (function too long)

Decompose by responsibility. Java's preferred unit is a `private` helper method, often co-located in the same class. For Spring services, group related business logic into smaller `@Service` classes if a single service grows past ~5 methods:

```java
// Before: 80-line method
public Order placeOrder(OrderRequest req) {
    // ... validation
    // ... pricing
    // ... persistence
    // ... event publication
}

// After
public Order placeOrder(OrderRequest req) {
    var validated = validate(req);
    var priced = calculatePricing(validated);
    var saved = persist(priced);
    publishOrderCreatedEvent(saved);
    return saved;
}
```

### SAFE102 (nesting too deep)

Use early returns / guard clauses. For Spring controllers, prefer `Optional` over deeply-nested null checks:

```java
// Before
public Response getUser(Long id) {
    if (id != null) {
        if (id > 0) {
            var user = repo.findById(id);
            if (user.isPresent()) {
                return Response.ok(user.get());
            }
        }
    }
    return Response.notFound();
}

// After
public Response getUser(Long id) {
    if (id == null || id <= 0) return Response.badRequest();
    return repo.findById(id)
        .map(Response::ok)
        .orElseGet(Response::notFound);
}
```

### SAFE103 (too many arguments)

Group related parameters into a record (Java 14+) or builder:

```java
// Before
public Order create(String name, String email, BigDecimal amount, LocalDate due,
                    String currency, boolean recurring, Integer maxRetries, String notes) { ... }

// After (record)
public record OrderRequest(
    String name, String email, BigDecimal amount, LocalDate due,
    String currency, boolean recurring, Integer maxRetries, String notes
) {}
public Order create(OrderRequest req) { ... }
```

### SAFE104 (high complexity)

Replace nested conditionals with polymorphism (strategy pattern), or extract decision logic into a separate helper. For switch expressions with many arms, consider table-driven dispatch via a `Map<Key, Handler>`.

### SAFE202 (empty catch)

At minimum, log the exception. If swallowing is deliberate (e.g. a probe call that's allowed to fail), suppress with a `// nosafe: SAFE202` and a brief explanation comment.

```java
// Before
try { riskyCall(); } catch (Exception e) { }

// After
try { riskyCall(); } catch (Exception e) { logger.warn("riskyCall failed", e); }
```

### SAFE401 (resource lifecycle)

Use try-with-resources for any `AutoCloseable`:

```java
// Before
FileInputStream in = new FileInputStream(path);
try { /* use in */ } finally { in.close(); }

// After
try (FileInputStream in = new FileInputStream(path)) {
    // use in - auto-closed on any exit path including exception
}
```

### SAFE501 (unbounded loop)

`while (true)` is rarely the right shape in Java; prefer `while (condition)` with explicit termination. If a long-running loop must check periodically for a shutdown signal, wrap with a `Future` / `ExecutorService` and a cancellation flag.

### SAFE801 (tainted sink)

For SQL: use parameterised queries via `PreparedStatement` or Spring's `JdbcTemplate.query("... WHERE id = ?", id)` - never concatenate user input into SQL. For shell: prefer `ProcessBuilder` with an arg list (each arg is a separate element) over `Runtime.exec(String)`. For reflection: validate class / method names against an allow-list before passing to `Class.forName` / `Method.invoke`.

### SAFE901 (Spring field injection)

Convert to constructor injection. Spring 4.3+ auto-wires single-constructor classes without `@Autowired`:

```java
// Before
@Service
class UserService {
    @Autowired private UserRepository repo;
}

// After
@Service
class UserService {
    private final UserRepository repo;
    public UserService(UserRepository repo) { this.repo = repo; }
}
```

### SAFE902 (missing @Transactional)

Add `@Transactional` to the method, or to the whole `@Service` class if every method needs the same boundary:

```java
@Service
class UserService {
    @Transactional
    public void register(User user, AuditEvent audit) {
        userRepo.save(user);
        auditRepo.save(audit);
    }
}
```

### SAFE903 (unvalidated input)

Add `@Valid` (JSR-380) or `@Validated` (Spring's group-aware variant):

```java
// Before
@PostMapping("/create")
public User create(@RequestBody UserDto dto) { ... }

// After
@PostMapping("/create")
public User create(@RequestBody @Valid UserDto dto) { ... }
```

The DTO needs Bean Validation annotations (`@NotNull`, `@Size`, `@Email`, etc.) on its fields for `@Valid` to find anything to check.

### SAFE904 (@Async throws)

Catch inside the body. If the method returns a `Future`, wrap failures in `CompletableFuture.failedFuture`:

```java
// Before
@Async
public void runJob() throws InterruptedException { Thread.sleep(1000); }

// After (void)
@Async
public void runJob() {
    try { Thread.sleep(1000); }
    catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        logger.warn("runJob interrupted", e);
    }
}

// After (returning a Future)
@Async
public CompletableFuture<Void> runJob() {
    try {
        Thread.sleep(1000);
        return CompletableFuture.completedFuture(null);
    } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        return CompletableFuture.failedFuture(e);
    }
}
```

## Integration with Spring Boot tooling

safelint runs alongside the standard Java tool chain; it doesn't replace any of them. Typical wiring:

* **Maven / Gradle**: keep using SpotBugs / PMD / Checkstyle for style and general defect detection. safelint covers a different, narrower set (Holzmann safety rules + Spring framework-specific patterns).
* **Pre-commit**: drop into `.pre-commit-config.yaml` as shown in the install section above. Pre-commit handles file routing automatically via `types_or: [java]`.
* **CI**: invoke `safelint check src/main/java src/test/java --fail-on warning` (or `--mode ci`) in your build pipeline. Exit code 0 / 1 / 2 maps cleanly to "passed" / "violations found" / "setup error - install hint emitted on stderr".
* **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

For deeper integration with Spring Boot specifically, see the [Spring Boot test fixture validation results](../README.md) (when v2.1.0 GA ships) for a list of representative violation patterns from a real Spring petclinic-style reference app.
