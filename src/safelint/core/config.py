"""Configuration defaults, constants, and config loader for safelint.

Config is searched in this priority order (highest first):

1. ``safelint.toml`` - standalone TOML, keys at the top level (no wrapper)
2. ``pyproject.toml`` - ``[tool.safelint]`` section
3. Built-in defaults

When both files exist in the same directory, ``safelint.toml`` wins (matching
ruff's ``ruff.toml`` precedence convention).

TOML support uses the stdlib ``tomllib`` module (Python 3.11+).
"""

from __future__ import annotations

import copy
from pathlib import Path
import tomllib
from typing import Any

from safelint.core import _diagnostics


# ---------------------------------------------------------------------------
# Severity / mode constants
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {"warning": 0, "error": 1}

MODE_FAIL_ON: dict[str, str] = {"local": "error", "ci": "warning"}

TOML_CONFIG_FILENAME = "pyproject.toml"
TOML_CONFIG_KEY = "safelint"
STANDALONE_TOML_FILENAME = "safelint.toml"

# ---------------------------------------------------------------------------
# Default vendor / generated directories pruned from discovery
# ---------------------------------------------------------------------------
#
# Almost no project wants safelint walking into these - they hold
# third-party code (virtualenvs, ``node_modules``), build outputs
# (``build/`` / ``dist/``), or generated caches (``__pycache__``,
# ``.pytest_cache``, etc.). Without these defaults, a fresh
# ``safelint check --all-files`` from a project root with a venv at
# ``.venv/`` would trip over the virtualenv's own Python files and
# produce noise from code the user didn't author.
#
# **Two patterns per entry** because Python's ``fnmatch.fnmatchcase``
# matches the entire path string (anchored at both ends), combined
# with the literal ``/`` before ``<dir>`` in the nested form:
#
# * ``<dir>/**`` matches a top-level vendor dir (the most common case
#   - e.g. ``.venv/foo`` directly under the project root). The
#   anchored start means this pattern does NOT match a nested
#   occurrence like ``a/b/.venv/foo``.
# * ``**/<dir>/**`` matches the same name nested anywhere else
#   (e.g. ``packages/foo/node_modules/x``). The leading ``**/``
#   requires SOME parent path with a slash separator before ``<dir>``,
#   so this pattern does NOT match the top-level ``.venv/foo`` case
#   (no leading parent path with ``/`` before ``.venv``).
#
# Note: fnmatch's ``*`` and ``**`` both match across ``/`` separators
# (unlike pathspec / git-style globs where ``*`` is single-segment).
# Verify with ``fnmatch.fnmatchcase("a/b/c", "*")`` - returns ``True``.
# The reason we need both patterns is the *anchoring + literal slash*,
# not a "wildcards don't span slashes" limitation.
#
# Users can:
# * **Override completely** by setting ``exclude_paths = []`` in
#   their config - clears every default, useful for the rare case of
#   wanting safelint to look inside a normally-excluded directory.
# * **Extend additively** via ``extend_exclude_paths = [...]`` -
#   keeps the defaults and adds the user's patterns. Recommended for
#   project-specific excludes (``"generated/**"``, ``"vendor/**"``,
#   etc.).
_DEFAULT_EXCLUDE_VENDOR_DIRS: tuple[str, ...] = (
    # Python virtual environments
    ".venv",
    "venv",
    # Python test / build tooling
    ".tox",
    ".nox",
    # Python caches
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".ty_cache",
    # Python build outputs
    "build",
    "dist",
    # Coverage outputs
    "htmlcov",
    # JavaScript / Node
    "node_modules",
    # Site packages (defensive - sometimes installed into the project tree)
    "site-packages",
)

_DEFAULT_EXCLUDE_PATHS: list[str] = [pattern for vendor_dir in _DEFAULT_EXCLUDE_VENDOR_DIRS for pattern in (f"{vendor_dir}/**", f"**/{vendor_dir}/**")]


