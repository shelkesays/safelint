"""The ``skip_test_code`` scoping shared by SAFE101/203/302/304/401 (#198).

Five default-on rules put the overwhelming majority of their findings in test
files - SAFE401 was 78% in Python and 93% in JS/TS, SAFE302 95% in JS/TS - where
the pattern is conventional and the volume buries the findings in library code.
They now skip test code by default, which is what safelint already did to its own
test tree through per-file-ignores.

The scoping is deliberately **narrower** than the test-file detection SAFE601 /
SAFE701 / SAFE702 use, because excluding production code is a different risk from
finding tests; see ``_filename_is_unambiguously_test``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.rules._test_files import skips_test_code


#: The five rules #198 covers, with the code each emits.
_SCOPED_RULES: list[tuple[str, str]] = [
    ("function_length", "SAFE101"),
    ("logging_on_error", "SAFE203"),
    ("global_mutation", "SAFE302"),
    ("side_effects", "SAFE304"),
    ("resource_lifecycle", "SAFE401"),
]

#: A Python module that trips SAFE101, SAFE203, SAFE304 and SAFE401 at once.
_NOISY_SOURCE = (
    "import requests\n"
    "\n"
    "def handle():\n"
    "    session = requests.Session()\n"
    "    print('working')\n" + "".join(f"    x{i} = {i}\n" for i in range(70)) + "    try:\n"
    "        session.get('http://x')\n"
    "    except ValueError:\n"
    "        cleanup()\n"
)


def _codes(sample: Path, *, skip: bool | None = None) -> set[str]:
    """Return the codes the five scoped rules fire on *sample*."""
    overrides: dict[str, dict[str, object]] = {}
    for rule, _ in _SCOPED_RULES:
        overrides[rule] = {"enabled": True} if skip is None else {"enabled": True, "skip_test_code": skip}
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": overrides}))
    wanted = {code for _, code in _SCOPED_RULES}
    return {v.code for v in engine.check_file(str(sample)).violations if v.code in wanted}


def test_the_same_source_reports_in_library_code_and_not_in_a_test_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical code, two locations: only the library copy reports.

    One assertion covering all five rules at once, because the point is the
    scoping rather than any individual rule's detection.
    """
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "lib.py"
    library.write_text(_NOISY_SOURCE, encoding="utf-8")
    test_copy = tmp_path / "tests" / "test_handle.py"
    test_copy.parent.mkdir()
    test_copy.write_text(_NOISY_SOURCE, encoding="utf-8")

    assert _codes(library) == {"SAFE101", "SAFE203", "SAFE304", "SAFE401"}
    assert _codes(test_copy) == set()


def test_skip_test_code_false_restores_the_previous_behaviour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The knob is the opt-out for projects that want the strict reading."""
    monkeypatch.chdir(tmp_path)
    test_copy = tmp_path / "tests" / "test_handle.py"
    test_copy.parent.mkdir()
    test_copy.write_text(_NOISY_SOURCE, encoding="utf-8")
    assert _codes(test_copy, skip=False) == {"SAFE101", "SAFE203", "SAFE304", "SAFE401"}


_TEST_DIR_NAMES = ["tests", "test", "__tests__", "spec"]


@pytest.mark.parametrize("directory", _TEST_DIR_NAMES)
def test_every_default_test_dir_name_is_recognised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: str) -> None:
    """``tests`` alone would have missed Express, whose directory is ``test``.

    161 of Express's 165 SAFE101 findings are in it, so a default needing
    per-project tuning to work is not the useful default #198 asked for.
    ``__tests__`` is Jest's convention and ``spec`` is Jasmine's.
    """
    monkeypatch.chdir(tmp_path)
    sample = tmp_path / directory / "sample.py"
    sample.parent.mkdir()
    sample.write_text(_NOISY_SOURCE, encoding="utf-8")
    assert _codes(sample) == set()


#: (path, language, expected skip). The production entries are the point: an
#: over-broad filename rule would silently drop five rules on real source files.
_FILENAME_CASES: list[tuple[str, str, bool]] = [
    # A ``test_`` PREFIX is not enough to exclude: production modules use it.
    # safelint's own rule implementation is the worked example.
    ("src/safelint/rules/test_coverage.py", "python", False),
    ("src/testing.py", "python", False),
    ("src/main/java/TestDataFactory.java", "java", False),
    ("src/main/java/TestConfig.java", "java", False),
    # Infix and suffix forms nothing but a test uses.
    ("lib/foo.test.js", "javascript", True),
    ("lib/foo.spec.ts", "typescript", True),
    ("internal/server_test.go", "go", True),
    ("src/lib_test.rs", "rust", True),
    ("src/test/java/FooTest.java", "java", True),
    ("app/FooTest.php", "php", True),
    # Plain production files in each.
    ("lib/foo.js", "javascript", False),
    ("internal/server.go", "go", False),
]


@pytest.mark.parametrize(["path", "lang_name", "expected"], _FILENAME_CASES, ids=[c[0] for c in _FILENAME_CASES])
def test_only_unambiguous_filename_conventions_exclude_a_file(path: str, lang_name: str, expected: bool) -> None:  # noqa: FBT001 - `expected` is parametrized test data, not a flag argument
    """Excluding production code is a different risk from finding tests.

    An earlier draft reused the SAFE601 / SAFE701 / SAFE702 detection wholesale,
    which recognises a ``test_`` prefix - and so skipped five rules inside
    safelint's own ``src/safelint/rules/test_coverage.py``. safelint's SAFE004
    ``unused_suppression`` caught it, by noticing that the ``# nosafe: SAFE203``
    annotations in that file had stopped suppressing anything.
    """
    assert skips_test_code({}, path, lang_name) is expected


def test_a_scalar_test_dirs_fails_loud() -> None:
    """A typo must not iterate characters and silently skip the whole project."""
    with pytest.raises(TypeError, match="test_dirs"):
        skips_test_code({"test_dirs": "mytests"}, "tests/x.py", "python")
