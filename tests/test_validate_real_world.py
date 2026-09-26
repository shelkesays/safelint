"""Smoke test for scripts/validate_real_world.py, the real-world validation harness.

Runs the harness end-to-end against a tiny synthetic project using the safelint
that ``uv run`` puts on PATH. It does not assert on specific findings - those
belong to the rule suites - only that the harness produces both runs, filters
to the language, records provenance, and writes a summary someone can read.
"""

from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path
import shutil
import sys
import tomllib

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
        assert r.files_with_findings <= 1, "only the .py file can carry findings after filtering"
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


def test_a_crashing_binary_is_an_error_not_a_clean_run(tmp_path: Path) -> None:
    """A run with no JSON report raises; it must never be recorded as zero findings."""
    fake = tmp_path / "safelint"
    fake.write_text("#!/bin/sh\necho 'Traceback (most recent call last):' >&2\necho 'OSError: boom' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")
    harness = _load_harness()
    target = harness.Target(fake, "python", project, "crash", out_dir=tmp_path / "out")
    with pytest.raises(harness.HarnessError, match="without a JSON report"):
        harness.run_safelint(target, tmp_path, "defaults")


def test_label_and_preset_reject_unsafe_values() -> None:
    """Path separators and quotes cannot reach a filename or the generated TOML."""
    harness = _load_harness()
    for bad in ("../escape", 'x"y', "a\nb", "", "spring boot"):
        with pytest.raises(harness.argparse.ArgumentTypeError):
            harness._identifier(bad)
    assert harness._identifier("spring-petclinic") == "spring-petclinic"
    assert harness._identifier("cloudflare-workers") == "cloudflare-workers"


def test_peak_rss_is_measured_per_run(tmp_path: Path) -> None:
    """Two runs report their own peak RSS, not the running maximum across both.

    ``RUSAGE_CHILDREN.ru_maxrss`` is the maximum over every child the process
    has reaped, so an in-process measurement makes the second run report the
    larger of the two. Sanity-check the wrapper reports a positive figure and
    an exit code, which the in-process version could not do.
    """
    harness = _load_harness()
    env = harness._measured([sys.executable, "-c", "import sys; print('{}'); sys.exit(3)"])
    assert env["rc"] == 3
    assert env["rss_mb"] > 0
    assert env["out"].strip() == "{}"


def test_include_narrows_results_to_a_subtree(tmp_path: Path) -> None:
    """`--include` keeps only findings under a subtree of a monorepo.

    The motivating case is astral-sh/ty, whose own repository is a docs stub -
    the type checker's source lives in `crates/ty_*` inside the Ruff monorepo,
    so it can only be validated as a subtree of that clone.
    """
    project = tmp_path / "mono"
    (project / "crates" / "ty_core").mkdir(parents=True)
    (project / "crates" / "linter").mkdir(parents=True)
    bad = "def f(a, b, c, d, e, f, g, h):\n    return a\n"
    (project / "crates" / "ty_core" / "a.py").write_text(bad, encoding="utf-8")
    (project / "crates" / "linter" / "b.py").write_text(bad, encoding="utf-8")

    harness = _load_harness()
    whole = harness.Target(_safelint_on_path(), "python", project, "mono", out_dir=tmp_path / "o1")
    subtree = harness.Target(_safelint_on_path(), "python", project, "ty", include="crates/ty_", out_dir=tmp_path / "o2")

    whole_files = {v["filepath"] for v in harness.validate(whole)[1].violations}
    # One validate() per target: each call runs safelint twice as subprocesses,
    # so reusing the result rather than re-deriving it matters for suite runtime.
    subtree_runs = harness.validate(subtree)
    subtree_defaults = subtree_runs[1]
    subtree_files = {v["filepath"] for v in subtree_defaults.violations}

    assert len(whole_files) == 2, "both crates report without --include"
    assert len(subtree_files) == 1, "--include keeps only the subtree"
    assert all("crates/ty_" in f for f in subtree_files)
    assert subtree_defaults.files_with_findings == 1

    summary = harness.write_outputs(subtree, "0.0.0-test", "abc1234567", subtree_runs)
    assert "subtree `crates/ty_`" in summary.read_text(encoding="utf-8"), "provenance records the subtree"