# ---------------------------------------------------------------------------
# Built-in defaults - every key can be overridden via pyproject.toml
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "mode": "local",
    "fail_on": "error",
    "exclude_paths": list(_DEFAULT_EXCLUDE_PATHS),  # copy so callers can't mutate the module-level list
    "ignore": [],
    "per_file_ignores": {},
    # Skip files whose size exceeds this many bytes. Guards against
    # OOM on accidentally-huge inputs (binary blobs masquerading as
    # ``.py``, very large generated parsers, etc.). Default 5 MiB is
    # large enough that no realistic source file should hit it; raise
    # the bound explicitly if your project has legitimately huge
    # generated source. ``0`` is rejected as a likely typo and falls
    # back to this default with a warning.
    "max_file_size_bytes": 5 * 1024 * 1024,
    "execution": {
        # Stop checking a file the moment the first violation is found.
        # Cheap structural rules run first so expensive checks are skipped
        # when basic problems already exist.
        "fail_fast": False,
        "order": [
            "function_length",
            "nesting_depth",
            "max_arguments",
            "bare_except",
            "empty_except",
            "global_state",
            "global_mutation",
            "wide_scope_declaration",
            "unbounded_loops",
            "complexity",
            "side_effects_hidden",
            "side_effects",
            "logging_on_error",
            "resource_lifecycle",
            "test_coupling",
            "test_existence",
            "missing_assertions",
            "tainted_sink",
            "return_value_ignored",
            "null_dereference",
            # Spring Boot framework-aware rules (SAFE9xx, Java-only)
            "spring_field_injection",
            "spring_missing_transactional",
            "spring_unvalidated_input",
            "spring_async_checked_exception",
        ],
    },
    "rules": {
        "function_length": {"enabled": True, "max_lines": 60, "severity": "error"},
        "nesting_depth": {"enabled": True, "max_depth": 2, "severity": "error"},
        "max_arguments": {"enabled": True, "max_args": 7, "severity": "error"},
        "complexity": {"enabled": True, "max_complexity": 10, "severity": "error"},
        "bare_except": {"enabled": True, "severity": "error"},
        "empty_except": {"enabled": True, "severity": "error"},
        "logging_on_error": {"enabled": True, "severity": "warning"},
        "global_state": {"enabled": True, "severity": "warning"},
        "global_mutation": {
            "enabled": True,
            "severity": "error",
            # JavaScript: function-body assignments to any of these
            # global namespaces fire the rule. ``process`` covers the
            # common ``process.env.X = ...`` pattern (chained namespace
            # walked leftward to the root identifier).
            "global_namespaces_javascript": [
                "globalThis",
                "window",
                "global",
                "self",
                "process",
            ],
        },
        # JavaScript-only: prefer ``let`` / ``const`` over ``var`` for
        # block scope. Holzmann Power-of-Ten Rule 6 ("declare variables
        # at the smallest possible scope") translated to JS's actual
        # scope-control mechanism. No Python equivalent - Python lacks
        # the var/let/const distinction.
        "wide_scope_declaration": {"enabled": True, "severity": "warning"},
        "side_effects_hidden": {
            "enabled": True,
            "severity": "error",
            # Per-language I/O primitive lists. Adding separate keys per
            # language rather than a single shared list avoids Python
            # false positives on calls like ``logger.error()`` (where
            # ``call_name`` returns ``"error"``) - each language's list
            # is only consulted on its own file extensions.
            "io_functions": ["open", "print", "input", "subprocess"],
            "io_functions_javascript": [
                "log",  # console.log
                "error",  # console.error
                "warn",  # console.warn
                "info",  # console.info
                "debug",  # console.debug
                "fetch",  # network I/O
                "readFile",
                "writeFile",
                "readFileSync",
                "writeFileSync",
                "open",  # fs.open
            ],
            "io_functions_java": [
                # PrintStream / PrintWriter methods - ``System.out.println(...)``
                # resolves to ``"println"`` after ``call_name`` strips the receiver.
                # ``format`` is deliberately NOT listed: ``call_name`` returns the
                # bare method name, so an entry would also match the pure
                # ``String.format(...)`` / ``MessageFormat.format(...)`` / SLF4J's
                # ``String.format``-wrapped logging calls and produce false
                # positives. ``printf`` is unambiguous (PrintStream / PrintWriter
                # only) so it stays in.
                "println",
                "print",
                "printf",
                # Java stdin / Scanner methods.
                "readLine",
                "nextLine",
                "nextInt",
                "next",
                # File I/O via ``new`` - ``call_name`` on ``object_creation_expression``
                # returns the simple class name.
                "FileInputStream",
                "FileOutputStream",
                "FileReader",
                "FileWriter",
                "BufferedReader",
                "BufferedWriter",
                "Scanner",
                "PrintWriter",
                # java.nio.file.Files static methods.
                "readAllBytes",
                "readAllLines",
                "readString",
                "writeString",
                "write",
                # Network I/O. ``HttpClient`` is NOT listed: it doesn't expose
                # a public constructor (the JDK uses static factory methods),
                # so ``call_name`` never returns ``"HttpClient"`` for the
                # standard ``HttpClient.newHttpClient()`` / ``newBuilder()``
                # acquirers. The actual I/O happens through ``send`` /
                # ``sendAsync`` on the resulting client.
                "Socket",
                "newHttpClient",  # HttpClient.newHttpClient() factory
                "send",  # HttpClient.send(request, ...)
                "sendAsync",  # HttpClient.sendAsync(request, ...)
            ],
            # Rust I/O primitives. Most common stdlib I/O is via MACROS
            # (``println!`` / ``print!`` / ``eprintln!`` / ``eprint!`` /
            # ``write!`` / ``writeln!``), which the rule walks as
            # ``macro_invocation`` nodes alongside regular calls.
            # ``format!`` and ``vec!`` are deliberately NOT here -
            # they don't perform I/O (return ``String`` / ``Vec<T>``).
            "io_functions_rust": [
                # Stdout / stderr macros
                "println",
                "print",
                "eprintln",
                "eprint",
                # ``write!`` / ``writeln!`` macros - write to any
                # ``Write`` impl (stdout, file, network).
                "write",
                "writeln",
                "dbg",  # ``dbg!(x)`` prints to stderr
                # std::fs read/write entry points - both bare and scoped
                # forms resolve via ``call_name``'s scoped_identifier
                # branch to the trailing bareword.
                "read_to_string",
                "read_to_end",
                "read_dir",
                "metadata",
                "canonicalize",
                # std::io::Read / std::io::Write trait methods
                "read",
                "read_exact",
                "read_line",
                "write_all",
                "write_fmt",
                "flush",
                # std::process - subprocess execution
                "spawn",
                "output",
                "status",
                # Network - TCP / UDP / HTTP
                "connect",  # TcpStream::connect
                "bind",  # UdpSocket::bind, TcpListener::bind
                "accept",  # TcpListener::accept
                "recv",
                "recv_from",
                "send_to",
            ],
            "pure_prefixes": [
                "calculate",
                "compute",
                "get",
                "check",
                "validate",
                "is",
                "has",
                "find",
                "parse",
                "transform",
                "convert",
                "format",
                "build",
                "resolve",
                "detect",
            ],
        },
        "side_effects": {
            "enabled": True,
            "severity": "warning",
            # Per-language defaults - see the note on ``side_effects_hidden``
            # above. ``io_name_keywords`` and the rule's general structure
            # are language-agnostic; only the I/O primitive list differs.
            "io_functions": ["open", "print", "input"],
            "io_functions_javascript": [
                "log",
                "error",
                "warn",
                "info",
                "debug",
                "fetch",
                "readFile",
                "writeFile",
                "readFileSync",
                "writeFileSync",
            ],
            "io_functions_java": [
                "println",
                "print",
                "printf",
                "readLine",
                "nextLine",
                "FileInputStream",
                "FileOutputStream",
                "FileReader",
                "FileWriter",
                "Scanner",
                "readAllBytes",
                "readAllLines",
                "writeString",
                "write",
            ],
            "io_functions_rust": [
                # SAFE304's list is a deliberately narrower subset of
                # SAFE303's ``io_functions_rust`` (mirrors the Java
                # SAFE303/SAFE304 handling). SAFE303-only entries
                # (``metadata`` / ``canonicalize`` / ``read_exact`` /
                # ``write_fmt`` / ``bind`` / ``accept`` / ``recv_from``)
                # are intentionally NOT in SAFE304's list because
                # flagging every non-pure-named caller of those would
                # be too noisy; SAFE303 only catches them when the
                # function name signals purity, which is a stronger
                # signal of incorrect placement.
                "println",
                "print",
                "eprintln",
                "eprint",
                "write",
                "writeln",
                "dbg",
                "read_to_string",
                "read_to_end",
                "read_dir",
                "read",
                "read_line",
                "write_all",
                "flush",
                "spawn",
                "output",
                "status",
                "connect",
                "recv",
                "send_to",
            ],
            "io_name_keywords": [
                "print",
                "log",
                "write",
                "read",
                "save",
                "load",
                "send",
                "fetch",
                "export",
                "import",
            ],
        },
        "resource_lifecycle": {
            "enabled": True,
            "severity": "error",
            # Default tracked functions cover the most common resource-acquisition
            # primitives across Python's stdlib + popular libraries. Users can
            # extend (without re-listing) via ``extend_tracked_functions``.
            "tracked_functions": [
                "open",  # builtins.open - files
                "connect",  # sqlite3.connect, psycopg2.connect, mysql.connect, …
                "session",  # requests.session(), sqlalchemy session factories
                "Session",  # PEP-8-named session classes (requests.Session, sqlalchemy.Session)
                "Lock",  # threading.Lock, asyncio.Lock, multiprocessing.Lock
                "RLock",  # threading.RLock, asyncio.RLock
                "Semaphore",  # threading.Semaphore, asyncio.Semaphore
                "Pool",  # multiprocessing.Pool, concurrent.futures.*Pool
                "ThreadPoolExecutor",  # concurrent.futures
                "ProcessPoolExecutor",
                "socket",  # socket.socket
                "mmap",  # mmap.mmap
                "TemporaryFile",  # tempfile.TemporaryFile / NamedTemporaryFile
                "NamedTemporaryFile",
                "TemporaryDirectory",
                "ZipFile",  # zipfile.ZipFile
                "TarFile",  # tarfile.TarFile / tarfile.open
            ],
            "cleanup_patterns": ["close", "commit", "rollback", "release", "shutdown"],
            # JavaScript: tracked acquirer call names. The rule fires when
            # any of these is called outside an enclosing ``try { ... }
            # finally { ... }`` block.
            "tracked_functions_javascript": [
                "createReadStream",
                "createWriteStream",
                "openSync",
                "createServer",
                "createConnection",
                "connect",
                "createWorker",
            ],
        },
        "unbounded_loops": {"enabled": True, "severity": "warning"},
        "missing_assertions": {
            "enabled": False,
            "severity": "warning",
            # JavaScript assertion-function names. Python uses the
            # built-in ``assert`` keyword (no config needed); JS doesn't
            # have an assert keyword, so the rule walks for *calls* to
            # any of these names. Default covers Node's ``assert``
            # module (top-level + the asserting helpers), browser/Node
            # ``console.assert``, and common test frameworks.
            "assertion_calls_javascript": [
                # Node ``assert`` module
                "assert",
                "ok",
                "equal",
                "strictEqual",
                "deepEqual",
                "deepStrictEqual",
                "notEqual",
                "notStrictEqual",
                "rejects",
                "throws",
                "doesNotThrow",
                "doesNotReject",
                "fail",
                "ifError",
                "match",
                # console.assert (browser + Node)
                "assert",  # already listed; harmless duplicate
                # Test frameworks (call-name level - receiver is irrelevant)
                "expect",  # Jest, Chai (when used via expect()), Vitest's vi.expect
                "should",  # Should.js
            ],
            # Java assertion-method names. Java has the built-in ``assert``
            # keyword (handled directly by the rule, no config needed for
            # that path), AND in test code uses JUnit / AssertJ / Hamcrest
            # method-call assertions. The list below covers JUnit 5
            # (``Assertions.*``), JUnit 4 (``Assert.*``), AssertJ
            # (``assertThat``), Hamcrest (``assertThat`` again), and the
            # ``fail(...)`` short form. ``call_name`` strips the receiver
            # (``Assertions.assertEquals`` resolves to ``"assertEquals"``).
            "assertion_calls_java": [
                # JUnit 5 Assertions
                "assertEquals",
                "assertNotEquals",
                "assertTrue",
                "assertFalse",
                "assertNull",
                "assertNotNull",
                "assertSame",
                "assertNotSame",
                "assertArrayEquals",
                "assertIterableEquals",
                "assertLinesMatch",
                "assertThrows",
                "assertDoesNotThrow",
                "assertAll",
                "assertTimeout",
                "assertTimeoutPreemptively",
                "assertInstanceOf",
                # AssertJ / Hamcrest entry point
                "assertThat",
                # Common short forms
                "fail",
            ],
            # Rust assertion-macro names. Rust expresses assertions
            # exclusively through macros (no ``assert`` keyword like
            # Python / Java). ``call_name`` doesn't help here - the
            # rule walks ``macro_invocation`` nodes and matches the
            # bareword macro name (with ``std::`` / ``core::`` qualifiers
            # stripped). Defaults cover the standard library's three
            # always-on assertion macros, the three debug-only variants,
            # and proptest's ``prop_assert*`` triplet which is widely
            # used in property-based test code. ``panic!`` / ``todo!`` /
            # ``unreachable!`` / ``unimplemented!`` are intentionally
            # NOT in the defaults: they're failure-exit markers, not
            # invariant assertions in the Power of Ten sense - projects
            # that want them counted can add them via
            # ``assertion_calls_rust``.
            "assertion_calls_rust": [
                # Standard library (always on)
                "assert",
                "assert_eq",
                "assert_ne",
                # Standard library (debug builds only)
                "debug_assert",
                "debug_assert_eq",
                "debug_assert_ne",
                # proptest crate - property-based test assertions
                "prop_assert",
                "prop_assert_eq",
                "prop_assert_ne",
            ],
        },
        "test_existence": {"enabled": False, "test_dirs": ["tests"], "severity": "warning"},
        "test_coupling": {"enabled": False, "test_dirs": ["tests"], "severity": "warning"},
        # Dataflow hybrid rules - disabled by default; opt-in via config
        "tainted_sink": {
            "enabled": False,
            "severity": "error",
            # Python source / sanitizer / sink lists.
            "sinks": [
                "eval",
                "exec",
                "compile",
                "system",
                "popen",
                "Popen",
                "run",
                "call",
                "check_output",
                "execute",
            ],
            "sanitizers": ["escape", "sanitize", "clean", "validate", "quote", "encode", "bleach"],
            "sources": ["input", "readline", "recv", "recvfrom", "read"],
            # JavaScript source / sanitizer / sink lists. Per-language
            # to avoid false positives - e.g. ``call_name`` returns
            # ``"read"`` for both Python's ``file.read()`` (a tainted
            # source) and JavaScript's ``Buffer.read()`` (which has a
            # very different threat model). Adding a new language is
            # additive: drop new ``<key>_<lang>`` lists in here.
            "sinks_javascript": [
                "eval",
                "Function",  # ``new Function(code)`` - same risk as eval
                "execScript",  # legacy IE
                "exec",  # child_process.exec
                "execSync",
                "spawn",
                "spawnSync",
                "execFile",
                "execFileSync",
                "setTimeout",  # only with string arg, but rule can't tell at this level
                "setInterval",  # same
                "innerHTML",  # via ``el.innerHTML = tainted`` - assignment-side, not call; documented limitation
            ],
            "sanitizers_javascript": [
                "escape",
                "sanitize",
                "encodeURIComponent",
                "encodeURI",
                "DOMPurify",  # commonly imported as a sanitizer
                "validate",
                "clean",
            ],
            "sources_javascript": [
                "prompt",  # window.prompt
                "readline",  # interactive readline
                "stdin",  # process.stdin
                "input",  # generic input wrappers
            ],
            # Java stdlib sink / sanitizer / source lists. Spring Boot adds
            # ``executeQuery`` etc. via the ``framework = "spring-boot"`` preset.
            "sinks_java": [
                # Runtime / process execution.
                "exec",  # Runtime.getRuntime().exec(...)
                "getRuntime",  # caller usually chains ``.exec(...)`` next
                "ProcessBuilder",  # ``new ProcessBuilder(tainted)``
                "loadLibrary",  # System.loadLibrary, Runtime.loadLibrary
                "load",  # System.load
                # Reflection - arbitrary class / method invocation by name
                # is a code-execution sink when ``name`` is user-controlled.
                "forName",  # Class.forName(tainted)
                "invoke",  # Method.invoke(receiver, tainted)
                "newInstance",  # Class.newInstance, Constructor.newInstance
                # Script engines (JSR 223) - executes arbitrary script source.
                "eval",  # ScriptEngine.eval
                # JDBC raw SQL execution. ``executeQuery`` / ``execute`` /
                # ``executeUpdate`` are sinks when the SQL string is built
                # from user input. ``PreparedStatement`` users would
                # parametrise these calls; raw ``Statement`` users
                # concatenate, which is the hazard.
                "executeQuery",
                "execute",
                "executeUpdate",
                "executeLargeUpdate",
                # URL fetch with attacker-controlled host - SSRF surface.
                "openConnection",  # URL.openConnection
                "openStream",  # URL.openStream
            ],
            "sanitizers_java": [
                # IMPORTANT: SAFE801 has a SINGLE shared ``sanitizers_java``
                # set that clears taint for every sink type (SQL,
                # reflection, shell, SSRF). Context-specific encoders
                # are deliberately NOT in the defaults:
                #
                # * HTML / XML encoders (OWASP ``forHtml`` / ``forXml`` /
                #   ``forJavaScript`` / ``forCssString``, Apache Commons
                #   ``escapeHtml*`` / ``escapeXml``, Spring ``htmlEscape``)
                #   - safe only for HTML output, NOT for SQL / shell /
                #   reflection. Including them would suppress real SAFE801
                #   findings like ``jdbc.query(... + forHtml(input))``.
                #
                # * URL encoders (``encode`` / ``encodeURIComponent``) -
                #   safe only for URL contexts. URL-encoding input before
                #   concatenating into SQL or shell would suppress those
                #   warnings even though URL encoding doesn't quote SQL
                #   metacharacters or shell metacharacters.
                #
                # Defaults below are limited to names that imply
                # *validation* (not encoding) or project-level
                # *wrappers* whose semantics are typically generic.
                # Even ``sanitize`` / ``quote`` are ambiguous in
                # principle (OWASP ``HtmlPolicyBuilder.sanitize`` is
                # HTML-only, SQL ``quote`` is SQL-only) - they're kept
                # in defaults because they're more commonly used as
                # project-level generic wrappers than as exact library
                # call sites. Projects with strict requirements should
                # configure ``[tool.safelint.rules.tainted_sink]
                # sanitizers_java`` explicitly, and a category-aware
                # sanitiser framework is on the v3.x roadmap.
                "sanitize",  # OWASP HtmlPolicyBuilder + generic wrappers
                "validate",  # generic input validators (idiomatic name)
                "quote",  # SQL / shell quoting helpers + generic wrappers
                "escape",  # generic; project-level wrappers + Apache Commons
            ],
            "sources_java": [
                # System / env sources.
                "getenv",  # System.getenv(name)
                "getProperty",  # System.getProperty - configurable, often user
                # Console / Scanner / BufferedReader stdin.
                "readLine",
                "nextLine",
                "next",
                "nextInt",
                # Servlet API - HttpServletRequest user-input methods.
                "getParameter",
                "getParameterValues",
                "getHeader",
                "getHeaders",
                "getQueryString",
                "getCookies",
                "getPathInfo",
                "getRequestURI",
                "getRemoteUser",
            ],
            # Rust stdlib sink / sanitizer / source lists. Rust has no
            # ``eval`` / dynamic-code-execution analogue; the security
            # surface is shell execution (``Command`` / ``arg`` /
            # ``args``), raw-SQL database APIs (sqlx / diesel /
            # rusqlite / postgres), and FFI loading. ``call_name``
            # strips the qualifier (``std::process::Command::new``
            # resolves to ``"new"``; ``cmd.arg(x)`` to ``"arg"``).
            "sinks_rust": [
                # Process execution.
                "Command",  # ``Command::new(tainted)`` - the program path
                "new",  # ``Command::new(tainted)`` - the bareword path resolves to "new"
                "arg",  # ``cmd.arg(tainted)`` - tainted command argument
                "args",  # ``cmd.args(tainted)`` - tainted args iterator
                # Database raw-SQL (sqlx / diesel / rusqlite / postgres).
                # All four crates expose a ``query`` / ``execute`` entry
                # point that takes a SQL string; bind parameters via
                # placeholders are safe, but interpolation isn't.
                "query",
                "query_as",
                "query_scalar",
                "execute",
                "execute_batch",
                # FFI / dynamic-library loading.
                "Library",  # ``libloading::Library::new(path)`` with tainted path
                # File-path sinks (path traversal). ``Path::new`` and
                # the ``read`` / ``write`` family take paths; tainted
                # paths can escape an allow-listed directory via ``..``.
                "open",  # ``File::open(tainted_path)``
            ],
            "sanitizers_rust": [
                # Narrow defaults - the same trade-off as Java's
                # sanitizers_java. Context-specific HTML / URL / shell
                # encoders are deliberately NOT included because they
                # only clear taint for their own output context;
                # including them would suppress real SAFE801 findings
                # when used for the wrong context.
                "validate",
                "sanitize",
                "escape",
                "quote",
                # Rust crate convention: ``percent_encode`` for URLs,
                # ``html_escape::encode_text`` for HTML. These ARE
                # context-specific; users should configure them per
                # rule rather than the global default.
            ],
            "sources_rust": [
                # Environment / process / args sources.
                "var",  # ``std::env::var(name)`` - returns user-controlled env value
                "args",  # ``std::env::args()`` - command-line argument iterator
                # Stdin sources.
                "read_line",  # ``stdin().read_line(&mut buf)``
                "read_to_string",  # ``File::read_to_string(...)`` / ``stdin().read_to_string(...)``
                "lock",  # ``stdin().lock()`` - returned reader is a source
                # Network sources (basic - frameworks add more).
                "recv",  # ``UdpSocket::recv``, ``Receiver::recv``
                "recv_from",
            ],
        },
        "return_value_ignored": {
            "enabled": False,
            "severity": "warning",
            # Python defaults - Python file/network/subprocess functions
            # whose return value carries success/failure info.
            "flagged_calls": [
                "run",
                "call",
                "check_output",
                "write",
                "send",
                "sendall",
                "sendfile",
                "seek",
                "truncate",
                "remove",
                "unlink",
                "rename",
                "replace",
                "makedirs",
                "mkdir",
                "rmdir",
            ],
            # JavaScript defaults - Node fs / stream / process methods
            # whose return value (or returned promise) carries
            # success/failure info. Discarded promises in particular
            # silently swallow rejections.
            "flagged_calls_javascript": [
                "write",  # stream.write, fs.write
                "writeFile",
                "writeFileSync",
                "unlink",
                "unlinkSync",
                "rename",
                "renameSync",
                "mkdir",
                "mkdirSync",
                "rmdir",
                "rmdirSync",
                "rm",
                "rmSync",
                "send",
                "sendall",
                "exec",  # child_process.exec
                "execSync",
                "spawn",
                "spawnSync",
            ],
            # Java methods whose return value carries success / failure
            # information. ``File.delete()`` / ``.mkdir()`` / ``.renameTo()``
            # return ``boolean`` (false on failure); ignoring them silently
            # swallows the failure. ``String`` / ``BigDecimal`` / etc. are
            # immutable - calling a mutator without using the result is a
            # common no-op bug.
            "flagged_calls_java": [
                # java.io.File: boolean-returning mutators
                "delete",
                "mkdir",
                "mkdirs",
                "renameTo",
                "setLastModified",
                "setReadOnly",
                "setWritable",
                "setReadable",
                "setExecutable",
                "createNewFile",
                # String immutables - ignoring the result is always a bug
                "trim",
                "strip",
                "toUpperCase",
                "toLowerCase",
                "replace",
                "replaceAll",
                "replaceFirst",
                "substring",
                "concat",
                "intern",
                # BigDecimal / BigInteger immutables
                "add",
                "subtract",
                "multiply",
                "divide",
                "remainder",
                "negate",
                "abs",
                # Futures: ignoring ``cancel()`` discards the success
                # boolean. ``get()`` is deliberately NOT listed because
                # ``get`` collides with ``Map.get``, ``Optional.get``,
                # and many getter-style methods where discarding the
                # return value is the normal pattern.
                "cancel",
            ],
            # Rust stdlib methods that return ``Result<_, _>`` or
            # ``Option<_>`` carrying success / failure information.
            # Bare-statement ``file.write(buf);`` discards the Result
            # silently - Rust's ``#[must_use]`` only warns at the
            # compiler level for new code, not for legacy code or
            # types defined outside the crate. ``call_name`` strips
            # the receiver, so ``file.write_all(buf)`` resolves to
            # ``"write_all"`` and matches the bareword list.
            "flagged_calls_rust": [
                # io::Write
                "write",
                "write_all",
                "write_fmt",
                "flush",
                # io::Read - rare to discard but possible
                "read",
                "read_exact",
                "read_to_end",
                "read_to_string",
                # std::fs filesystem mutators
                "remove_file",
                "remove_dir",
                "remove_dir_all",
                "rename",
                "copy",
                "create_dir",
                "create_dir_all",
                "set_permissions",
                "set_len",
                # Networking - socket I/O
                "send",
                "send_to",
                # std::process::Command runners
                "spawn",
                "output",
                "status",
                # std::process::Child
                "wait",
                "wait_with_output",
                "try_wait",
                "kill",
            ],
        },
        "null_dereference": {
            "enabled": False,
            "severity": "error",
            "nullable_methods": [],
            # JavaScript's null-or-undefined-returning methods. ``find``
            # / ``pop`` / ``shift`` are Array.prototype; ``get`` is
            # Map.prototype (returns ``undefined`` for missing keys);
            # ``getElementById`` / ``querySelector`` are DOM APIs that
            # return ``null`` for no match; ``exec`` is RegExp.prototype.
            # User can extend via ``[tool.safelint.rules.null_dereference]``.
            "nullable_methods_javascript": [
                "find",
                "pop",
                "shift",
                "get",
                "getElementById",
                "querySelector",
                "exec",
                "match",
                "closest",
            ],
            # Java's null-returning stdlib methods. Conservative defaults
            # covering the most common SAFE803 hazards in vanilla Java;
            # the Spring Boot preset adds ``find`` (EntityManager.find),
            # ``findById`` (when not using the Optional-returning
            # CrudRepository), and the Spring-cache pattern.
            "nullable_methods_java": [
                "get",  # Map.get(missing-key) returns null; Properties.get likewise
                "getOrDefault",  # returns default only when *value* is null, hazardous chain target
                "remove",  # Map.remove returns the previous value, null if absent
                "put",  # Map.put returns the previous value, null if no previous
                "putIfAbsent",  # null when binding succeeded (counterintuitive)
                # Servlet API - HttpServletRequest reads.
                "getParameter",
                "getHeader",
                "getCookie",
                "getAttribute",
                "getSession",  # may return null when ``create=false``
                # java.util.Properties / System
                "getProperty",
                # Reflection - many methods return null when not found.
                "getAnnotation",
                "getDeclaredAnnotation",
                "getEnclosingClass",
                "getEnclosingMethod",
                # Stream.findFirst / findAny return Optional, not null - so
                # NOT listed here. peek / orElse / orElseGet similarly fine.
            ],
            # Rust methods returning ``Option<T>`` or ``Result<T, E>``.
            # The Rust SAFE803 fires on ``<call>.unwrap()`` /
            # ``<call>.expect(...)`` when ``<call>``'s name is in this
            # list - unwrapping the resulting Option / Result panics on
            # ``None`` / ``Err``, the closest analogue to a null-
            # dereference in a language without ``null``.
            "nullable_methods_rust": [
                # std collections - missing-key lookups
                "get",  # HashMap::get / Vec::get / BTreeMap::get / slice::get
                "get_mut",
                "get_key_value",
                # Vec / slice positional access
                "first",
                "last",
                "first_mut",
                "last_mut",
                "pop",  # Vec::pop
                # Iterator advancing - exhausted iterator returns None
                "next",
                "next_back",
                "nth",
                "peek",  # Peekable::peek
                # String / &str search
                "find",
                "rfind",
                "chars",  # chains commonly into ``.next()``
                # Parse / convert
                "parse",  # &str::parse - returns Result
                "to_socket_addrs",
                # Env / process
                "var",  # std::env::var - returns Result
                "var_os",
                # Filesystem
                "read",
                "read_to_string",
                "read_to_end",
                "read_dir",
                "metadata",
                "canonicalize",
                # IO
                "read_line",
                "lines",
                # Common Option-returning conversion methods
                "checked_add",
                "checked_sub",
                "checked_mul",
                "checked_div",
            ],
        },
        # Spring Boot framework-aware rules (SAFE9xx band). Java-only.
        # Default-disabled under the vanilla preset so non-Spring users
        # see no behaviour change; the ``[tool.safelint.java] framework
        # = "spring-boot"`` preset flips ``enabled`` to True for the
        # whole set via ``_JAVA_FRAMEWORK_PRESETS["spring-boot"]``.
        "spring_field_injection": {"enabled": False, "severity": "warning"},
        "spring_missing_transactional": {"enabled": False, "severity": "error"},
        "spring_unvalidated_input": {"enabled": False, "severity": "error"},
        "spring_async_checked_exception": {"enabled": False, "severity": "warning"},
        # Rust-idiom rules. Slotted into category bands per the
        # SafeLint rule-numbering policy (see CLAUDE.md); all four
        # are language-specific (no cross-language counterpart) and
        # disabled by default so non-Rust projects see no behaviour
        # change. Opt in via [tool.safelint.rules.<name>] enabled = true.
        "panic_macros_outside_tests": {
            "enabled": False,
            "severity": "warning",
            # Macro names that count as "panicking". Defaults to the
            # three obvious offenders; ``unreachable!`` is deliberately
            # excluded (idiomatic for impossible-branch markers).
            # Override to add custom panic macros from a project's
            # own crate (``my_assert!`` etc.) or to add ``unreachable``.
            "panic_macros_rust": [
                "panic",
                "todo",
                "unimplemented",
            ],
        },
        "lock_poisoning_ignored": {"enabled": False, "severity": "warning"},
        "silent_result_discard": {"enabled": False, "severity": "warning"},
        "unlogged_error_branch": {"enabled": False, "severity": "warning"},
        "result_unwrap_outside_tests": {"enabled": False, "severity": "warning"},
        "needless_mut": {"enabled": False, "severity": "warning"},
        "unchecked_arithmetic_on_input": {"enabled": False, "severity": "warning"},
        "truncating_as_cast": {
            "enabled": False,
            "severity": "warning",
            # Per-target overridable. Default covers the fixed-width
            # integer types and f32. ``isize`` / ``usize`` / ``i128`` /
            # ``u128`` / ``f64`` are the widest types - casts TO them
            # don't truncate, so they're not in the default set.
            "truncating_cast_targets_rust": [
                "i8",
                "u8",
                "i16",
                "u16",
                "i32",
                "u32",
                "i64",
                "u64",
                "f32",
            ],
        },
        "dangerous_mem_ops": {
            "enabled": False,
            "severity": "error",
            # std::mem footguns. All four have safer Rust idioms:
            # ``transmute`` -> ``From`` / ``TryFrom`` / ``bytemuck``;
            # ``forget`` -> ``ManuallyDrop``;
            # ``zeroed`` / ``uninitialized`` -> ``MaybeUninit``.
            "dangerous_mem_ops_rust": [
                "transmute",
                "transmute_copy",
                "forget",
                "zeroed",
                "uninitialized",
            ],
        },
        "undocumented_unsafe": {"enabled": False, "severity": "warning"},
    },
}


