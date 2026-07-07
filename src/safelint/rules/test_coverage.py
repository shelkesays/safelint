"""Test-coverage rules: test_existence and test_coupling (disabled by default)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from safelint.languages import JAVASCRIPT, TSX, TYPESCRIPT
from safelint.languages._node_utils import resolve_lang_name, walk
from safelint.rules._rust_test_attribute import attribute_is_test_marker
from safelint.rules.base import BaseRule


# Pre-sorted so ``_candidate_test_filenames`` produces a deterministic
# order for messages and tests; sourced from the registered
# ``LanguageDefinition``s so the test-file-pattern set stays in sync
# if the registered extensions ever change. JS and TS extensions are
# kept separate because a ``.ts`` source pairs with a ``.test.ts``
# (or ``.test.tsx`` / ``.test.as``) test, NOT a ``.test.js`` - keeping
# the language-family consistent across source and test is a
# convention every test runner expects.
_JS_EXTENSIONS: tuple[str, ...] = tuple(sorted(JAVASCRIPT.file_extensions))
_TS_EXTENSIONS: tuple[str, ...] = tuple(sorted(TYPESCRIPT.file_extensions | TSX.file_extensions))

# Java's three conventional test-filename suffixes. Maven and Gradle
# both expect a test class to live alongside the production class
# with one of these forms:
#
# * ``<ClassName>Test.java``  - JUnit unit tests (default for new code)
# * ``<ClassName>Tests.java`` - Spring's preferred form
#   (``@SpringBootTest`` examples in spring.io docs use this)
# * ``<ClassName>IT.java``    - Maven Surefire / Failsafe integration tests
#
# Plus the ``Test<ClassName>.java`` *prefix* form, which is older but
# still legal in JUnit. The candidate list yields all four so projects
# can mix conventions without false-positive misses.
_JAVA_TEST_SUFFIXES: tuple[str, ...] = ("Test", "Tests", "IT")

# Rust test-filename suffixes. Cargo's integration-test convention is
# ``tests/<stem>.rs`` (exact stem, no suffix); some projects also use a
# ``<stem>_test.rs`` suffix as a colocated convention. Both are listed
# as candidates so projects following either pattern get a match.
_RUST_TEST_SUFFIXES: tuple[str, ...] = ("", "_test")


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


def _candidate_test_filenames(src_path: Path, lang_name: str) -> list[str]:
    """Return the list of test filenames safelint will look for.

    Python: ``test_<stem>.py`` (single canonical pattern).

    JavaScript: ``<stem>.test.<ext>`` (Jest convention) and
    ``<stem>.spec.<ext>`` (Mocha / Karma convention) for each of the
    registered JS extensions (``.js`` / ``.mjs`` / ``.cjs``).

    TypeScript: same ``.test.<ext>`` / ``.spec.<ext>`` patterns but
    using the TS extension set (``.ts`` / ``.tsx`` / ``.as``). A
    ``foo.ts`` source pairs with ``foo.test.ts`` (or ``.tsx`` / ``.as``),
    NOT ``foo.test.js`` - language-family consistency between source
    and test is a convention every JS / TS test runner expects.

    Java: ``<ClassName>Test.java`` / ``<ClassName>Tests.java`` /
    ``<ClassName>IT.java`` (Maven Surefire / Failsafe + Spring Boot
    conventions), plus the legacy ``Test<ClassName>.java`` prefix form.
    Users following a different convention can override
    ``test_dirs`` and rely on test-discovery from a custom location
    (e.g. Kotlin / Groovy sources at ``src/test/groovy``); the
    candidate-list generation only owns the filename convention.
    """
    stem = src_path.stem
    if lang_name in ("javascript", "typescript"):
        # ``.test.<ext>`` / ``.spec.<ext>`` for the language-family's own
        # extension set (a ``.ts`` source pairs with ``.test.ts``, not
        # ``.test.js``).
        extensions = _JS_EXTENSIONS if lang_name == "javascript" else _TS_EXTENSIONS
        return [f"{stem}{infix}{ext}" for infix in (".test", ".spec") for ext in extensions]
    # Per-language filename conventions (single-return dispatch):
    # * java - Maven Surefire / Failsafe + Spring Boot suffixes plus the
    #   legacy ``Test<Class>`` prefix.
    # * rust - Cargo's ``<stem>.rs`` integration test (+ colocated suffix).
    # * go - sibling ``<stem>_test.go`` (same dir; ``test_dirs`` N/A, handled
    #   in ``_find_test_file``).
    # * php - PHPUnit's ``<Class>Test.php`` under ``test_dirs``.
    # * c - weak conventions (Unity / Check / CMocka): both ``<stem>_test.c``
    #   and ``test_<stem>.c``; C projects usually override ``test_dirs``.
    candidates_by_lang: dict[str, list[str]] = {
        "java": [f"{stem}{suf}.java" for suf in _JAVA_TEST_SUFFIXES] + [f"Test{stem}.java"],
        "rust": [f"{stem}{suf}.rs" for suf in _RUST_TEST_SUFFIXES],
        "go": [f"{stem}_test.go"],
        "php": [f"{stem}Test.php"],
        "c": [f"{stem}_test.c", f"test_{stem}.c"],
        # C++ sources use several extensions (``.cpp`` / ``.cc`` / ``.cxx``); a
        # ``foo.cc`` is conventionally paired with ``foo_test.cc``, so accept a
        # matching test file under any of them (GoogleTest / Catch2 conventions).
        "cpp": [f"{stem}_test.{ext}" for ext in ("cpp", "cc", "cxx")] + [f"test_{stem}.{ext}" for ext in ("cpp", "cc", "cxx")],
    }
    # Python (and any future language without an explicit override).
    return candidates_by_lang.get(lang_name, [f"test_{stem}.py"])


def _test_filename_for_message(src_path: Path, lang_name: str) -> str:
    """Pick the canonical test filename to surface in a violation message.

    The "expected" filename in messages is one example, not the full
    list (which would be unwieldy). For Python, the unique pattern;
    for JavaScript, the Jest-style ``foo.test.js`` form (the most
    common modern convention); for Java, the JUnit 5 default
    ``<ClassName>Test.java``.
    """
    stem = src_path.stem
    if lang_name in ("javascript", "typescript"):
        # Default to the Jest-style ``.test.<source-extension>`` form so the
        # suggestion matches the source file's own extension.
        return f"{stem}.test{src_path.suffix}"
    # Canonical example filename per language (rust: Cargo's ``<stem>.rs``
    # integration test; c: the ``<stem>_test.c`` form).
    message_name_by_lang: dict[str, str] = {
        "java": f"{stem}Test.java",
        "rust": f"{stem}.rs",
        "go": f"{stem}_test.go",
        "php": f"{stem}Test.php",
        "c": f"{stem}_test.c",
        "cpp": f"{stem}_test.cpp",
    }
    return message_name_by_lang.get(lang_name, f"test_{stem}.py")


def _find_test_file(src_path: Path, test_dirs: list[str], lang_name: str) -> bool:
    """Return True if any candidate test filename for *src_path* can be found.

    Go looks for the sibling ``<stem>_test.go`` in the source file's own
    directory (its convention has no ``tests/`` idiom); every other
    language searches under the configured ``test_dirs``.
    """
    candidates = _candidate_test_filenames(src_path, lang_name)
    if lang_name == "go":
        return any((src_path.parent / name).exists() for name in candidates)
    # Anchor every *relative* ``test_dirs`` entry inside the project root before
    # globbing: a crafted relative value (``"../../etc"``) would otherwise make
    # the ``rglob`` below walk outside the project, so relative entries that
    # escape the root are dropped (no paired test is found there). Absolute
    # entries (``"/etc"``) are honoured as-is by design - an explicit, supported
    # config choice, not an implicit traversal. See ``_contained_test_dir``.
    root = Path.cwd().resolve()
    contained = [d for d in (_contained_test_dir(td, root) for td in test_dirs) if d is not None]
    return any(_test_dir_contains(d, candidates) for d in contained)


def _contained_test_dir(test_dir: str, root: Path) -> Path | None:
    """Resolve a ``test_dirs`` entry, containing *relative* ones inside *root*.

    Closes the H3 finding's headline case: a **relative** ``test_dirs`` value
    that climbs out of the project root via ``..`` (``"../../etc"``) would let
    the filesystem ``rglob`` probe outside the tree. A relative entry is joined
    onto *root*, its ``..`` segments collapsed **lexically** (``os.path.normpath``
    - no filesystem access, so a non-existent or symlinked path neither raises
    nor is followed during this check), and dropped if the collapsed path
    escapes *root*. ``os.path.normpath`` is deliberate here (not the
    otherwise-preferred ``pathlib``): there is no pure-``Path`` lexical
    ``..``-collapse, and ``Path.resolve()`` would hit the filesystem and follow
    symlinks - exactly what this containment check must avoid. Do not swap it.

    An **absolute** entry is honoured as-is: it is an explicit, deliberate path
    named by the config author (and a supported feature - the test suite passes
    ``str(tmp_path / "tests")``), not an implicit traversal. *root* is the
    process cwd, which is the project root for a normal ``safelint`` run but not
    necessarily for an absolute entry pointing elsewhere, so containing absolute
    paths here would over-reject legitimate configs (the same over-rejection
    trap as H1). The residual absolute-path probe is near-zero risk - the rules
    are opt-in, the result is a single existence bit flipping a SAFE701/702
    violation in the user's own terminal, with no exfiltration channel.
    """
    p = Path(test_dir)
    if p.is_absolute():
        return Path(os.path.normpath(p))
    collapsed = Path(os.path.normpath(root / p))
    return collapsed if collapsed.is_relative_to(root) else None


def _path_components_contain(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Return True if *needle* appears as a contiguous subsequence in *haystack*.

    Used by :func:`_is_test_file` to recognise test-dir membership for
    multi-component (``"tests/unit"``) and absolute (``"/abs/path/tests"``)
    ``test_dirs`` entries. ``Path(td).parts`` produces a tuple per
    component, and matching the whole tuple as a contiguous slice of
    ``Path(filepath).parts`` correctly handles both single-component
    (``"tests"``) and nested (``"tests/unit"``) forms - a plain
    ``in path.parts`` membership check would only match the
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
        # C: Unity / Check / CMocka; C++: GoogleTest / Catch2 - both use ``<stem>_test.c`` and ``test_<stem>.c``;
        # recognise either so a canonical C test is not treated as production code.
        stem = Path(filepath).stem
        return stem.endswith("_test") or stem.startswith("test_")
    return name.startswith("test_")


def _is_test_file(filepath: str, test_dirs: list[str], lang_name: str) -> bool:
    """Return True if *filepath* is itself a test file (so SAFE701/702 should not run on it).

    Without this guard the test-coverage rules would treat a test file
    as a source file and look for *its* paired test (e.g. ``tests/foo.test.js``
    would search for ``foo.test.test.js``, ``tests/test_bar.py`` would
    search for ``test_test_bar.py``).

    Two checks, OR'd together:

    1. **Path-component match.** ``filepath`` lives under any
       configured ``test_dirs`` entry - covers test files even if
       their filenames don't follow the pattern convention
       (``conftest.py``, ``__init__.py``, fixtures, helpers).
       Handles multi-component entries (``"tests/unit"``) and
       absolute paths by matching each ``test_dirs`` entry's full
       ``Path.parts`` tuple as a contiguous subsequence.
    2. **Filename-pattern match.** Delegated to
       :func:`_filename_matches_test_pattern`.
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


