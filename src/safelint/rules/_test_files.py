"""Shared lexical test-file identification.

Used two ways, in opposite directions:

* SAFE601 / SAFE701 / SAFE702 ask "is this a test file?" to scope *into* test
  code (``test_functions_only``);
* SAFE101 / SAFE203 / SAFE302 / SAFE304 / SAFE401 ask the same question to scope
  *out of* it (``skip_test_code``, #198), because the patterns those rules flag
  are conventional in a test and the volume was burying the findings that matter.

Answers one question purely from a path (no filesystem probing): *is this file a
test file?* - a file is a test either because it lives under a configured
``test_dirs`` entry (path-component match) or because its filename follows the
language's test-file naming convention (``test_*.py`` / ``*.test.ts`` /
``*Test.java`` / ...).

Lives in ``rules/`` as a private shared helper (mirrors
``rules/_rust_test_attribute.py``) so the test-coverage rules (``test_coverage``)
and the assertion rule (``documentation``) share **one** definition of "test
file" rather than each rolling its own - a divergence would let SAFE601 scope
differently from SAFE701/702 for the same ``test_dirs``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from safelint.core._validators import _validated_string_list


# Java's three conventional test-filename suffixes (Maven Surefire / Failsafe +
# Spring Boot): ``<Class>Test.java`` (JUnit default), ``<Class>Tests.java``
# (Spring's preferred form), ``<Class>IT.java`` (integration tests).
_JAVA_TEST_SUFFIXES: tuple[str, ...] = ("Test", "Tests", "IT")


def _path_components_contain(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Return True if *needle* appears as a contiguous subsequence in *haystack*.

    Used to recognise test-dir membership for multi-component
    (``"tests/unit"``) and absolute (``"/abs/path/tests"``) ``test_dirs``
    entries. ``Path(td).parts`` produces a tuple per component, and matching
    the whole tuple as a contiguous slice of ``Path(filepath).parts`` correctly
    handles both single-component (``"tests"``) and nested (``"tests/unit"``)
    forms - a plain ``in path.parts`` membership check would only match the
    single-component case.
    """
    if not needle:
        return False
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def _filename_matches_test_pattern(filepath: str, lang_name: str) -> bool:
    """Return True if *filepath*'s bare filename matches a test-file naming convention.

    Per-language conventions:

    * JS / TS: ``.test.`` or ``.spec.`` infix (Jest / Mocha / Karma).
    * Java: stem ending in ``Test`` / ``Tests`` / ``IT``. The legacy
      ``Test<Name>.java`` prefix form is deliberately NOT recognised
      here because production utilities (``TestDataFactory``,
      ``TestConfig``) under ``src/main/java`` use the same prefix and
      would be wrongly classified as tests; legitimate JUnit 3
      ``Test``-prefix tests get picked up via the path-component check
      in :func:`_is_test_file` when they live in the configured test
      directory.
    * Rust: stem ending in ``_test`` (colocated convention). Bare
      ``<stem>.rs`` under ``tests/`` is handled by path-component
      matching at the call site, not here.
    * C: stem ending in ``_test`` or starting with ``test_`` (Unity /
      Check / CMocka both conventions).
    * Python (fallback): filename starting with ``test_``.
    """
    name = Path(filepath).name
    if lang_name in ("javascript", "typescript"):
        return ".test." in name or ".spec." in name
    if lang_name == "java":
        return any(Path(filepath).stem.endswith(suf) for suf in _JAVA_TEST_SUFFIXES)
    if lang_name in ("rust", "go"):
        # Rust: colocated ``<stem>_test.rs``. Go: sibling ``<stem>_test.go``.
        # Both mark the file itself as a test via the ``_test`` stem suffix.
        return Path(filepath).stem.endswith("_test")
    if lang_name == "php":
        # PHPUnit's ``<ClassName>Test.php`` (StudlyCaps suffix).
        return Path(filepath).stem.endswith("Test")
    if lang_name in ("c", "cpp"):
        # C (Unity / Check / CMocka) and C++ (GoogleTest / Catch2) share a
        # ``<stem>_test`` / ``test_<stem>`` convention. The match is on the stem
        # only, so it holds for any C / C++ extension (``.c`` / ``.cpp`` /
        # ``.cc`` / ``.cxx`` / ``.hpp`` / ...); recognise either form so a
        # canonical test is not treated as production code.
        stem = Path(filepath).stem
        return stem.endswith("_test") or stem.startswith("test_")
    return name.startswith("test_")