# ---------------------------------------------------------------------------
# JavaScript runtime presets
# ---------------------------------------------------------------------------
#
# JavaScript source is JavaScript source - the parser, AST, and rule logic
# are runtime-agnostic. But the *defaults* baked into ``DEFAULTS["rules"]``
# (sinks / sanitisers / sources / I/O verbs / nullable methods / resource
# acquirers / global namespaces) are Node-flavoured today: ``fs.readFile``,
# ``createReadStream``, ``process.env``, ``child_process.exec``, etc.
#
# Other JavaScript runtimes (Browser / Deno / Cloudflare Workers / Bun /
# WASM-hosted JS engines) expose different APIs. Users select one via:
#
#   [tool.safelint.javascript]
#   runtime = "browser"   # or "deno" / "cloudflare-workers" / "bun" / "node"
#
# The named preset overrides Node defaults *before* the user's TOML is
# merged in - so an explicit ``[tool.safelint.rules.tainted_sink]
# sinks_javascript = […]`` in the user's config still wins, even when a
# runtime is selected. The default runtime is ``"node"`` so existing
# users see no behaviour change.
#
# To add a new preset: add a ``"<name>"`` entry below with the same
# nested shape as ``DEFAULTS["rules"]`` (only the keys you want to
# override). To add a new language whose runtime varies similarly,
# follow the same pattern with a ``[tool.safelint.<lang>] runtime``
# selector.

