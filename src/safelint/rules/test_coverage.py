"""Test-coverage rules: test_existence and test_coupling (disabled by default)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from safelint.languages._node_utils import resolve_lang_name
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


def _candidate_test_filenames(src_path: Path, lang_name: str) -> list[str]:
    """Return the list of test filenames safelint will look for.

    Python: ``test_<stem>.py`` (single canonical pattern).

    JavaScript: ``<stem>.test.<ext>`` (Jest convention) and
    ``<stem>.spec.<ext>`` (Mocha / Karma convention) for each of the
    registered JS extensions (``.js``, ``.mjs``, ``.cjs``). A source
    ``foo.js`` matches if any of ``foo.test.js`` / ``foo.test.mjs`` /
    ``foo.test.cjs`` / ``foo.spec.js`` / ``foo.spec.mjs`` /
    ``foo.spec.cjs`` exists under the configured ``test_dirs``.
    """
    if lang_name == "javascript":
        stem = src_path.stem
        extensions = (".js", ".mjs", ".cjs")
        infixes = (".test", ".spec")
        return [f"{stem}{infix}{ext}" for infix in infixes for ext in extensions]
    # Python (and any future language without an explicit override).
    return [f"test_{src_path.stem}.py"]


def _test_filename_for_message(src_path: Path, lang_name: str) -> str:
    """Pick the canonical test filename to surface in a violation message.

    The "expected" filename in messages is one example, not the full
    list (which would be unwieldy). For Python, the unique pattern;
    for JavaScript, the Jest-style ``foo.test.js`` form (the most
    common modern convention).
    """
    if lang_name == "javascript":
        # Default to the Jest-style ``.test.<source-extension>`` form so the
        # suggestion matches the source file's own extension.
        return f"{src_path.stem}.test{src_path.suffix}"
    return f"test_{src_path.stem}.py"


def _find_test_file(src_path: Path, test_dirs: list[str], lang_name: str) -> bool:
    """Return True if any candidate test filename for *src_path* exists under *test_dirs*."""
    candidates = _candidate_test_filenames(src_path, lang_name)
    return any(_test_dir_contains(Path(d), candidates) for d in test_dirs)


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
    language = ("python", "javascript")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:  # noqa: ARG002
        """Return a violation when no matching test file can be found.

        Filename pattern is language-aware — see :func:`_candidate_test_filenames`.
        """
        lang_name = resolve_lang_name(filepath)
        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
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

    Filename pattern is language-aware — Python source pairs with
    ``test_<stem>.py``; JavaScript source pairs with any of
    ``<stem>.test.{js,mjs,cjs}`` / ``<stem>.spec.{js,mjs,cjs}``.
    """

    name = "test_coupling"
    code = "SAFE702"
    language = ("python", "javascript")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:  # noqa: ARG002
        """Return a violation when the paired test file was not part of this commit."""
        # No coupling context means we are not in a diff-aware run (e.g. --all-files).
        # Firing on every file would be noise, so skip entirely.
        if "_changed_files" not in self.config:
            return []

        lang_name = resolve_lang_name(filepath)

        test_dirs: list[str] = self.config.get("test_dirs", ["tests"])
        changed: set[str] = set(self.config["_changed_files"])
        src = Path(filepath)

        # If no test file exists at all, defer to test_existence.
        if not _find_test_file(src, test_dirs, lang_name):
            return []

        # Was *any* of the candidate test filenames in the changed set?
        # Compare against the basename of each changed path — a substring
        # match (``candidate in f``) would falsely treat ``foo.test.js`` as
        # paired with ``barfoo.test.js`` (or with a directory named
        # ``foo.test.js/`` further up the tree). ``Path(f).name`` extracts
        # the final path component regardless of separator normalisation.
        candidates = _candidate_test_filenames(src, lang_name)
        changed_basenames = {Path(f).name for f in changed}
        if any(candidate in changed_basenames for candidate in candidates):
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