def _rust_has_test_marker(tree: tree_sitter.Tree) -> bool:
    """Return True if *tree* contains ``#[test]`` or ``#[cfg(test)]``.

    Both attributes mean the file *is* a test (inline tests in a
    ``#[cfg(test)] mod tests { }`` block) or *defines* tests
    (``#[test] fn it_works()``), satisfying SAFE701 / SAFE702
    without a separate paired file. Rust's idiomatic unit-test
    placement is in-file, so the rule must recognise it - otherwise
    every Rust source with inline tests would still fire SAFE701
    asking for an external ``tests/<stem>.rs`` that doesn't exist.

    The per-attribute marker check is delegated to
    :func:`safelint.rules._rust_test_attribute.attribute_is_test_marker`
    so SAFE701 / SAFE702 / SAFE204 / SAFE208 share one definition.
    """
    return any(node.type == "attribute" and attribute_is_test_marker(node) for node in walk(tree.root_node))


def _paired_test_in_changed_under_test_dirs(src: Path, changed: set[str], test_dirs: list[str], lang_name: str) -> bool:
    """Return True if any candidate paired-test filename for *src* is in *changed* and under *test_dirs*.

    Restricts the candidate match to changed paths whose components
    include a configured ``test_dirs`` entry as a contiguous
    subsequence. A same-basename file changed outside the test root
    (e.g. ``legacy/test_foo.py`` or ``packages/foo/bar/foo.test.js``
    when ``test_dirs=["tests"]``) would otherwise satisfy the
    basename match and silently skip SAFE702 even though the paired
    test under ``tests/`` wasn't touched.

    Both sides are normalised via ``.absolute()`` before the parts
    comparison so a relative ``changed_files`` entry and an absolute
    ``test_dirs`` entry still match - mirrors :func:`_is_test_file`.
    """
    if lang_name == "go":
        # Go's paired test is a sibling in the SAME directory, so match the
        # exact ``<dir>/<stem>_test.go`` path in the changed set rather than
        # a basename-under-test_dirs match.
        targets = {(src.parent / name).absolute() for name in _candidate_test_filenames(src, lang_name)}
        return any(Path(f).absolute() in targets for f in changed)
    candidates = _candidate_test_filenames(src, lang_name)
    td_parts_list = [Path(td).absolute().parts for td in test_dirs]
    changed_under_test_dirs = {f for f in changed if any(_path_components_contain(Path(f).absolute().parts, td_parts) for td_parts in td_parts_list)}
    changed_basenames = {Path(f).name for f in changed_under_test_dirs}
    return any(candidate in changed_basenames for candidate in candidates)