_JS_VALID_RUNTIMES: frozenset[str] = frozenset({"node", "browser", "deno", "cloudflare-workers", "bun"})

_JS_RUNTIME_PRESETS: dict[str, dict[str, Any]] = {
    # ``node`` is the baseline - equal to DEFAULTS, so the preset is empty
    # (no overrides needed). Listed for completeness so unknown-runtime
    # validation can compare against the full set of accepted names.
    "node": {},
    # ``browser`` - Web APIs (DOM, fetch, localStorage, BroadcastChannel,
    # observers). No Node fs / child_process / process surface.
    "browser": {
        "rules": {
            "tainted_sink": {
                "sinks_javascript": [
                    "eval",
                    "Function",
                    "execScript",  # legacy IE / DOM
                    "setTimeout",
                    "setInterval",
                    "write",  # document.write
                    "writeln",
                ],
                "sources_javascript": [
                    "prompt",
                    "confirm",
                    "getItem",  # localStorage / sessionStorage
                ],
            },
            "return_value_ignored": {
                # ``EventTarget.dispatchEvent`` returns a boolean
                # (``false`` if any handler called ``preventDefault``);
                # ignoring it loses the cancellation signal. The other
                # browser DOM-mutation / event-registration methods
                # (``setItem``, ``removeItem``, ``clear``,
                # ``addEventListener``, ``postMessage``) all return
                # ``undefined`` - capturing the return value would be
                # meaningless, so flagging them only produces noise.
                "flagged_calls_javascript": [
                    "dispatchEvent",
                ],
            },
            "null_dereference": {
                "nullable_methods_javascript": [
                    # DOM lookups that return null on miss:
                    "getElementById",
                    "querySelector",
                    "closest",
                    "getAttribute",
                    "getNamedItem",
                    # Common collection methods:
                    "find",
                    "pop",
                    "shift",
                    # Regex / string match:
                    "exec",
                    "match",
                ],
            },
            "resource_lifecycle": {
                # Browser has no fs surface; the resources that need
                # cleanup are observers / workers / streams / sockets.
                "tracked_functions_javascript": [
                    "Worker",
                    "SharedWorker",
                    "EventSource",
                    "WebSocket",
                    "BroadcastChannel",
                    "IntersectionObserver",
                    "MutationObserver",
                    "ResizeObserver",
                    "PerformanceObserver",
                    "ReadableStream",
                    "WritableStream",
                    "TransformStream",
                ],
            },
            "global_mutation": {
                "global_namespaces_javascript": [
                    "globalThis",
                    "window",
                    "self",
                    "document",
                    # Drop ``global`` and ``process`` - Node-only.
                ],
            },
            "side_effects_hidden": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "setItem",
                    "getItem",
                    "removeItem",
                    "appendChild",
                    "removeChild",
                    "replaceChild",
                ],
            },
            "side_effects": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "setItem",
                    "removeItem",
                ],
            },
        },
    },
    # ``deno`` - ``Deno.*`` APIs + Web APIs. No Node-style ``fs`` /
    # ``child_process`` / ``process``.
    "deno": {
        "rules": {
            "tainted_sink": {
                "sinks_javascript": [
                    "eval",
                    "Function",
                    "run",  # Deno.run (deprecated but still seen)
                    "Command",  # Deno.Command (newer)
                    "setTimeout",
                    "setInterval",
                ],
                "sources_javascript": [
                    "prompt",
                    "readLine",
                    "read",  # Deno.stdin.read
                    "readTextFile",
                ],
            },
            "return_value_ignored": {
                "flagged_calls_javascript": [
                    "writeFile",
                    "writeTextFile",
                    "remove",
                    "rename",
                    "mkdir",
                    "chmod",
                    "chown",
                    "truncate",
                    "write",
                    "send",
                ],
            },
            "null_dereference": {
                "nullable_methods_javascript": [
                    "find",
                    "pop",
                    "shift",
                    "get",  # Map.get / Headers.get
                    "exec",
                    "match",
                ],
            },
            "resource_lifecycle": {
                "tracked_functions_javascript": [
                    # ``call_name`` extracts the method, not the namespace:
                    "open",  # Deno.open
                    "openSync",
                    "connect",  # Deno.connect / connectTls
                    "listen",  # Deno.listen / listenTls
                    "create",  # Deno.create
                    "createSync",
                ],
            },
            "global_mutation": {
                "global_namespaces_javascript": [
                    "globalThis",
                    "self",
                    "Deno",
                    # Drop window, global, process
                ],
            },
            "side_effects_hidden": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "readFile",
                    "readTextFile",
                    "writeFile",
                    "writeTextFile",
                    "open",
                    "create",
                ],
            },
            "side_effects": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "readFile",
                    "readTextFile",
                    "writeFile",
                    "writeTextFile",
                ],
            },
        },
    },
    # ``cloudflare-workers`` - Workers Runtime (V8 isolates with Web APIs +
    # KV / Durable Objects / R2). No fs surface.
    "cloudflare-workers": {
        "rules": {
            "tainted_sink": {
                "sinks_javascript": [
                    "eval",
                    "Function",
                    "setTimeout",
                    "setInterval",
                ],
                "sources_javascript": [
                    # Request body methods carry untrusted user input:
                    "text",
                    "json",
                    "formData",
                    "arrayBuffer",
                    "blob",
                ],
            },
            "return_value_ignored": {
                "flagged_calls_javascript": [
                    "put",  # KV.put, R2.put
                    "delete",
                    "send",
                    # ``addEventListener`` deliberately omitted - it
                    # returns ``undefined`` and produces only noise
                    # when flagged (same reason as the browser preset).
                ],
            },
            "null_dereference": {
                "nullable_methods_javascript": [
                    "get",  # KV.get returns null for missing keys
                    "find",
                    "pop",
                    "shift",
                    "exec",
                    "match",
                ],
            },
            "resource_lifecycle": {
                # Workers has very few resource-lifecycle concerns -
                # WebSocket pairs being the main one.
                "tracked_functions_javascript": [
                    "WebSocketPair",
                ],
            },
            "global_mutation": {
                "global_namespaces_javascript": [
                    "globalThis",
                    "self",
                    # No window / document / global / process
                ],
            },
            "side_effects_hidden": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "put",
                    "delete",
                    "get",  # KV.get
                ],
            },
            "side_effects": {
                "io_functions_javascript": [
                    "log",
                    "error",
                    "warn",
                    "info",
                    "debug",
                    "fetch",
                    "put",
                    "delete",
                ],
            },
        },
    },
    # ``bun`` - mostly Node-compatible API surface plus ``Bun.*`` extras.
    # Defaults equal to Node with a couple of Bun-specific additions
    # (``Bun.spawn``, ``Bun.serve``, ``Bun.file`` - call names ``spawn``
    # / ``serve`` / ``file`` mostly already in the Node defaults).
    "bun": {
        "rules": {
            "resource_lifecycle": {
                "tracked_functions_javascript": [
                    # Inherit Node's defaults; add Bun.serve which keeps
                    # an HTTP server alive for the lifetime of the process.
                    "createReadStream",
                    "createWriteStream",
                    "openSync",
                    "createServer",
                    "createConnection",
                    "connect",
                    "createWorker",
                    "serve",  # Bun.serve
                    "listen",  # net.listen / Bun.listen
                ],
            },
        },
    },
}


