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

from safelint.core._validators import ConfigValueError
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import get_language_for_file
from safelint.rules.dataflow import NullDereferenceRule, ReturnValueIgnoredRule


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
    """The kept set is exactly these six.

    ``sendall`` is deliberately absent: it returns ``None``, so it fails the same
    test that removed the other six. Asserted as equality rather than a subset so
    a name cannot be added back without a decision.
    """
    flagged = set(DEFAULTS["rules"]["return_value_ignored"]["flagged_calls"])
    assert flagged == {"run", "call", "check_output", "send", "sendfile", "replace"}


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
    ids=["remove", "unlink", "rename", "makedirs", "mkdir", "rmdir"],
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


# ids is NOT redundant here: with more than one parameter pytest joins them
# all into the id, which embeds the whole snippet. Naming them keeps the ids
# readable.
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


# ---------------------------------------------------------------------------
# The default lists now have a single owner, so a partial config behaves like
# the shipped one in every language.
# ---------------------------------------------------------------------------


def test_a_partial_config_does_not_flag_the_removed_names(parse_python) -> None:
    """A config that enables the rule but omits ``flagged_calls`` uses the trimmed list.

    The rule classes used to carry ``ClassVar`` copies of their ``DEFAULTS``
    entries. ``flagged_calls`` kept the pre-#156 sixteen names, so this path still
    flagged ``os.remove`` and ``f.write``; the copies are gone and the fallback is
    read from ``DEFAULTS``.
    """
    source = 'import os\nos.remove("/tmp/x")\nf = open("/tmp/x", "w")\nf.write("hi")\n'
    rule = ReturnValueIgnoredRule({"enabled": True})
    assert rule.check_file("partial.py", parse_python(source)) == []


def test_a_partial_config_still_flags_the_kept_names(parse_python) -> None:
    """The control: the fallback is the trimmed list, not an empty one."""
    rule = ReturnValueIgnoredRule({"enabled": True})
    assert len(rule.check_file("keep.py", parse_python('import subprocess\nsubprocess.run(["echo"])\n'))) == 1


def test_a_partial_config_uses_the_defaults_for_non_python_languages(tmp_path: Path) -> None:
    """Every language gets its documented default, not just Python.

    The fallback was Python-only, so a library caller linting Rust, Go, Java, PHP,
    C or C++ with a partial config fell through to ``[]`` and received a silent
    clean bill of health.
    """
    sample = tmp_path / "x.rs"
    sample.write_text('fn f(w: W) { w.write_all(b"x"); }\n', encoding="utf-8")
    language = get_language_for_file(str(sample))
    assert language is not None, "the rust grammar must be installed for this test"
    tree = language.create_parser().parse(sample.read_bytes())
    assert len(ReturnValueIgnoredRule({"enabled": True}).check_file(str(sample), tree)) == 1


def test_a_scalar_flagged_calls_raises_instead_of_matching_characters(parse_python) -> None:
    """``flagged_calls = "remove"`` must raise, not become a set of characters.

    Python was the one language whose list skipped ``_validated_string_list``, so
    the typo silently produced ``{'r','e','m','o','v'}`` - ``os.remove`` stopped
    firing and an unrelated ``r()`` started. The docs tell users to edit this very
    key, which is what made the gap worth closing rather than documenting.
    """
    rule = ReturnValueIgnoredRule({"enabled": True, "flagged_calls": "remove"})
    with pytest.raises(ConfigValueError, match="flagged_calls must be a list of strings"):
        rule.check_file("scalar.py", parse_python('import os\nos.remove("/tmp/x")\n'))


def test_sendall_is_not_flagged_but_send_is(parse_python) -> None:
    """``sendall`` returns ``None``; only ``send`` and ``sendfile`` return a count.

    It was kept on the trimmed list with the rationale that "a short send is a real
    bug, which is precisely why ``sendall`` exists" - which argues the opposite of
    its conclusion: ``sendall`` exists so that check is unnecessary. By the same
    returns-``None`` test used to remove the other six, it had to go too.
    """
    assert ReturnValueIgnoredRule({"enabled": True}).check_file("a.py", parse_python('s.sendall(b"x")\n')) == []
    assert len(ReturnValueIgnoredRule({"enabled": True}).check_file("b.py", parse_python('s.send(b"x")\n'))) == 1


def test_the_severity_fallback_is_the_rules_own_default() -> None:
    """A partial config must not promote a warning-severity rule to blocking.

    ``BaseRule.__init__`` defaulted to a blanket ``"error"``, which disagreed with
    every warning-severity rule, so a direct caller got findings marked blocking
    that the shipped config marks advisory.
    """
    assert ReturnValueIgnoredRule({"enabled": True}).severity == DEFAULTS["rules"]["return_value_ignored"]["severity"]


def test_nullable_methods_replaces_rather_than_unions(parse_python) -> None:
    """Setting ``nullable_methods`` must be able to NARROW SAFE803, as in every other language.

    The Python branch OR'd a ``ClassVar`` with the user's list, so narrowing was
    impossible: all nine built-ins fired whatever was configured. ``DEFAULTS`` also
    carried an empty list for this key while the docs documented the nine, so the
    two halves disagreed about what the default even was.
    """
    source = 'def f(c):\n    c.get("k").strip()\n    c.pop("k").strip()\n'
    both = NullDereferenceRule({"enabled": True})
    narrowed = NullDereferenceRule({"enabled": True, "nullable_methods": ["get"]})
    assert len(both.check_file("n.py", parse_python(source))) == 2
    assert len(narrowed.check_file("n.py", parse_python(source))) == 1


def test_nullable_methods_default_matches_its_documentation() -> None:
    """``DEFAULTS`` carries the nine names the docs have always listed."""
    assert DEFAULTS["rules"]["null_dereference"]["nullable_methods"] == [
        "get",
        "pop",
        "find",
        "next",
        "first",
        "one_or_none",
        "scalar",
        "scalar_one_or_none",
        "fetchone",
    ]