def test_include_is_anchored_at_a_path_boundary() -> None:
    """`--include` matches a subtree, not a raw substring.

    A raw `in` test would let `vendor/xcrates/ty_x` satisfy `crates/ty_`, and
    would miss Windows-style separators entirely. Prefix semantics *inside* the
    final segment are deliberate: `crates/ty_` has to match the sibling crates
    `ty_ide`, `ty_python_semantic` and the rest.
    """
    harness = _load_harness()
    under = harness._path_under

    assert under("/r/crates/ty_ide/a.rs", "crates/ty_")
    assert under("crates/ty_ide/a.rs", "crates/ty_"), "relative paths anchor at the start"
    assert under("C:\\r\\crates\\ty_ide\\a.rs", "crates/ty_"), "separators are normalised"
    assert under("/r/crates/ty_ide/a.rs", "crates/ty"), "prefix within the segment is intended"

    assert not under("/r/vendor/xcrates/ty_x/a.rs", "crates/ty_"), "must not match mid-segment"
    assert not under("/r/crates/typescript/a.rs", "crates/ty_"), "underscore boundary respected"
    assert not under("/r/crates/ty_ide/a.rs", ""), "an empty include matches nothing"


def test_python_preset_and_pydantic_share_one_table() -> None:
    """`--preset django --pydantic` must emit ONE [python] table, not two.

    TOML forbids declaring a table twice, so a header per key made the generated
    config unparseable and killed the run - and that combination is exactly what
    the Django / Flask / FastAPI rows of the validation matrix ask for.
    """
    harness = _load_harness()
    target = harness.Target(Path("safelint"), "python", Path(), "x", preset="django", pydantic=True)
    toml = harness.preset_toml(target)
    assert toml.count("[python]") == 1, toml
    assert tomllib.loads(toml) == {"python": {"framework": "django", "pydantic": True}}


def test_every_preset_combination_generates_valid_toml() -> None:
    """No combination of --preset / --pydantic may produce unparseable config."""
    harness = _load_harness()
    combinations = itertools.product(sorted(harness.EXTENSIONS), (None, "somepreset"), (False, True))
    for lang, preset, pydantic in combinations:
        target = harness.Target(Path("safelint"), lang, Path(), "x", preset=preset, pydantic=pydantic)
        tomllib.loads(harness.preset_toml(target))  # raises on a duplicate table


def test_extra_excludes_stay_in_step_with_the_directory_names() -> None:
    """The generated glob list is derived from the names the eligibility check uses."""
    harness = _load_harness()
    for name in harness.EXCLUDED_DIR_NAMES:
        assert f"{name}/**" in harness.EXTRA_EXCLUDES
        assert f"**/{name}/**" in harness.EXTRA_EXCLUDES


def test_an_include_matching_no_source_file_is_an_error(tmp_path: Path) -> None:
    """A mistyped --include must fail loudly, not report zero findings.

    `files_checked` counts the whole project, so the include filter emptying the
    findings looks identical to a clean subtree - and that report gets committed.
    """
    project = tmp_path / "mono"
    (project / "crates" / "ty_a").mkdir(parents=True)
    (project / "crates" / "ty_a" / "a.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    typo = harness.Target(_safelint_on_path(), "python", project, "m", include="crates/typo_", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="selects no python file"):
        harness.validate(typo)


def test_an_include_matching_only_vendored_files_is_an_error(tmp_path: Path) -> None:
    """Eligibility ignores vendored trees, which the run would have excluded anyway."""
    project = tmp_path / "mono"
    (project / "vendor" / "dep").mkdir(parents=True)
    (project / "vendor" / "dep" / "a.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "m", include="vendor", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="selects no python file"):
        harness.validate(target)


def test_an_include_with_eligible_but_clean_files_is_accepted(tmp_path: Path) -> None:
    """Zero findings stays valid when the subtree really does contain source files."""
    project = tmp_path / "mono"
    (project / "crates" / "ty_a").mkdir(parents=True)
    (project / "crates" / "ty_a" / "clean.py").write_text('"""Clean."""\n\nNAME = "x"\n', encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "m", include="crates/ty_", out_dir=tmp_path / "o")
    assert harness.validate(target)[1].violations == []


def test_a_missing_binary_exits_two_without_a_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Naming a nonexistent --safelint is a user error, not a harness crash.

    Version discovery ran before the error guard, so the likeliest way to invoke
    the harness wrongly surfaced as a FileNotFoundError traceback.
    """
    harness = _load_harness()
    missing = tmp_path / "not-a-binary"
    rc = harness.main(["--safelint", str(missing), "--lang", "python", "--project", str(tmp_path), "--label", "x"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err