def _apply_javascript_runtime_preset(defaults: dict[str, Any], runtime: str) -> None:
    """Modify *defaults* in place to apply the JS runtime preset.

    No-op when the runtime is ``"node"`` (defaults already encode that
    runtime) or when the runtime is unknown - unknown-runtime warnings
    are emitted by the caller via ``_diagnostics.print_warning``.

    The preset's nested shape mirrors ``DEFAULTS``: each key is a path
    into ``DEFAULTS["rules"][...]``, with values that *replace* the
    Node default for that rule. The user's TOML is then deep-merged on
    top, so explicit user overrides still win.
    """
    preset = _JS_RUNTIME_PRESETS.get(runtime)
    if not preset:
        return
    # ``deepcopy`` each value before planting it into the defaults dict
    # so downstream callers can't mutate ``_JS_RUNTIME_PRESETS`` by
    # mutating the resolved config (the preset's lists are otherwise
    # shared by reference). Defensive - current consumers treat the
    # config as read-only, but the cost is one shallow deepcopy per
    # preset key and the protection is permanent.
    import copy  # noqa: PLC0415

    for rule_name, rule_overrides in preset.get("rules", {}).items():
        target = defaults["rules"].setdefault(rule_name, {})
        for key, value in rule_overrides.items():
            target[key] = copy.deepcopy(value)


