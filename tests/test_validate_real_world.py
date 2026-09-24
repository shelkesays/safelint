"""Smoke test for scripts/validate_real_world.py, the real-world validation harness.

Runs the harness end-to-end against a tiny synthetic project using the safelint
that ``uv run`` puts on PATH. It does not assert on specific findings - those
belong to the rule suites - only that the harness produces both runs, filters
to the language, records provenance, and writes a summary someone can read.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys

import pytest


_HARNESS = Path(__file__).parent.parent / "scripts" / "validate_real_world.py"


def _safelint_on_path() -> Path:
    """The ``safelint`` entry point ``uv run`` puts on PATH, as a Path.

    ``shutil.which`` returns ``str | None``; the tests that call this are
    skipped when it is ``None``, but the type checker cannot see the skip, so
    narrow here rather than at each call site.
    """
    found = shutil.which("safelint")
    if found is None:
        pytest.skip("safelint entry point not on PATH")
    return Path(found)


def _load_harness():
    """Import the script as a module without it being a package."""
    spec = importlib.util.spec_from_file_location("validate_real_world", _HARNESS)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE executing: the script uses ``from __future__ import
    # annotations``, so ``dataclasses`` resolves its string annotations via
    # ``sys.modules[cls.__module__].__dict__`` and needs the entry to exist.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(shutil.which("safelint") is None, reason="safelint entry point not on PATH")
def test_harness_end_to_end(tmp_path: Path) -> None:
    """Both runs happen, only the target language is counted, and the summary is written."""
    project = tmp_path / "proj"
    project.mkdir()
    # One Python file that trips a default-on structural rule, and one JS file
    # that must be filtered OUT of a python run.
    (project / "deep.py").write_text("def f(a, b, c, d, e, f, g, h):\n    return a\n", encoding="utf-8")
    (project / "noise.js").write_text("function g(a, b, c, d, e, f, g, h) { return a; }\n", encoding="utf-8")
    out = tmp_path / "results"

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "smoke", out_dir=out)
    results = harness.validate(target)

    assert [r.mode for r in results] == ["all-rules", "defaults"]
    for r in results:
        assert r.files_checked == 2, "both files are scanned; filtering happens on results"
        assert all(v["filepath"].endswith(".py") for v in r.violations), "JS findings must be filtered out"
        assert r.wall_seconds > 0
    assert any(code.startswith("SAFE1") for code in results[1].counts), "defaults run should report the arity violation"

    summary = harness.write_outputs(target, "0.0.0-test", "abcdef0123456789", results)
    text = summary.read_text(encoding="utf-8")
    assert summary.name == "python-smoke-0.0.0-test-abcdef0.md"
    assert "## all-rules" in text
    assert "## defaults" in text
    assert "@ `abcdef0123456789`" in text, "project SHA is recorded for reproducibility"
    assert (out / ".raw" / "python-smoke-0.0.0-test-abcdef0-defaults.json").exists()


def test_config_generation_puts_preset_in_the_right_table() -> None:
    """A TypeScript preset is set via [javascript] runtime; pydantic is its own switch."""
    harness = _load_harness()
    target = harness.Target(Path("safelint"), "typescript", Path(), "x", preset="bun", pydantic=True)
    toml = harness.preset_toml(target)
    assert '[javascript]\nruntime = "bun"' in toml
    assert "[python]\npydantic = true" in toml


def test_rules_for_asks_the_binary_not_the_checkout() -> None:
    """The rule list comes from the binary under test, filtered by language."""
    harness = _load_harness()
    names = harness.rules_for(_safelint_on_path(), "go")
    assert "no_recursion" in names, "cross-language rule present"
    assert "bare_except" not in names, "SAFE201 is not registered for Go"
    assert sys.version_info >= (3, 11)
