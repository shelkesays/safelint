# Java

SafeLint analyses Java source for the Holzmann "Power of Ten" safety rules, function length, nesting depth, cyclomatic complexity, error-handling discipline, hidden side effects, dataflow taint, and other classes of bug that style linters like Checkstyle and PMD don't catch. Java support landed in **v2.1.0** alongside a dedicated **Spring Boot framework preset** that adds Spring-aware sinks, nullable methods, and four `SAFE9xx` framework-specific structural rules. Java does NOT replace SpotBugs / Checkstyle / PMD / ErrorProne, it runs alongside them and covers a different, narrower set focused on Holzmann safety + Spring-specific patterns.

## File extensions

- **`.java`**, parsed by `tree-sitter-java`. Picked up by `safelint check` (directory mode, `--all-files` mode, and the pre-commit hook).

Kotlin (`.kt`), Groovy (`.groovy`), and Scala (`.scala`) are NOT yet registered; they would land as separate language modules with their own extras when added.

## Quick start

```bash
pip install 'safelint[java]'           # the tool runs on Python; the [java] extra adds the Java grammar
safelint check src/                    # lint a directory (git-modified files by default)
safelint check --all-files .           # lint everything
safelint check --format json src/      # machine-readable for editors / CI
```

If your Java project doesn't already have a Python tool chain, `pipx install 'safelint[java]'` isolates the install. Maven / Gradle plugins are NOT required; safelint is a standalone CLI that reads source files directly.

v2.1.0+ ships every language grammar as an opt-in extra, plain `pip install safelint` installs only the engine and would skip every `.java` file with an install hint on first run.

## Rules that fire on Java

**20 rules apply to Java**: 16 cross-language rules + 4 Spring Boot framework-specific rules (`SAFE9xx`, enabled by the `spring-boot` preset). 4 rules are deliberately skipped, see the next section.