# ---------------------------------------------------------------------------
# Java framework presets
# ---------------------------------------------------------------------------
#
# Same architectural shape as ``_JS_RUNTIME_PRESETS`` above but selected via
# ``[tool.safelint.java] framework = "..."`` in TOML. The current presets:
#
#   * ``vanilla`` (default) - pure-Java stdlib defaults; the lists baked
#     into ``DEFAULTS["rules"]`` already encode this preset, so the entry
#     is empty.
#   * ``spring-boot`` - augments the vanilla defaults with Spring-aware
#     sinks (``JdbcTemplate``'s ``query`` / ``queryForObject`` / ``queryForList``
#     / ``queryForMap`` / ``queryForRowSet`` / ``batchUpdate``,
#     ``RestTemplate``'s ``getForObject`` / ``getForEntity`` / ``postForObject``
#     / ``postForEntity`` / ``postForLocation`` / ``patchForObject`` for SSRF;
#     bare ``put`` / ``delete`` / ``update`` / ``exchange`` are deliberately
#     NOT in the preset because they collide with HashMap / File / project
#     helpers under SAFE801's single-set design - users who specifically
#     want them can opt in via TOML) and nullable methods
#     (``queryForObject``: zero-rows raises ``EmptyResultDataAccessException``
#     rather than returning null, but RowMapper implementations and
#     nullable column values can still produce a null result, so the
#     conservative treatment applies).
#
# Source-language analysis is identical across frameworks - same parser,
# same AST walks, same per-rule logic. Only the *defaults* shift, so a
# user explicitly setting ``sinks_java = [...]`` in their TOML still
# wins over the preset.
#
# Adding a framework: add an entry below with the same nested shape as
# ``DEFAULTS["rules"]`` (only the keys you want to override). Adding a
# new language whose framework varies similarly follows the same pattern
# with a ``[tool.safelint.<lang>] framework`` selector.

_JAVA_VALID_FRAMEWORKS: frozenset[str] = frozenset({"vanilla", "spring-boot"})

_JAVA_FRAMEWORK_PRESETS: dict[str, dict[str, Any]] = {
    # ``vanilla`` is the baseline - equal to DEFAULTS, so the preset is
    # empty. Listed so unknown-framework validation can compare against
    # the full set of accepted names.
    "vanilla": {},
    # ``spring-boot`` - the Spring Web / Spring Data / Spring JDBC
    # ecosystem. The vanilla Java sinks / sources already cover the
    # Servlet API (which Spring MVC uses underneath); the preset adds
    # the framework-level abstractions that sit on top:
    #
    #   * ``JdbcTemplate`` - the raw-SQL escape hatch. ``query`` /
    #     ``queryForObject`` / ``queryForList`` / ``update`` /
    #     ``batchUpdate`` all take a SQL string the application code
    #     typically concatenates. Treated as sinks for SAFE801.
    #   * ``RestTemplate`` / ``WebClient`` - outbound HTTP. SSRF
    #     surface when the URL is built from user input. ``exchange``
    #     / ``getForObject`` / ``getForEntity`` / ``postForObject`` /
    #     ``postForEntity`` / ``put`` / ``delete`` cover the canonical
    #     methods.
    #   * ``queryForObject`` raises ``EmptyResultDataAccessException``
    #     when zero rows match; nullable results come from RowMapper
    #     implementations and nullable column values, which is why
    #     the method is included in ``nullable_methods_java``. The
    #     Optional-returning alternatives ``JdbcClient.findOne`` /
    #     ``JdbcClient.findFirst`` were added in Spring 6.1 for
    #     unambiguous null-or-present access in newer code.
    #
    # The preset deliberately does NOT touch:
    #
    #   * SAFE304 ``side_effects`` - exempting ``@Bean`` factory methods
    #     from the I/O warning would require annotation-aware rule
    #     logic the preset can't express through default overrides.
    #     Users with noisy SAFE304 hits on factory methods can
    #     suppress via ``// nosafe: SAFE304`` (Java's comment prefix)
    #     until a future ``skip_functions_annotated_with`` knob lands.
    #   * SAFE401 ``resource_lifecycle`` - Spring-managed resources
    #     (``JdbcTemplate``-borrowed connections) are typically not
    #     held in user code at all, so the vanilla tracked-function
    #     list doesn't fire on them. Raw ``DriverManager.getConnection``
    #     still fires (correctly) regardless of Spring presence.
    #   * SAFE203 ``logging_on_error`` - SLF4J / Log4j method names
    #     (``error`` / ``warn`` / ``info`` / ``debug`` / ``trace``)
    #     are already in the universal logger-method set.
    "spring-boot": {
        "rules": {
            "tainted_sink": {
                # Spring sinks layered on top of vanilla Java's stdlib
                # set. The vanilla list (``exec``, ``executeQuery``, ...)
                # also fires because the preset REPLACES rather than
                # extends; we include both vanilla and Spring-specific
                # entries here so the preset is self-contained. Users
                # who configure ``[tool.safelint.rules.tainted_sink]
                # sinks_java = [...]`` in TOML still win - their
                # explicit list overrides the preset.
                "sinks_java": [
                    # Vanilla Java sinks (mirrored from DEFAULTS so the
                    # preset is a complete replacement, not a partial
                    # one. Keep these in sync with the vanilla list
                    # above; a drift-detection test in tests/core/
                    # test_java_framework_presets.py guards against
                    # divergence.)
                    "exec",
                    "getRuntime",
                    "ProcessBuilder",
                    "loadLibrary",
                    "load",
                    "forName",
                    "invoke",
                    "newInstance",
                    "eval",
                    "executeQuery",
                    "execute",
                    "executeUpdate",
                    "executeLargeUpdate",
                    "openConnection",
                    "openStream",
                    # Spring JdbcTemplate raw-SQL methods. Includes ``query``
                    # which - despite being a common verb - is rarely a
                    # collision (no standard Java type has a public ``query``
                    # method in the way HashMap has ``put`` or File has
                    # ``delete``). ``batchUpdate`` is Spring-only naming.
                    # Bare ``update`` is deliberately NOT in defaults
                    # because it collides with ``Hibernate.Session.update``,
                    # Swing's ``update``, and project-local helpers; users
                    # who want ``jdbcTemplate.update`` flagged can add
                    # ``update`` to ``[tool.safelint.rules.tainted_sink]
                    # sinks_java`` explicitly.
                    "query",
                    "queryForObject",
                    "queryForList",
                    "queryForMap",
                    "queryForRowSet",
                    "batchUpdate",
                    # Spring NamedParameterJdbcTemplate - same names,
                    # same risk. Already covered by the above.
                    # Spring RestTemplate / WebClient - outbound HTTP,
                    # SSRF surface when URL contains user input. The
                    # ``...For{Object,Entity,Location}`` names are
                    # unambiguous (no other API uses them). Bare
                    # ``put`` / ``delete`` / ``exchange`` are
                    # deliberately NOT in defaults because they collide
                    # heavily with HashMap.put, File.delete,
                    # CurrencyExchange.exchange, and many project-local
                    # helpers. Users who specifically need
                    # ``restTemplate.put`` / ``.delete`` / ``.exchange``
                    # SSRF detection can add them via TOML; the SAFE801
                    # rule has a single-set design without receiver-
                    # aware matching, so flagging them globally would
                    # create more noise than signal on typical Java
                    # code.
                    "getForObject",
                    "getForEntity",
                    "postForObject",
                    "postForEntity",
                    "postForLocation",
                    "patchForObject",
                ],
            },
            "null_dereference": {
                "nullable_methods_java": [
                    # Vanilla Java nullable methods (mirrored for the
                    # same self-contained reason).
                    "get",
                    "getOrDefault",
                    "remove",
                    "put",
                    "putIfAbsent",
                    "getParameter",
                    "getHeader",
                    "getCookie",
                    "getAttribute",
                    "getSession",
                    "getProperty",
                    "getAnnotation",
                    "getDeclaredAnnotation",
                    "getEnclosingClass",
                    "getEnclosingMethod",
                    # Spring JdbcTemplate.queryForObject(...) raises
                    # ``EmptyResultDataAccessException`` on zero rows;
                    # null can still surface via RowMapper output or
                    # nullable column values, hence the conservative
                    # entry here. The newer ``JdbcClient.findOne``
                    # returns Optional and is deliberately NOT listed.
                    "queryForObject",
                    # Spring ApplicationContext.getBean(name) throws
                    # when missing; NOT null-returning. NOT listed.
                ],
            },
            # Spring-specific structural rules (SAFE901-904) - opt-in
            # under the vanilla preset, opt-out under spring-boot.
            # Flipping ``enabled`` to True here is the only knob
            # users need to get Spring-aware structural checks
            # (the dataflow rules SAFE801 / SAFE803 are already opt-in
            # for performance reasons and remain so under spring-boot).
            "spring_field_injection": {"enabled": True},
            "spring_missing_transactional": {"enabled": True},
            "spring_unvalidated_input": {"enabled": True},
            "spring_async_checked_exception": {"enabled": True},
        },
    },
}


