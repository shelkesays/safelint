"""Test-coverage rules: test_existence and test_coupling (disabled by default)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from safelint.languages import JAVASCRIPT, TSX, TYPESCRIPT
from safelint.languages._node_utils import node_text, resolve_lang_name, walk
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

#: Test-attribute names that mark a function as a test. Mirrors
#: :data:`safelint.rules.rust_rules._RUST_TEST_ATTRIBUTE_NAMES` -
#: keep the two in sync. ``"test"`` covers ``#[test]`` plus every
#: framework that suffixes ``::test`` (tokio / actix_web /
#: async_std / smol_potat / etc.); ``"rstest"`` covers the
#: parametric-test framework's bare ``#[rstest]`` and scoped
#: ``#[rstest::rstest]`` forms.
_RUST_TEST_ATTRIBUTE_NAMES: frozenset[str] = frozenset({"test", "rstest"})


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
    if lang_name == "javascript":
        stem = src_path.stem
        infixes = (".test", ".spec")
        return [f"{stem}{infix}{ext}" for infix in infixes for ext in _JS_EXTENSIONS]
    if lang_name == "typescript":
        stem = src_path.stem
        infixes = (".test", ".spec")
        return [f"{stem}{infix}{ext}" for infix in infixes for ext in _TS_EXTENSIONS]
    if lang_name == "java":
        stem = src_path.stem
        suffix_forms = [f"{stem}{suf}.java" for suf in _JAVA_TEST_SUFFIXES]
        prefix_form = [f"Test{stem}.java"]
        return [*suffix_forms, *prefix_form]
    if lang_name == "rust":
        stem = src_path.stem
        return [f"{stem}{suf}.rs" for suf in _RUST_TEST_SUFFIXES]
    # Python (and any future language without an explicit override).
    return [f"test_{src_path.stem}.py"]


def _test_filename_for_message(src_path: Path, lang_name: str) -> str:
    """Pick the canonical test filename to surface in a violation message.

    The "expected" filename in messages is one example, not the full
    list (which would be unwieldy). For Python, the unique pattern;
    for JavaScript, the Jest-style ``foo.test.js`` form (the most
    common modern convention); for Java, the JUnit 5 default
    ``<ClassName>Test.java``.
    """
    if lang_name in ("javascript", "typescript"):
        # Default to the Jest-style ``.test.<source-extension>`` form so the
        # suggestion matches the source file's own extension.
        return f"{src_path.stem}.test{src_path.suffix}"
    if lang_name == "java":
        return f"{src_path.stem}Test.java"
    if lang_name == "rust":
        # Cargo's integration-test convention - bare ``<stem>.rs`` under
        # ``tests/``. Inline ``#[cfg(test)] mod tests { }`` users won't
        # see this message since the rule's tree-walk bypass clears
        # the violation before the message is built.
        return f"{src_path.stem}.rs"
    return f"test_{src_path.stem}.py"


def _find_test_file(src_path: Path, test_dirs: list[str], lang_name: str) -> bool:
    """Return True if any candidate test filename for *src_path* exists under *test_dirs*."""
    candidates = _candidate_test_filenames(src_path, lang_name)
    return any(_test_dir_contains(Path(d), candidates) for d in test_dirs)


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
    * Python (fallback): filename starting with ``test_``.
    """
    name = Path(filepath).name
    if lang_name in ("javascript", "typescript"):
        return ".test." in name or ".spec." in name
    if lang_name == "java":
        return any(Path(filepath).stem.endswith(suf) for suf in _JAVA_TEST_SUFFIXES)
    if lang_name == "rust":
        return Path(filepath).stem.endswith("_test")
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


def _token_tree_mentions_test(token_tree: tree_sitter.Node) -> bool:
    """Return True if *token_tree* directly contains an ``identifier`` ``test``."""
    return any(inner.type == "identifier" and node_text(inner) == "test" for inner in token_tree.named_children)


def _cfg_token_tree_mentions_test(children: list[tree_sitter.Node]) -> bool:
    """Return True if any ``token_tree`` in *children* contains an ``identifier`` ``test``.

    Helper for :func:`_rust_has_test_marker`'s ``#[cfg(test)]`` branch.
    Split out so the marker walker stays under the cyclomatic /
    nesting limits SafeLint enforces on its own code.
    """
    return any(child.type == "token_tree" and _token_tree_mentions_test(child) for child in children)


def _attribute_is_rust_test_marker(node: tree_sitter.Node) -> bool:
    """Return True if *node* is a ``#[test]`` or ``#[cfg(test)]`` attribute.

    Also recognises scoped test-attribute paths whose trailing
    identifier is ``"test"`` - the convention every major async-test
    framework follows: ``#[tokio::test]``, ``#[actix_web::test]``,
    ``#[async_std::test]``, ``#[smol_potat::test]``, etc. Without
    this, files using those frameworks falsely fire SAFE701 /
    SAFE702 / SAFE204 / SAFE208 even though they ARE test files.
    """
    children = node.named_children
    if not children:  # pragma: no cover - tree-sitter-rust always emits a name child on an attribute
        return False
    first = children[0]
    if first.type == "scoped_identifier":
        # ``#[tokio::test]`` / ``#[rstest::rstest]`` - check the trailing identifier.
        trailing = first.child_by_field_name("name")
        return trailing is not None and node_text(trailing) in _RUST_TEST_ATTRIBUTE_NAMES
    if first.type != "identifier":  # pragma: no cover - defensive: rare attribute shapes (token_tree etc.)
        return False
    first_name = node_text(first)
    if first_name in _RUST_TEST_ATTRIBUTE_NAMES:
        return True
    if first_name != "cfg":
        return False
    return _cfg_token_tree_mentions_test(children[1:])


def _rust_has_test_marker(tree: tree_sitter.Tree) -> bool:
    """Return True if *tree* contains ``#[test]`` or ``#[cfg(test)]``.

    Both attributes mean the file *is* a test (inline tests in a
    ``#[cfg(test)] mod tests { }`` block) or *defines* tests
    (``#[test] fn it_works()``), satisfying SAFE701 / SAFE702
    without a separate paired file. Rust's idiomatic unit-test
    placement is in-file, so the rule must recognise it - otherwise
    every Rust source with inline tests would still fire SAFE701
    asking for an external ``tests/<stem>.rs`` that doesn't exist.

    tree-sitter-rust parses both forms as ``attribute`` nodes whose
    first named child is an ``identifier``; the per-node decision
    lives in :func:`_attribute_is_rust_test_marker`.
    """
    return any(node.type == "attribute" and _attribute_is_rust_test_marker(node) for node in walk(tree.root_node))


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
    language = ("python", "javascript", "typescript", "java", "rust")

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
        dirs = ", ".join(test_dirs)
        return [
            self._make_violation(
                filepath,
                0,
                f"No test file found for {src.name} - expected {expected} under {dirs}/",
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
    language = ("python", "javascript", "typescript", "java", "rust")

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
        dirs = ", ".join(test_dirs)
        return [
            self._make_violation(
                filepath,
                0,
                f"{src.name} changed but {expected} was not updated - tests must be updated alongside source changes (under {dirs}/)",
            )
        ]