| Code | Rule | Notes for Java |
|---|---|---|
| [SAFE101](../configuration/rules.md#safe101-function_length) | `function_length` | Counts source lines on `method_declaration` / `constructor_declaration` / `lambda_expression` / `static_initializer`. Default cap is 60. Lambda bodies count toward their own size, not the enclosing method's. |
| [SAFE102](../configuration/rules.md#safe102-nesting_depth) | `nesting_depth` | Counts `if` / `for` / `enhanced_for` (for-each) / `while` / `do` / `try` / `try_with_resources` / `switch_expression` (Java 14+). `synchronized` blocks add visual indent but are NOT counted (no control-flow branch). Default max 2. |
| [SAFE103](../configuration/rules.md#safe103-max_arguments) | `max_arguments` | Counts `formal_parameter` and `spread_parameter` (varargs `T... args`). The `receiver_parameter` form (`Foo this`) is excluded (analogue of Python's `self`). Default cap 7. |
| [SAFE104](../configuration/rules.md#safe104-complexity) | `complexity` | Cyclomatic complexity, every `if` / `for` / `enhanced_for` / `while` / `do` / `catch` / ternary adds one. Both Java switch shapes count their cases: colon-form (`switch_block_statement_group`) and arrow-form (`switch_rule`, Java 14+). `&&` / `\|\|` short-circuit operators inside `binary_expression` add one each (no `??`; Java uses `Objects.requireNonNullElse` for null-coalescing). Default cap 10. |
| [SAFE202](../configuration/rules.md#safe202-empty_except) | `empty_except` | Fires on `catch (Exception e) {}` and on catch bodies containing only a literal expression (`{ 0; }`, `{ null; }`, `{ "TODO"; }`) or a single comment (`{ // todo }`, `{ /* nope */ }`). tree-sitter-java emits comments as named children of blocks (unlike JS where they're extras), so the rule correctly classifies comment-only catch bodies as empty. |
| [SAFE203](../configuration/rules.md#safe203-logging_on_error) | `logging_on_error` | Requires a logging call in every catch block that doesn't re-raise. Recognised logger method names cover SLF4J / Log4j / java.util.logging: `error` / `warn` / `info` / `debug` / `trace` / `severe` / `fine` / `finer` / `finest` / `log` / `exception`. `call_name` strips the receiver, so `logger.error(...)` and `LoggerFactory.getLogger(Foo.class).error(...)` both resolve to `"error"`. Re-raise pattern `catch (Type e) { throw e; }` is recognised when the thrown identifier matches the catch-parameter binding. |
| [SAFE303](../configuration/rules.md#safe303-side_effects_hidden) | `side_effects_hidden` | Fires when a method with a "pure" name prefix (`get` / `compute` / `is` / `has` / `validate` / `parse` / etc.) calls an I/O primitive. Default `io_functions_java` covers `PrintStream` (`println` / `print` / `printf`), Scanner / BufferedReader stdin readers, file IO via `new` (`FileInputStream` / `FileOutputStream` / `FileReader` / `FileWriter` / `Scanner` / `PrintWriter`), `java.nio.file.Files` static methods (`readAllBytes` / `readAllLines` / `writeString` / `write`), and network (`Socket` / `HttpClient`). |
| [SAFE304](../configuration/rules.md#safe304-side_effects) | `side_effects` | Same I/O primitive set as SAFE303 but fires on any method whose name doesn't *signal* I/O. **Spring users:** the `spring-boot` preset does NOT exempt `@Bean` factory methods - if you have noisy hits on factory methods that legitimately create side-effectful resources, suppress with `# nosafe: SAFE304` until a future `skip_functions_annotated_with` knob lands. |
| [SAFE401](../configuration/rules.md#safe401-resource_lifecycle) | `resource_lifecycle` | Java's idiom is try-with-resources (`try (Resource r = ...) { ... }`) which auto-closes any `AutoCloseable`; the classic `try { ... } finally { r.close(); }` form is accepted too. Default tracked acquirers: file streams (`FileInputStream` / `FileOutputStream` / `FileReader` / `FileWriter` / `BufferedReader` / `BufferedWriter` / `Scanner` / `PrintWriter` / `RandomAccessFile`), `java.nio.file.Files` factory methods (`newBufferedReader` / `newBufferedWriter` / `newInputStream` / `newOutputStream`), network (`Socket` / `ServerSocket`), JDBC (`getConnection`), `FileChannel.open`. |
| [SAFE501](../configuration/rules.md#safe501-unbounded_loops) | `unbounded_loops` | Fires on `while (true)` without a `break`. Java's labelled-break form (`outer: while (true) { for (...) { break outer; } }`) is recognised via `labeled_statement` parent traversal. Note: Java uses `identifier` (NOT JS's `statement_identifier`) as the label-token type. `enhanced_for_statement` and `switch_expression` are break-scope boundaries so a `break` inside a Java foreach / arrow-switch doesn't count toward an enclosing `while`. |
| [SAFE601](../configuration/rules.md#safe601-missing_assertions) | `missing_assertions` | **Hybrid Java detection:** counts both the built-in `assert` keyword (parsed as `assert_statement`) AND JUnit / AssertJ / Hamcrest method-call assertions. Default `assertion_calls_java` covers JUnit 5 `Assertions.*` (assertEquals / assertTrue / assertThrows / assertAll / assertTimeout / assertInstanceOf / etc.), AssertJ / Hamcrest `assertThat`, and `fail`. Disabled by default. |
| [SAFE701](../configuration/rules.md#safe701-test_existence) | `test_existence` | Looks for `<ClassName>Test.java` (JUnit unit-test default), `<ClassName>Tests.java` (Spring's preferred form), `<ClassName>IT.java` (Maven Surefire / Failsafe integration tests), and `Test<ClassName>.java` (legacy prefix). Default `test_dirs` is `["tests"]`; **Maven / Gradle projects should override to `["src/test/java"]`** in their config. Disabled by default. |
| [SAFE702](../configuration/rules.md#safe702-test_coupling) | `test_coupling` | Same candidate filenames as SAFE701; fires when a source file changes in the commit but no paired test does. Disabled by default. |
| [SAFE801](../configuration/rules.md#safe801-tainted_sink) | `tainted_sink` | Method parameters are seeded as tainted on function entry (every `formal_parameter` / `spread_parameter` name; `receiver_parameter` `Foo this` is excluded). Default vanilla sinks: `Runtime.exec` / `ProcessBuilder` / `forName` / `invoke` / `eval` (JSR-223) / `executeQuery` / `execute` / `executeUpdate` / `openConnection` / `openStream`. Default vanilla sources: `getenv` / `getProperty` / `readLine` / `nextLine` / Servlet API (`getParameter` / `getHeader` / `getQueryString` / `getCookies` / `getPathInfo` / `getRemoteUser`). Default vanilla sanitisers cover Apache Commons Text (`escapeHtml*` / `escapeXml` / `escapeJava` / `escapeJson`), URL encoding (`encode` / `encodeURIComponent`), generic (`sanitize` / `validate` / `quote`), Spring (`htmlEscape`), and the full OWASP Java Encoder API (`forHtml` / `forJavaScript` / `forCssString` / `forUri` / `forXml`). The `spring-boot` preset adds `JdbcTemplate.query` / `queryForObject` / `queryForList` / `queryForMap` / `update` / `batchUpdate` and `RestTemplate.exchange` / `getForObject` / `getForEntity` / `postForObject` / `postForEntity` / `put` / `delete` (SSRF surface). Disabled by default. |
| [SAFE802](../configuration/rules.md#safe802-return_value_ignored) | `return_value_ignored` | Fires on bare expression statements whose call discards a meaningful return. Default vanilla `flagged_calls_java`: `java.io.File` boolean-returning mutators (`delete` / `mkdir` / `mkdirs` / `renameTo` / `setLastModified` / `setReadOnly` / `setWritable` / `setReadable` / `setExecutable` / `createNewFile`), `String` / `BigDecimal` / `BigInteger` immutables (`trim` / `strip` / `toUpperCase` / `replace` / `replaceAll` / `substring` / `concat` / `add` / `subtract` / `multiply` / etc.), and `Future.cancel`. Disabled by default. |
| [SAFE803](../configuration/rules.md#safe803-null_dereference) | `null_dereference` | Fires on chained access (`field_access` / `array_access` / `method_invocation` with chained receiver) where the receiver is a nullable-returning call. Default vanilla `nullable_methods_java`: `Map` / `Properties` (`get` / `getOrDefault` / `remove` / `put` / `putIfAbsent`), Servlet-request (`getParameter` / `getHeader` / `getCookie` / `getAttribute` / `getSession`), `System.getProperty`, reflection (`getAnnotation` / `getDeclaredAnnotation` / `getEnclosingClass` / `getEnclosingMethod`). Pass-through wrappers `parenthesized_expression` and `cast_expression` are peeled so `((Foo) map.get(k)).bar` is recognised. **Java has NO optional-chaining operator** (`?.` doesn't exist) - the only safe guards are `if (result != null)` or `Optional.ofNullable(...)`. The `spring-boot` preset adds `queryForObject` (returns null on zero rows). Disabled by default. |
| [SAFE901](../configuration/rules.md#safe901-spring_field_injection) | `spring_field_injection` | **Java + Spring Boot only.** Fires on `@Autowired` on a field. Spring's reference docs recommend constructor injection (immutable, testable, fail-fast on missing deps). Both bare `@Autowired` and fully-qualified `@org.springframework.beans.factory.annotation.Autowired` are recognised. Enabled by `framework = "spring-boot"`. |
| [SAFE902](../configuration/rules.md#safe902-spring_missing_transactional) | `spring_missing_transactional` | **Java + Spring Boot only.** Fires when a `@Service` or `@Component` method does 2+ Spring Data repository writes (`save` / `saveAll` / `saveAndFlush` / `delete` / `deleteAll` / `deleteById` / `update` etc.) without `@Transactional` (on the method or the class). Single-write methods are exempt. Enabled by `framework = "spring-boot"`. |
| [SAFE903](../configuration/rules.md#safe903-spring_unvalidated_input) | `spring_unvalidated_input` | **Java + Spring Boot only.** Fires when a `@RestController` or `@Controller` method parameter binds `@RequestBody` or `@ModelAttribute` without `@Valid` or `@Validated`. `@PathVariable` / `@RequestParam` are deliberately NOT covered (typically bind to primitives). Complements SAFE801 structurally. Enabled by `framework = "spring-boot"`. |
| [SAFE904](../configuration/rules.md#safe904-spring_async_checked_exception) | `spring_async_checked_exception` | **Java + Spring Boot only.** Fires on `@Async` methods that declare a `throws` clause. Spring runs `@Async` on a separate thread and silently swallows exceptions; the caller never sees them. Fix: catch inside the body or return `CompletableFuture.failedFuture(...)`. Enabled by `framework = "spring-boot"`. |

The 4 rules **not registered for Java**:

- [SAFE201 `bare_except`](../configuration/rules.md#safe201-bare_except), Python-only construct. Java's `catch (Throwable t)` is the closest analogue but is already covered by SAFE202 (empty body) and SAFE203 (missing logging).
- [SAFE301 `global_state`](../configuration/rules.md#safe301-global_state), Python-only (`global` keyword). Java has no statement-level "this references module state" annotation.
- [SAFE302 `global_mutation`](../configuration/rules.md#safe302-global_mutation), Python's `global` keyword and JS's `globalThis.x = ...` patterns have no clean Java analogue. The natural Java equivalent (writes to non-final static fields from outside the declaring class's own static initialiser) needs class-scope analysis the rule doesn't yet do. Deferred to a future release.
- [SAFE305 `wide_scope_declaration`](../configuration/rules.md#safe305-wide_scope_declaration), JavaScript / TypeScript only (`var` hoisting). Java's `var` (Java 10+) is local-only and block-scoped, no hoisting hazard.

## Configuration

SafeLint config is read from `[tool.safelint]` in `pyproject.toml` or from a standalone `safelint.toml` at the project root. Java projects that don't already have a `pyproject.toml` typically prefer the standalone form (without the `[tool.safelint]` prefix).

### Framework presets

Java source is Java source - the parser, AST, and rule logic are framework-agnostic. But the *defaults* baked into the rules (taint sinks, nullable methods, etc.) shift depending on which framework the project uses. `[tool.safelint.java] framework = "<name>"` selects the preset:

| Framework | When to pick it | What changes |
|---|---|---|
| `vanilla` (default) | Plain Java applications, Jakarta EE, Android, Spring-free libraries | Stdlib-only defaults (the lists in the rules table above). The four `SAFE9xx` Spring-specific rules are disabled. |
| `spring-boot` | Spring Boot 2.x / 3.x applications - Spring MVC, Spring Data JPA, Spring JDBC, Spring WebFlux | Adds `JdbcTemplate` / `RestTemplate` methods to SAFE801 sinks (SSRF surface). Adds `queryForObject` to SAFE803 nullable methods. **Enables the four `SAFE901-904` Spring rules.** |

Configure via TOML:

```toml
# safelint.toml (standalone) - no [tool.safelint] wrapper
[java]
framework = "spring-boot"

[rules.tainted_sink]
enabled = true        # dataflow rules are opt-in; flip on for Spring apps

[rules.test_existence]
test_dirs = ["src/test/java"]   # Maven / Gradle convention

# Or, in pyproject.toml:
[tool.safelint.java]
framework = "spring-boot"
```

Explicit per-rule TOML config still wins over the preset; setting `[tool.safelint.rules.tainted_sink] sinks_java = [...]` overrides whatever the preset planted. The default framework is `vanilla` so existing v2.1.0+ users with no Java config see no surprise behaviour.

### Per-rule TOML overrides

Standard pattern - override any per-language config list with the `_java` suffix:

```toml
[tool.safelint.rules.side_effects_hidden]
io_functions_java = ["println", "print", "writeFile"]   # narrower than the default

[tool.safelint.rules.tainted_sink]
enabled = true
sinks_java = ["exec", "executeQuery", "myInternalSink"]
sanitizers_java = ["escape", "myProjectSanitizer"]
sources_java = ["readLine", "getParameter", "getHeader"]

[tool.safelint.rules.return_value_ignored]
enabled = true
flagged_calls_java = ["delete", "renameTo", "trim", "myFunctionThatMustHaveReturnUsed"]

[tool.safelint.rules.null_dereference]
enabled = true
nullable_methods_java = ["get", "find", "queryForObject", "myCustomNullable"]

[tool.safelint.rules.resource_lifecycle]
tracked_functions_java = ["FileInputStream", "Socket", "MyCustomResource"]
```

All accept a list of strings; bare-string typos (`sinks_java = "eval"` instead of `["eval"]`) raise a clear `TypeError` instead of silently coercing into a set of characters.

## Installing the Java extra

Java grammar support ships as an optional extra so non-Java projects don't pay for it:

```bash
pip install 'safelint[java]'              # adds .java only
pip install 'safelint[python,java]'       # polyglot Python + Java monorepo
pip install 'safelint[all]'               # kitchen-sink, every supported grammar
```

Without the extra, `safelint check` skips `.java` files with a one-line install hint at lint time. If at least one other supported file (e.g. a Python file in a mixed repo) does get linted, the run continues normally. **If every candidate file gets skipped**, the typical case in a Java-only project, the [silent-failure guard](../configuration/cli.md#exit-code-2--silent-failure-triggers) fires and SafeLint exits with code 2 plus the install hint embedded in the error, so CI / pre-commit can't accidentally report green on an un-linted run.

## Pre-commit integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/shelkesays/safelint
    rev: v2.1.0       # pin to a release (use the latest GA tag)
    hooks:
      - id: safelint
        # Java users add the matching extra so pre-commit's isolated
        # environment installs ``tree-sitter-java``.
        additional_dependencies: ['safelint[java]']
        # The published hook's ``types_or`` already includes python,
        # javascript, ts, tsx, and java. Optional: scope to a directory.
        files: ^src/
```

For a Maven / Gradle project that organises sources under `src/main/java` and tests under `src/test/java`, prefer:

```yaml
      - id: safelint
        additional_dependencies: ['safelint[java]']
        files: ^src/(main|test)/java/
```

See [Pre-commit integration](../pre-commit.md) for the full hook reference.

## Java-specific config keys

All cross-language rules accept a `_java`-suffixed variant of their per-language config:

- `[tool.safelint.rules.side_effects_hidden]`, `io_functions_java`
- `[tool.safelint.rules.side_effects]`, `io_functions_java`
- `[tool.safelint.rules.resource_lifecycle]`, `tracked_functions_java`
- `[tool.safelint.rules.missing_assertions]`, `assertion_calls_java`
- `[tool.safelint.rules.tainted_sink]`, `sinks_java`, `sanitizers_java`, `sources_java`
- `[tool.safelint.rules.return_value_ignored]`, `flagged_calls_java`
- `[tool.safelint.rules.null_dereference]`, `nullable_methods_java`

The Spring-specific `SAFE9xx` rules use the standard `enabled` / `severity` knobs only; no per-rule list config today (the Spring annotation names they look for are fixed).

## Integration with existing Java tooling

SafeLint runs alongside the standard Java tool chain; it doesn't replace any of them:

- **SpotBugs / PMD / Checkstyle** keep covering style and general defect detection. SafeLint covers a different, narrower set (Holzmann safety rules + Spring framework-specific patterns).
- **ErrorProne** focuses on compile-time correctness; SafeLint is a separate review-time pass.
- **CI**: invoke `safelint check src/main/java src/test/java --mode ci` in your build. Exit code 0 / 1 / 2 maps to "passed" / "violations found" / "setup error".
- **IDE**: any JSON-output-consuming editor plugin (the safelint JSON schema is stable in v2.0.0+) can surface violations inline.

## Contributing

Want to refine a rule's Java behaviour, add a Spring-aware handler, or extend coverage to other JVM languages (Kotlin / Groovy / Scala)? See [Adding a language](../contributing/adding-a-language.md) for the architecture overview, or open an issue / PR against the [main repo](https://github.com/shelkesays/safelint).