def _is_test_file(filepath: str, test_dirs: list[str], lang_name: str) -> bool:
    """Return True if *filepath* is itself a test file.

    Two checks, OR'd together:

    1. **Path-component match.** ``filepath`` lives under any configured
       ``test_dirs`` entry - covers test files even if their filenames don't
       follow the pattern convention (``conftest.py``, ``__init__.py``,
       fixtures, helpers). Handles multi-component entries (``"tests/unit"``)
       and absolute paths by matching each ``test_dirs`` entry's full
       ``Path.parts`` tuple as a contiguous subsequence.
    2. **Filename-pattern match.** Delegated to
       :func:`_filename_matches_test_pattern`.

    Purely lexical (``.absolute()``, never ``.resolve()``, so no symlink is
    followed and the filesystem is not probed).
    """
    # Normalise both sides to absolute paths before the parts comparison.
    # Without this, a relative ``filepath`` (``tests/conftest.js``) wouldn't
    # match against an absolute ``test_dirs`` entry (``/abs/project/tests``)
    # and helper files under the test root would be misclassified as source.
    # ``.absolute()`` (not ``.resolve()``) avoids following symlinks.
    path_parts = Path(filepath).absolute().parts
    for td in test_dirs:
        td_parts = Path(td).absolute().parts
        if _path_components_contain(path_parts, td_parts):
            return True
    return _filename_matches_test_pattern(filepath, lang_name)


#: Filename conventions that are unambiguous enough to EXCLUDE a file on, keyed
#: by language. Deliberately narrower than :func:`_filename_matches_test_pattern`,
#: which answers the opposite question.
#:
#: The difference is the ``test_`` *prefix*. For finding tests it is a fine
#: signal; for excluding production code it is not, because production modules
#: legitimately carry it - safelint's own ``src/safelint/rules/test_coverage.py``
#: is a rule implementation, and an earlier draft of this skipped five rules in
#: it (caught by safelint's own SAFE004 ``unused_suppression``, which noticed the
#: annotations inside had stopped suppressing anything). The helper's docstring
#: already records the same reasoning for Java, where ``TestDataFactory`` and
#: ``TestConfig`` under ``src/main/java`` are production utilities.
#:
#: What remains is infix and suffix forms that nothing but a test is called:
#: ``foo.test.ts`` / ``foo.spec.js``, Go's toolchain-enforced ``foo_test.go``,
#: ``FooTest.java`` / ``FooTests.java`` / ``FooIT.java``, ``FooTest.php``, and
#: the ``_test`` stem suffix in Rust / C / C++.
_UNAMBIGUOUS_TEST_INFIXES: tuple[str, ...] = (".test.", ".spec.")


def _filename_is_unambiguously_test(filepath: str, lang_name: str) -> bool:
    """Return True only for filename forms that production code does not use.

    See :data:`_UNAMBIGUOUS_TEST_INFIXES` for why this is stricter than
    :func:`_filename_matches_test_pattern`.
    """
    path = Path(filepath)
    if lang_name in ("javascript", "typescript"):
        return any(infix in path.name for infix in _UNAMBIGUOUS_TEST_INFIXES)
    if lang_name in ("java", "php"):
        return any(path.stem.endswith(suffix) for suffix in _JAVA_TEST_SUFFIXES if lang_name == "java" or suffix == "Test")
    # Go's toolchain compiles ``_test.go`` only under ``go test``; Rust / C / C++
    # use the same stem suffix by convention. The ``test_`` prefix is excluded.
    return path.stem.endswith("_test")


#: Config key shared by every rule that scopes out of test code, and its default.
#: On by default: the status quo is not a conservative setting but a loud one, and
#: the loudness is what hides the true positives (#198). A project that wants the
#: strict reading sets it to ``false``.
SKIP_TEST_CODE_KEY = "skip_test_code"

#: Default ``test_dirs``. Four names because ``tests`` alone would have missed
#: Express entirely, where the directory is ``test`` (singular) and holds 161 of
#: its 165 SAFE101 findings.
_DEFAULT_TEST_DIRS: list[str] = ["tests", "test", "__tests__", "spec"]


def skips_test_code(rule_config: dict[str, Any], filepath: str, lang_name: str) -> bool:
    """Return True when *filepath* is test code this rule is configured to skip.

    File-level only, deliberately. The measured noise in #198 is entirely in test
    files - a session opened in ``test_requests.py``, a ``print`` in
    ``test_render`` - and a whole-file answer also covers the fixtures, helpers and
    ``conftest.py`` that live there without following a naming convention.
    Matching individual ``test_``-prefixed *functions* instead would have skipped
    a production ``test_connection()`` helper, which is a real finding.

    ``test_dirs`` is the same key SAFE601 / SAFE701 / SAFE702 read, so a project
    that has already told safelint where its tests live does not say it twice.
    The filename half is **stricter** than theirs: see
    :func:`_filename_is_unambiguously_test`.
    """
    if not rule_config.get(SKIP_TEST_CODE_KEY, True):
        return False
    # Validated as a string list so a scalar typo (``test_dirs = "mytests"``)
    # fails loud rather than iterating characters - matching every other list key.
    test_dirs = _validated_string_list(rule_config.get("test_dirs", _DEFAULT_TEST_DIRS), "test_dirs")
    path_parts = Path(filepath).absolute().parts
    if any(_path_components_contain(path_parts, Path(td).absolute().parts) for td in test_dirs):
        return True
    return _filename_is_unambiguously_test(filepath, lang_name)