def _test_dir_contains(test_dir: Path, candidates: list[str]) -> bool:
    """Return True if any candidate filename exists anywhere under *test_dir*.

    Short-circuits at the first match for both the candidate loop and
    each candidate's ``rglob``: ``next(iter(...), None)`` stops the
    rglob walk as soon as it yields one path, and the outer ``any``
    stops as soon as any candidate finds something. On a large repo
    this avoids a full materialised file listing per source file.
    """
    return any(next(iter(test_dir.rglob(name)), None) is not None for name in candidates)


class TestExistenceRule(BaseRule):
    """Verify that a corresponding test file exists for every checked module."""

    name = "test_existence"
    code = "SAFE701"
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c", "cpp")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Return a violation when no matching test file can be found.

        Filename pattern is language-aware - see :func:`_candidate_test_filenames`.
        Skips test files themselves (see :func:`_is_test_file`) so we
        don't ask a test to have its own test. For Rust, additionally
        skips files that carry inline tests (``#[test]`` /
        ``#[cfg(test)]``) - that's the idiomatic Rust placement and
        the rule must not demand an external test file alongside it.
        """
        lang_name = resolve_lang_name(filepath)
        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
        if _is_test_file(filepath, test_dirs, lang_name):
            return []
        if lang_name == "rust" and _rust_has_test_marker(tree):
            return []
        src = Path(filepath)
        if _find_test_file(src, test_dirs, lang_name):
            return []
        expected = _test_filename_for_message(src, lang_name)
        location = "alongside it" if lang_name == "go" else f"under {', '.join(test_dirs)}/"
        return [
            self._make_violation(
                filepath,
                0,
                f"No test file found for {src.name} - expected {expected} {location}",
            )
        ]


class TestCouplingRule(BaseRule):
    """Require that when a src file changes, its test file also changes.

    Unlike ``test_existence``, this rule checks coupling: if you touched the
    source you must touch the tests. The engine injects ``_changed_files``
    (the full list of files being checked) into the rule config before running.

    Filename pattern is language-aware - Python source pairs with
    ``test_<stem>.py``; JavaScript source pairs with any of
    ``<stem>.test.{js,mjs,cjs}`` / ``<stem>.spec.{js,mjs,cjs}``.
    """

    name = "test_coupling"
    code = "SAFE702"
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c", "cpp")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Return a violation when the paired test file was not part of this commit."""
        # No coupling context means we are not in a diff-aware run (e.g. --all-files).
        # Firing on every file would be noise, so skip entirely.
        if "_changed_files" not in self.config:
            return []

        lang_name = resolve_lang_name(filepath)

        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
        # A test file isn't a source file with a paired test - skip
        # the coupling check rather than asking the test file's own
        # test to also change.
        if _is_test_file(filepath, test_dirs, lang_name):
            return []
        # Rust files with inline tests are themselves the test file -
        # if the source changed, the inline tests in the same file
        # were necessarily reachable for editing in the same commit,
        # so the coupling guarantee is satisfied by definition.
        if lang_name == "rust" and _rust_has_test_marker(tree):
            return []
        changed: set[str] = set(self.config["_changed_files"])
        src = Path(filepath)

        # If no test file exists at all, defer to test_existence.
        if not _find_test_file(src, test_dirs, lang_name):
            return []

        if _paired_test_in_changed_under_test_dirs(src, changed, test_dirs, lang_name):
            return []

        expected = _test_filename_for_message(src, lang_name)
        location = "in the same directory" if lang_name == "go" else f"under {', '.join(test_dirs)}/"
        return [
            self._make_violation(
                filepath,
                0,
                f"{src.name} changed but {expected} was not updated - tests must be updated alongside source changes ({location})",
            )
        ]
