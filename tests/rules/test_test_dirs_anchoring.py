"""A relative ``test_dirs`` entry is anchored at the file's own project root.

The exclusion side (``skip_test_code``) already anchored this way; the inclusion
side absolutised the entry against the working directory, so
``safelint check /abs/project`` run from anywhere else matched nothing. Since
``test_functions_only`` became the default (#163) that does not merely mis-scope
the rule, it silently turns it off for every language with no marker route.

These tests deliberately never change the working directory: pytest runs from
the repository root, which is what makes the bug reproducible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules._test_files import _is_test_file


def _engine() -> SafetyEngine:
    """SafetyEngine with SAFE601 enabled and everything else at its default."""
    return SafetyEngine(deep_merge(DEFAULTS, {"rules": {"missing_assertions": {"enabled": True}}}))


def _project(tmp_path: Path, rel: str, src: str) -> Path:
    """Write *src* at *rel* inside a project rooted at ``tmp_path/project``.

    The ``safelint.toml`` is what makes the root discoverable: the anchor walks
    up from the file looking for a config, exactly as the cache-dir resolver
    does, and falls back to the working directory only when there is none.
    """
    root = tmp_path / "project"
    (root / "safelint.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "safelint.toml").write_text("", encoding="utf-8")
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    return path


def test_a_test_dir_below_the_project_root_is_found_from_another_cwd(tmp_path: Path) -> None:
    """``project/tests/helper.py`` is a test file although the cwd is elsewhere.

    ``helper.py`` matches no test-filename convention, so the ``test_dirs``
    membership is the only thing that can classify it.
    """
    sample = _project(tmp_path, "tests/helper.py", "def test_x():\n    do_thing()\n")
    assert _is_test_file(str(sample), ["tests"], "python")
    assert [v.message for v in _engine().check_file(str(sample)).violations if v.code == "SAFE601"] == ['Function "test_x" has no assertions']


def test_a_nested_test_dir_entry_still_matches(tmp_path: Path) -> None:
    """A multi-component entry (``tests/unit``) matches as a contiguous subsequence."""
    sample = _project(tmp_path, "tests/unit/helper.py", "def test_x():\n    do_thing()\n")
    assert _is_test_file(str(sample), ["tests/unit"], "python")


def test_a_test_dir_component_above_the_project_root_does_not_match(tmp_path: Path) -> None:
    """A clone living under ``~/tests/`` must not read as all test code.

    This is why the entry is anchored rather than matched anywhere in the path:
    the project is at ``tests/myproj``, and ``src/service.py`` inside it is
    production code whose ``test_connection`` helper is a real finding.
    """
    root = tmp_path / "tests" / "myproj"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "safelint.toml").write_text("", encoding="utf-8")
    sample = root / "src" / "service.py"
    sample.write_text("def test_connection():\n    connect()\n", encoding="utf-8")
    assert not _is_test_file(str(sample), ["tests"], "python")
    assert [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE601"] == []


def test_an_absolute_test_dirs_entry_still_matches_exactly(tmp_path: Path) -> None:
    """An absolute entry stays anchored to the path given, project root or not."""
    sample = _project(tmp_path, "mytests/helper.py", "def test_x():\n    do_thing()\n")
    assert _is_test_file(str(sample), [str(tmp_path / "project" / "mytests")], "python")
    assert not _is_test_file(str(sample), [str(tmp_path / "elsewhere")], "python")


def test_a_traversing_relative_entry_matches_nothing(tmp_path: Path) -> None:
    """``test_dirs = ["../../../"]`` must not classify the whole filesystem as tests.

    Security finding H3. A relative entry is matched against the components
    BELOW the project root, and those never contain ``..``, so a traversing
    entry has nothing to match.
    """
    sample = _project(tmp_path, "src/service.py", "def process(x):\n    return x\n")
    assert not _is_test_file(str(sample), ["../../../"], "python")
