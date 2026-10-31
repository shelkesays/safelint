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


def _origins(sample: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, wording)`` for each SAFE801 finding, in file order."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}}))
    found = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE801"]
    return [(v.lineno, _SOURCED if v.message.startswith(_SOURCED) else _PARAM) for v in found]


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


def test_overwriting_with_a_source_then_a_constant_clears_both(tmp_path: Path) -> None:
    """Assignment overwrites the origin along with the status.

    Without that, a variable that had once held a source would stay flagged as
    source-traced for the rest of the function even after being reassigned,
    which is the kind of stale claim this change exists to stop.
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