def _apply_java_framework_preset(defaults: dict[str, Any], framework: str) -> None:
    """Modify *defaults* in place to apply the Java framework preset.

    No-op when the framework is ``"vanilla"`` (defaults already encode
    that framework) or when the framework is unknown - unknown-framework
    warnings are emitted by :func:`_resolve_java_framework` before this
    helper runs.

    The preset's nested shape mirrors ``DEFAULTS``: each key is a path
    into ``DEFAULTS["rules"][...]``, with values that *replace* the
    vanilla default for that rule. The user's TOML is then deep-merged
    on top, so explicit user overrides still win.
    """
    preset = _JAVA_FRAMEWORK_PRESETS.get(framework)
    if not preset:
        return
    import copy  # noqa: PLC0415

    for rule_name, rule_overrides in preset.get("rules", {}).items():
        target = defaults["rules"].setdefault(rule_name, {})
        for key, value in rule_overrides.items():
            target[key] = copy.deepcopy(value)


def _resolve_java_framework(cfg: dict[str, Any]) -> str:
    """Extract the Java framework selector from *cfg* (user TOML), defaulting to ``"vanilla"``.

    Validates the value: unknown frameworks surface as a stderr warning
    via :mod:`safelint.core._diagnostics` and fall back to ``"vanilla"``.
    Type errors (non-string ``framework``) surface the same way. Mirrors
    :func:`_resolve_javascript_runtime` exactly - same diagnostic
    posture, same fallback shape.
    """
    java_section = cfg.get("java", {})
    if not isinstance(java_section, dict):
        from safelint.core import _diagnostics  # noqa: PLC0415

        _diagnostics.print_warning(
            f"[tool.safelint.java] must be a table, got {type(java_section).__name__} - falling back to framework='vanilla'",
        )
        return "vanilla"
    framework = java_section.get("framework", "vanilla")
    if not isinstance(framework, str):
        from safelint.core import _diagnostics  # noqa: PLC0415

        _diagnostics.print_warning(
            f"[tool.safelint.java].framework must be a string, got {type(framework).__name__} - falling back to 'vanilla'",
        )
        return "vanilla"
    if framework not in _JAVA_VALID_FRAMEWORKS:
        from safelint.core import _diagnostics  # noqa: PLC0415

        valid = ", ".join(sorted(_JAVA_VALID_FRAMEWORKS))
        _diagnostics.print_warning(
            f"[tool.safelint.java].framework={framework!r} is not recognised (valid: {valid}) - falling back to 'vanilla'",
        )
        return "vanilla"
    return framework


def _resolve_javascript_runtime(cfg: dict[str, Any]) -> str:
    """Extract the JS runtime selector from *cfg* (user TOML), defaulting to ``"node"``.

    Validates the value: unknown runtimes surface as a stderr warning
    via :mod:`safelint.core._diagnostics` and fall back to ``"node"``.
    Type errors (non-string ``runtime``) surface the same way.
    """
    js_section = cfg.get("javascript", {})
    if not isinstance(js_section, dict):
        from safelint.core import _diagnostics  # noqa: PLC0415  - circular avoidance

        _diagnostics.print_warning(
            f"[tool.safelint.javascript] must be a table, got {type(js_section).__name__} - falling back to runtime='node'",
        )
        return "node"
    runtime = js_section.get("runtime", "node")
    if not isinstance(runtime, str):
        from safelint.core import _diagnostics  # noqa: PLC0415

        _diagnostics.print_warning(
            f"[tool.safelint.javascript].runtime must be a string, got {type(runtime).__name__} - falling back to 'node'",
        )
        return "node"
    if runtime not in _JS_VALID_RUNTIMES:
        from safelint.core import _diagnostics  # noqa: PLC0415

        valid = ", ".join(sorted(_JS_VALID_RUNTIMES))
        _diagnostics.print_warning(
            f"[tool.safelint.javascript].runtime={runtime!r} is not recognised (valid: {valid}) - falling back to 'node'",
        )
        return "node"
    return runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# File parsers
# ---------------------------------------------------------------------------


