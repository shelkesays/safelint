"""Tests for ``return_value_ignored`` (SAFE802).

Covers the Python default set after #156 trimmed it twice: the six
``os``/``pathlib`` functions that return ``None`` (or, for ``Path.rename``, an
unactionable ``Path``), and the three whose return value idiomatic Python
discards (``write``, ``seek``, ``truncate``). ``subprocess.run`` and the socket
``send`` family still fire.

The ``os``-name cases and the engine helpers here are @Jah-yee's work from PR
#227, kept as written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation


def _engine() -> SafetyEngine:
    config = deep_merge(
        DEFAULTS,
        {"rules": {"return_value_ignored": {"enabled": True}}},
    )
    return SafetyEngine(config)


def _safe802(result: LintResult) -> list[Violation]:
    return [v for v in result.violations if v.code == "SAFE802"]


# ---------------------------------------------------------------------------
# Python defaults
# ---------------------------------------------------------------------------


def test_python_defaults_exclude_six_none_returning_names() -> None:
    """The six ``os``/``pathlib`` names that return ``None`` are absent from the Python defaults."""
    flagged = DEFAULTS["rules"]["return_value_ignored"]["flagged_calls"]
    excluded = {"remove", "unlink", "rename", "makedirs", "mkdir", "rmdir"}
    leaked = excluded & set(flagged)
    assert not leaked, f"names still in Python defaults: {leaked}"


def test_python_defaults_exclude_the_discarded_value_names() -> None:
    """``write`` / ``seek`` / ``truncate`` return a count or position nobody reads."""
    flagged = DEFAULTS["rules"]["return_value_ignored"]["flagged_calls"]
    leaked = {"write", "seek", "truncate"} & set(flagged)
    assert not leaked, f"names still in Python defaults: {leaked}"


def test_python_defaults_keep_the_names_that_carry_a_signal() -> None:
    """``run`` / ``call`` / ``check_output`` / the ``send`` family / ``replace`` remain."""
    flagged = set(DEFAULTS["rules"]["return_value_ignored"]["flagged_calls"])
    assert {"run", "call", "check_output", "send", "sendall", "sendfile", "replace"} <= flagged


def test_the_c_defaults_are_untouched() -> None:
    """``flagged_calls_c`` keeps the POSIX names: there, the return code is the point."""
    flagged_c = set(DEFAULTS["rules"]["return_value_ignored"]["flagged_calls_c"])
    assert {"remove", "rename", "fclose", "fwrite"} <= flagged_c


def test_subprocess_run_still_fires(tmp_path: Path) -> None:
    """``subprocess.run(...)`` with discarded return value fires SAFE802."""
    sample = tmp_path / "sub.py"
    sample.write_text('import subprocess\nsubprocess.run(["echo", "hi"])\n', encoding="utf-8")
    hits = _safe802(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "run" in hits[0].message


def test_socket_send_still_fires(tmp_path: Path) -> None:
    """``sock.send(...)`` still fires: a short send is a real bug.

    This is why ``sendall`` exists, and it is the reason the socket family stayed
    on the list while ``write`` / ``seek`` / ``truncate`` left it.
    """
    sample = tmp_path / "sock.py"
    sample.write_text('import socket\ns = socket.socket()\ns.send(b"hello")\n', encoding="utf-8")
    hits = _safe802(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "send" in hits[0].message


# ---------------------------------------------------------------------------
# Excluded names must NOT fire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ["name", "snippet"],
    (
        ["remove", 'import os\nos.remove("/tmp/foo")\n'],
        ["unlink", 'import os\nos.unlink("/tmp/foo")\n'],
        ["rename", 'import os\nos.rename("/tmp/a", "/tmp/b")\n'],
        ["makedirs", 'import os\nos.makedirs("/tmp/foo")\n'],
        ["mkdir", 'import os\nos.mkdir("/tmp/foo")\n'],
        ["rmdir", 'import os\nos.rmdir("/tmp/foo")\n'],
    ),
)
def test_excluded_os_names_do_not_fire(tmp_path: Path, name: str, snippet: str) -> None:
    """Each of the six excluded ``os`` functions produces zero SAFE802 findings."""
    sample = tmp_path / f"{name}.py"
    sample.write_text(snippet, encoding="utf-8")
    hits = _safe802(_engine().check_file(str(sample)))
    assert hits == [], f"{name}() should not fire SAFE802, got {len(hits)} hits"


def test_path_rename_does_not_fire(tmp_path: Path) -> None:
    """``Path.rename()`` is excluded from the Python defaults (returns an unactionable Path)."""
    sample = tmp_path / "pathrename.py"
    sample.write_text(
        'from pathlib import Path\np = Path("/tmp/a")\np.rename("/tmp/b")\n',
        encoding="utf-8",
    )
    hits = _safe802(_engine().check_file(str(sample)))
    assert hits == [], f"Path.rename() should not fire SAFE802, got {len(hits)} hits"


_DISCARDED_VALUE_NAMES = [
    ["write", 'f = open("/tmp/foo", "w")\nf.write("hello")\n'],
    ["seek", 'f = open("/tmp/foo")\nf.seek(0)\n'],
    ["truncate", 'f = open("/tmp/foo", "w")\nf.truncate(0)\n'],
]


@pytest.mark.parametrize(["name", "snippet"], tuple(_DISCARDED_VALUE_NAMES), ids=[case[0] for case in _DISCARDED_VALUE_NAMES])
def test_discarded_value_names_do_not_fire(tmp_path: Path, name: str, snippet: str) -> None:
    """Discarding a byte count, a file position or a truncate result is idiomatic.

    On Django these three were 404 of the 614 findings left after the six
    ``None``-returning names went, so they were the larger half of #156 rather
    than a tidy-up after it.
    """
    sample = tmp_path / f"{name}.py"
    sample.write_text(snippet, encoding="utf-8")
    assert _safe802(_engine().check_file(str(sample))) == [], name


def test_the_removed_names_are_still_reachable_by_config(tmp_path: Path) -> None:
    """They are defaults, not hard-coded: listing one restores the old behaviour."""
    sample = tmp_path / "cfg.py"
    sample.write_text('import os\nos.remove("/tmp/foo")\n', encoding="utf-8")
    config = deep_merge(DEFAULTS, {"rules": {"return_value_ignored": {"enabled": True, "flagged_calls": ["remove"]}}})
    hits = [v for v in SafetyEngine(config).check_file(str(sample)).violations if v.code == "SAFE802"]
    assert len(hits) == 1
