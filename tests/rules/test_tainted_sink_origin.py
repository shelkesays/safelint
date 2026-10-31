"""SAFE801 words a hit by the ORIGIN of its taint (#158 item 3).

Every tracker seeds taint from two places that are not equally good evidence.
A recognised **source** (``$_GET['q']``, ``input()``, ``os.Getenv``) means
untrusted data is genuinely in play. A function **parameter** does not: seeding
parameters is what makes an intra-procedural analysis useful, but it means any
helper taking an argument and calling a dangerous builtin reports whether or
not a request can reach it.

Against FreeScout, **0 of 10** SAFE801 findings had a traced source, yet every
message read ``Tainted variable "$mailbox" flows into dangerous sink`` - which
states a fact the analysis does not have. Both kinds still report; only the
wording differs, because only one of them is a claim about attacker input.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


_SOURCED = "Tainted variable"
_PARAM = "Parameter-derived value"


def _wording(message: str) -> str:
    """Return which of the two SAFE801 wordings *message* uses.

    Raises rather than defaulting. Classifying "anything that is not the
    source wording" as the parameter wording would let a malformed or
    unrelated message pass every case below as though it were the expected
    one, which is the opposite of what these tests are for.
    """
    for wording in (_SOURCED, _PARAM):
        if message.startswith(wording):
            return wording
    pytest.fail(f"SAFE801 message matches neither wording: {message!r}")


def _origins(sample: Path, overrides: dict | None = None) -> list[tuple[int, str]]:
    """Return ``(lineno, wording)`` for each SAFE801 finding, in file order."""
    rule: dict[str, object] = {"enabled": True}
    rule.update(overrides or {})
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule}}))
    found = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE801"]
    return [(v.lineno, _wording(v.message)) for v in found]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


# (label, filename, source, expected [(lineno, wording)])
_CASES: list[tuple[str, str, str, list[tuple[int, str]]]] = [
    (
        "python: a parameter is not a traced source",
        "p.py",
        """\
        import subprocess

        def run(cmd):
            subprocess.run(cmd)
        """,
        [(4, _PARAM)],
    ),
    (
        "python: input() is",
        "p.py",
        """\
        import subprocess

        def run():
            cmd = input("cmd: ")
            subprocess.run(cmd)
        """,
        [(5, _SOURCED)],
    ),
    (
        "python: taint derived from a parameter stays parameter-derived",
        "p.py",
        """\
        import subprocess

        def run(cmd):
            built = "sh -c " + cmd
            subprocess.run(built)
        """,
        [(5, _PARAM)],
    ),
    (
        "python: a parameter mixed with a source is sourced",
        "p.py",
        """\
        import subprocess

        def run(prefix):
            cmd = prefix + input("rest: ")
            subprocess.run(cmd)
        """,
        [(5, _SOURCED)],
    ),
    (
        "php: the FreeScout wrapper shape",
        "p.php",
        """\
        <?php
        function runCommand($command) {
            shell_exec($command);
        }
        """,
        [(3, _PARAM)],
    ),
    (
        "php: a superglobal is a traced source",
        "p.php",
        """\
        <?php
        function run() {
            $cmd = $_GET['c'];
            shell_exec($cmd);
        }
        """,
        [(4, _SOURCED)],
    ),
    (
        "php: a parameter reassigned from a superglobal becomes sourced",
        "p.php",
        """\
        <?php
        function run($cmd) {
            $cmd = $_POST['c'];
            shell_exec($cmd);
        }
        """,
        [(4, _SOURCED)],
    ),
    (
        "javascript: parameter versus a prompt source",
        "p.js",
        """\
        function fromParam(code) {
          eval(code);
        }
        function fromSource() {
          const code = prompt("code?");
          eval(code);
        }
        """,
        [(2, _PARAM), (6, _SOURCED)],
    ),
]


@pytest.mark.parametrize(["label", "name", "source", "expected"], _CASES, ids=[case[0] for case in _CASES])
def test_the_wording_follows_the_origin(tmp_path: Path, label: str, name: str, source: str, expected: list[tuple[int, str]]) -> None:
    """Each shape reports, worded by whether a real source was traced."""
    assert _origins(_write(tmp_path, name, source)) == expected, label


def test_reassigning_a_source_to_a_parameter_downgrades_the_wording(tmp_path: Path) -> None:
    """Assignment overwrites the origin along with the status.

    Without that, a variable that had once held a source would stay flagged as
    source-traced for the rest of the function even after being reassigned,
    which is the kind of stale claim this change exists to stop. The sink still
    reports, because ``arg`` is a seeded parameter; only the claim weakens.
    """
    sample = _write(
        tmp_path,
        "p.py",
        """\
        import subprocess

        def run(arg):
            cmd = input("cmd: ")
            cmd = arg
            subprocess.run(cmd)
        """,
    )
    assert _origins(sample) == [(6, _PARAM)]


def test_reassigning_a_source_to_a_constant_clears_the_finding(tmp_path: Path) -> None:
    """The companion: overwriting with a literal drops the taint, not just its origin.

    Distinct from the test above, where the new value is itself tainted. Here
    nothing is left to report at all, which is what pins that ``record_state``
    clears the status as well as the origin rather than leaving a stale entry.
    """
    sample = _write(
        tmp_path,
        "p.py",
        """\
        import subprocess

        def run():
            cmd = input("cmd: ")
            cmd = "ls -la"
            subprocess.run(cmd)
        """,
    )
    assert _origins(sample) == []


def test_a_go_closure_capture_keeps_its_origin(tmp_path: Path) -> None:
    """A captured local carries the origin of the scope it came from.

    Go, Java and Rust analyse closures in a second pass seeded with the
    enclosing scope's finished taint. Seeding the status without the origin
    would word a genuinely traced source as merely parameter-derived.
    """
    sample = _write(
        tmp_path,
        "p.go",
        """\
        package main

        import (
            "os"
            "os/exec"
        )

        func sourced(run func(func())) {
            p := os.Getenv("CMD")
            run(func() { exec.Command(p) })
        }

        func fromParam(p string, run func(func())) {
            run(func() { exec.Command(p) })
        }
        """,
    )
    assert _origins(sample) == [(10, _SOURCED), (14, _PARAM)]


# The property-typed sanitiser contract and the origin question have to agree
# on WHICH sink is being asked about, or a source the sink's own sanitiser
# already cleared still counts as traced.
_PROPERTY_CONFIG: dict[str, object] = {
    "sinks": ["htmlsink"],
    "sanitizers": [],
    "sources": ["input"],
    "sanitizer_properties": {"esc": ["html_escaped"], "urlenc": ["url_encoded"]},
    "sink_properties": {"htmlsink": "html_escaped"},
}

_PROPERTY_CASES: list[tuple[str, str, str]] = [
    ("source cleared for this sink's property", "htmlsink(esc(src) + param)", _PARAM),
    ("source not sanitised at all", "htmlsink(src + param)", _SOURCED),
    ("source sanitised for a DIFFERENT property", "htmlsink(urlenc(src) + param)", _SOURCED),
]


@pytest.mark.parametrize(["label", "expression", "expected"], _PROPERTY_CASES, ids=[case[0] for case in _PROPERTY_CASES])
def test_the_origin_question_respects_the_sinks_required_property(tmp_path: Path, label: str, expression: str, expected: str) -> None:
    """A source this sink's own sanitiser cleared is not evidence for this hit.

    Each of these fires only because ``param`` is a seeded parameter, so the
    question is whether the source in the same expression counts as traced.
    It does when it reaches the sink unsanitised, and when it was sanitised for
    some OTHER property - but not when the sink's own required property was
    established, because then the source is not what makes this a finding.

    Asking the origin question without the sink's property got the first row
    wrong, claiming a traced source for a hit caused entirely by the parameter.
    """
    sample = _write(tmp_path, "prop.py", f'def f(param):\n    src = input("x")\n    {expression}\n')
    assert _origins(sample, _PROPERTY_CONFIG) == [(3, expected)], label