def _read_toml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* as TOML and return the full document, or None on error."""
    try:
        with candidate.open("rb") as fp:
            return tomllib.load(fp)
    # The error IS reported via _diagnostics.print_error; SAFE203's heuristic
    # only recognises stdlib logging method names so it can't see the call.
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:  # nosafe: SAFE203
        _diagnostics.print_error(f"failed to parse {candidate}: {exc} - skipping file")
        return None


def _peek_toml_file(candidate: Path) -> dict[str, Any] | None:
    """Parse *candidate* quietly: same as :func:`_read_toml_file` but no diagnostic.

    Used by probes (e.g. :func:`_directory_has_config`) that decide
    whether a directory contains an active config file *before*
    ``load_config`` runs. Without a quiet variant, a malformed
    ``safelint.toml`` would print the same parse-error diagnostic
    twice - once from the probe, once from the real load - confusing
    users who'd see the file flagged repeatedly. Real load remains
    the authoritative reporter.
    """
    try:
        # SAFE304 suppression below: this *is* an I/O probe by design.
        # Alternative names ("read", "load") would imply an authoritative
        # read, but this helper is deliberately a quiet peek.
        with candidate.open("rb") as fp:  # nosafe: SAFE304
            return tomllib.load(fp)
    # Fail-silent on purpose: the actual load path will surface the
    # error to the user. SAFE203's heuristic doesn't see the silence
    # as logging, so the suppression marker isn't needed.
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):  # nosafe: SAFE203
        return None


# ---------------------------------------------------------------------------
# Per-directory config finders
# ---------------------------------------------------------------------------


def _try_standalone(directory: Path) -> dict[str, Any] | None:
    """Return the parsed safelint.toml from *directory*, or None."""
    candidate = directory / STANDALONE_TOML_FILENAME
    if not candidate.exists():
        return None
    return _read_toml_file(candidate)


def _try_pyproject(directory: Path) -> dict[str, Any] | None:
    """Return ``[tool.safelint]`` from *directory*/pyproject.toml, or None."""
    candidate = directory / TOML_CONFIG_FILENAME
    if not candidate.exists():
        return None
    doc = _read_toml_file(candidate)
    if doc is None:
        return None
    return doc.get("tool", {}).get(TOML_CONFIG_KEY)


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def _directory_has_config(directory: Path) -> bool:
    """Return True when *directory* contains an *active* safelint config file.

    "Active" mirrors :func:`load_config` exactly:

    * ``safelint.toml`` is parsed quietly; a malformed file is treated
      as *not* a config (so the upward walk continues, just like
      ``load_config`` falls through to the next candidate). Without
      this, a broken ``safelint.toml`` would still anchor the cache
      at a directory whose config never actually loads, and the user
      would silently get an unexpected ``.safelint_cache/`` placement.
    * ``pyproject.toml`` only counts when it actually has a
      ``[tool.safelint]`` section - an unrelated ``pyproject.toml``
      higher up the tree (e.g. a Python package whose author never
      configured safelint) shouldn't pin the cache there.

    Uses :func:`_peek_toml_file` (silent) rather than
    :func:`_read_toml_file` (verbose) so a malformed file's
    diagnostic is emitted exactly once - by the actual load path
    that follows. Otherwise the same broken file would print the
    same parse-error to stderr twice per run.
    """
    standalone = directory / STANDALONE_TOML_FILENAME
    if standalone.exists():
        return _peek_toml_file(standalone) is not None
    pyproject = directory / TOML_CONFIG_FILENAME
    if not pyproject.exists():
        return False
    doc = _peek_toml_file(pyproject)
    return doc is not None and doc.get("tool", {}).get(TOML_CONFIG_KEY) is not None


def find_config_root(search_from: Path | None = None) -> Path | None:
    """Return the directory holding the active safelint config, or None if defaults are used.

    Walks upward from *search_from* (defaults to cwd) using the same
    precedence as :func:`load_config`:

    1. ``safelint.toml``
    2. ``pyproject.toml`` containing a ``[tool.safelint]`` section

    Returns ``None`` when no config file is discoverable along the
    upward walk - the caller can then fall back to a sensible default
    (e.g. *search_from* itself) for any path that wants to live "next
    to the config".

    Used by the cache-dir resolver so ``.safelint_cache/`` ends up at
    the actual project root instead of an arbitrary subdirectory the
    user happened to pass to ``safelint check``.
    """
    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        if _directory_has_config(parent):
            return parent
    return None


def _validated_str_sequence(value: object, *, field_name: str) -> list[str]:
    """Return *value* as ``list[str]`` or raise a clear :class:`TypeError`.

    Two rejections matter equally:

    * **Bare strings** - ``ignore = "SAFE701"`` (missing brackets) would
      otherwise unpack into single-character entries via Python's
      iterable-unpacking sugar, silently producing a corrupted list.
      Tested explicitly because ``str`` *is* iterable; a plain
      ``isinstance(value, Iterable)`` check would accept it.
    * **Non-string elements** - coercing them via ``str(...)`` (the old
      behaviour) was wrong: if the user wrote ``[101]`` instead of
      ``["SAFE101"]``, silent coercion produced ``"101"`` and the
      ignore matched nothing.

    Used in both the ``extend_ignore`` and ``extend_per_file_ignores``
    merge paths so the existing list, the extension list, and each
    entry within them are all uniformly validated before any
    iterable-unpacking happens.
    """
    if not isinstance(value, (list, tuple)):
        msg = f"{field_name} must be a list of strings, got {type(value).__name__}"
        raise TypeError(msg)
    non_strings = [e for e in value if not isinstance(e, str)]
    if non_strings:
        bad = ", ".join(f"{type(e).__name__}({e!r})" for e in non_strings)
        msg = f"{field_name} must contain only strings - got: {bad}"
        raise TypeError(msg)
    return [e for e in value if isinstance(e, str)]


def _merge_extend_ignore(merged: dict[str, Any], extend_ignore: object) -> None:
    """Append ``extend_ignore`` entries onto ``merged["ignore"]`` (order-preserving dedupe).

    Both the *existing* ``ignore`` list and the new *extend_ignore* are
    validated as ``list[str]`` before merging. Without validating the
    base list, a misconfigured ``ignore = "SAFE701"`` would expand
    char-by-char during ``[*existing, *extend_ignore]`` and slip past
    the engine's downstream type-guard (which only sees the resulting
    ``list[str]``).
    """
    typed_existing = _validated_str_sequence(merged.get("ignore", []), field_name="ignore")
    typed_extend = _validated_str_sequence(extend_ignore, field_name="extend_ignore")
    merged["ignore"] = list(dict.fromkeys([*typed_existing, *typed_extend]))


def _merge_extend_per_file_ignores(merged: dict[str, Any], extend_pfi: object) -> None:
    """Merge ``extend_per_file_ignores`` into ``merged["per_file_ignores"]`` per glob pattern.

    Both the base ``per_file_ignores`` and the new ``extend_per_file_ignores``
    are validated as ``dict`` before merging. Without checking the base,
    a misconfigured ``per_file_ignores = "tests/**"`` (string) would fall
    through to ``_merge_one_pfi_pattern`` and raise a confusing
    AttributeError on ``.get()`` instead of a clear TypeError.
    """
    if not isinstance(extend_pfi, dict):
        msg = f"extend_per_file_ignores must be a mapping, got {type(extend_pfi).__name__}"
        raise TypeError(msg)
    existing_raw = merged.get("per_file_ignores", {})
    if not isinstance(existing_raw, dict):
        msg = f"per_file_ignores must be a mapping, got {type(existing_raw).__name__}"
        raise TypeError(msg)
    existing_pfi: dict[str, list[str]] = existing_raw
    # Iteration over a runtime-validated dict[Any, Any]; the type checker
    # can't infer per-key/value types so we annotate explicitly inside the
    # loop body for the call site to type-check.
    for raw_pattern, raw_entries in extend_pfi.items():
        pattern = str(raw_pattern)
        _merge_one_pfi_pattern(existing_pfi, pattern, raw_entries)
    merged["per_file_ignores"] = existing_pfi


def _merge_one_pfi_pattern(existing_pfi: dict[str, list[str]], pattern: str, entries: object) -> None:
    """Merge *entries* into *existing_pfi*[*pattern*] with order-preserving dedupe.

    Validates both the existing entries (in case ``per_file_ignores`` was
    misconfigured at base) and the new entries before unpacking. A
    string-instead-of-list typo (``"SAFE101"`` instead of ``["SAFE101"]``)
    raises a clear ``TypeError`` rather than silently expanding into
    single-character codes.
    """
    typed_existing = _validated_str_sequence(existing_pfi.get(pattern, []), field_name=f"per_file_ignores[{pattern!r}]")
    typed_entries = _validated_str_sequence(entries, field_name=f"extend_per_file_ignores[{pattern!r}]")
    existing_pfi[pattern] = list(dict.fromkeys([*typed_existing, *typed_entries]))


# Unique sentinel used by :func:`_apply_extend_keys` to distinguish
# *absent* from *explicitly-set-to-an-empty-or-falsy-value*. The dict
# ``.pop(key, None)`` idiom can't tell those apart - an explicit
# ``extend_ignore = 0`` would silently skip type validation otherwise.
_MISSING_KEY = object()


def _apply_extend_keys(merged: dict[str, Any]) -> dict[str, Any]:
    """Fold ``extend_ignore`` / ``extend_per_file_ignores`` into the resolved config.

    Modelled on ruff's ``extend-select`` / ``extend-ignore`` ergonomics: lets
    users *grow* a list-typed config value instead of replacing it. Without
    these keys, a project that wants to add ``"SAFE701"`` to the default
    ``ignore = []`` while keeping anything else added by their config would
    have to re-list every existing entry.

    Both keys are stripped from the returned dict so downstream consumers
    (engine, runner) only see the canonical ``ignore`` / ``per_file_ignores``.

    Sentinel-based detection means an explicitly-set falsy value
    (``extend_ignore = []`` or ``extend_ignore = 0``) is *not* skipped -
    empty lists pass through validation cleanly, and bad types like ``0``
    raise a clear :class:`TypeError` instead of being silently dropped.
    """
    extend_ignore = merged.pop("extend_ignore", _MISSING_KEY)
    if extend_ignore is not _MISSING_KEY:
        _merge_extend_ignore(merged, extend_ignore)
    extend_pfi = merged.pop("extend_per_file_ignores", _MISSING_KEY)
    if extend_pfi is not _MISSING_KEY:
        _merge_extend_per_file_ignores(merged, extend_pfi)
    return merged


def load_config(search_from: Path | None = None) -> dict[str, Any]:
    """Locate and load safelint config, merging it with the built-in defaults.

    Searches upward from *search_from* (defaults to cwd). At each directory
    the lookup order is:

    1. ``safelint.toml`` (standalone - keys at top level)
    2. ``pyproject.toml`` → ``[tool.safelint]``

    Always returns a fresh, deep-copied dict so callers can mutate the
    result (e.g. appending to ``ignore``) without corrupting the module
    ``DEFAULTS`` or sharing nested lists across loads.

    The user config may use ``extend_ignore`` / ``extend_per_file_ignores``
    to *grow* the corresponding default lists rather than replace them
    (mirrors ruff's ``extend-select`` / ``extend-ignore``). These keys
    are folded into ``ignore`` / ``per_file_ignores`` and stripped from
    the returned dict - downstream consumers only see the canonical keys.

    Returns a copy of ``DEFAULTS`` when no config file is found.
    """
    root = search_from or Path.cwd()
    for parent in [root, *root.parents]:
        # ``or`` short-circuits on falsy, so an empty-but-present
        # standalone config (``{}``) would let us silently fall through
        # to pyproject.toml. Check presence (None vs anything) explicitly.
        cfg = _try_standalone(parent)
        if cfg is None:
            cfg = _try_pyproject(parent)
        if cfg is not None:
            # Apply the JS runtime preset (if any) to a fresh copy of
            # DEFAULTS *before* the user's TOML is merged in. The
            # preset replaces Node defaults with browser / deno /
            # cloudflare-workers / bun equivalents; the user's
            # explicit ``_javascript`` config keys then win over the
            # preset via the deep_merge that follows.
            defaults_with_preset = copy.deepcopy(DEFAULTS)
            _apply_javascript_runtime_preset(defaults_with_preset, _resolve_javascript_runtime(cfg))
            _apply_java_framework_preset(defaults_with_preset, _resolve_java_framework(cfg))
            return _apply_extend_keys(deep_merge(defaults_with_preset, cfg))
    return copy.deepcopy(DEFAULTS)
