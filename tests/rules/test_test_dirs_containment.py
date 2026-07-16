"""Containment of the ``test_dirs`` config value (security finding H3).

A relative ``test_dirs`` entry that climbs out of the project root via ``..``
must not let SAFE701 / SAFE702's ``rglob`` probe outside the tree. Absolute
entries remain honoured (a supported, explicit config choice). See
``_contained_test_dir`` in ``safelint.rules.test_coverage``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules.test_coverage import _contained_test_dir


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _fires_safe701(src: Path, test_dirs: list[str]) -> bool:
    """Return True if SAFE701 fires for *src* with the given ``test_dirs``."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"test_existence": {"enabled": True, "test_dirs": test_dirs}}}))
    return any(v.code == "SAFE701" for v in engine.check_file(str(src)).violations)


def test_relative_parent_escape_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``../outside`` test_dir must not find a matching test outside the project root."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "foo.py").write_text("x = 1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_foo.py").write_text("def test_f(): assert True\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    # The matching test exists at ../outside, but the escape is contained, so
    # SAFE701 still fires (no in-root test found).
    assert _fires_safe701(proj / "foo.py", ["../outside"])


def test_deep_relative_escape_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deeper ``../../...`` traversal is contained too."""
    proj = tmp_path / "a" / "b" / "proj"
    proj.mkdir(parents=True)
    (proj / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "test_foo.py").write_text("def test_f(): assert True\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    assert _fires_safe701(proj / "foo.py", ["../../../"])


def test_in_root_relative_test_dir_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A legitimate in-root relative ``tests`` dir is found (no false positive)."""
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    (proj / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "tests" / "test_foo.py").write_text("def test_f(): assert True\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    assert not _fires_safe701(proj / "foo.py", ["tests"])


def test_absolute_test_dir_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An absolute test_dir (explicit config) is honoured even when cwd differs."""
    proj = tmp_path / "proj"
    abs_tests = tmp_path / "elsewhere" / "tests"
    abs_tests.mkdir(parents=True)
    proj.mkdir()
    (proj / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (abs_tests / "test_foo.py").write_text("def test_f(): assert True\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    # Absolute path is honoured, the paired test is found -> SAFE701 stays clean.
    assert not _fires_safe701(proj / "foo.py", [str(abs_tests)])


def test_contained_test_dir_unit(tmp_path: Path) -> None:
    """``_contained_test_dir``: relative-in-root kept, relative-escape dropped, absolute kept."""
    root = tmp_path / "root"
    root.mkdir()
    assert _contained_test_dir("tests", root) == root / "tests"
    assert _contained_test_dir("sub/unit", root) == root / "sub" / "unit"
    assert _contained_test_dir("../escape", root) is None
    assert _contained_test_dir("../../etc", root) is None
    # An absolute entry is returned as-is (normalised), regardless of root.
    # Build from tmp_path so the path is absolute on every OS (a hard-coded
    # "/var/..." is relative on Windows and would skip the absolute branch there).
    external = tmp_path / "elsewhere" / "tests"
    assert _contained_test_dir(str(external), root) == external


def test_relative_symlinked_test_dir_escaping_root_is_blocked(tmp_path: Path) -> None:
    """A relative ``tests`` entry that is a symlink out of tree is rejected.

    Lexical ``..`` containment passes for a plain name like ``tests``; the real
    escape is a committed symlink whose target is outside the root. Without the
    real-path guard the downstream ``rglob`` would follow the link and probe
    ``/etc`` (or any victim dir). ``_contained_test_dir`` must return None so the
    rglob never runs against the link target.
    """
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "tests").symlink_to(outside, target_is_directory=True)
    assert _contained_test_dir("tests", root) is None


def test_symlink_loop_test_dir_is_dropped_not_crashed(tmp_path: Path) -> None:
    """A symlink loop makes ``resolve()`` raise; it must be caught and dropped.

    ``Path.resolve()`` raises ``RuntimeError`` on a cyclic symlink (and ``OSError``
    on an unreadable ancestor). The containment check must return None rather than
    crash the linter during discovery.
    """
    root = tmp_path / "root"
    root.mkdir()
    loop = root / "tests"
    loop.symlink_to(loop)  # self-referential -> RuntimeError on resolve()
    assert _contained_test_dir("tests", root) is None
