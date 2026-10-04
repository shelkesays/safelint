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
import re
import shutil
import sys
import time
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


def test_extra_excludes_stay_in_step_with_the_harness_directory_names() -> None:
    """Both glob forms are derived for every harness-added name.

    Superseded in part by the scanner-exclusion test below: this one pins the
    derivation itself (each name yields a root-level and an any-depth pattern),
    which the other does not assert.
    """
    harness = _load_harness()
    for name in harness.HARNESS_EXCLUDED_DIR_NAMES:
        assert f"{name}/**" in harness.EXTRA_EXCLUDES
        assert f"**/{name}/**" in harness.EXTRA_EXCLUDES


def test_a_project_with_no_files_of_the_language_is_an_error(tmp_path: Path) -> None:
    """The wrong --lang must fail loudly; it needs no typo to reach.

    `--lang rust` against a Python repository scans the Python files, filters
    every finding out by extension, and would otherwise report a confident
    `scanned=N, findings=0` Rust result for a project holding no Rust at all.
    """
    project = tmp_path / "pyonly"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "rust", project, "wrong", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="no scannable rust file"):
        harness.validate(target)


def test_include_is_matched_relative_to_the_project_root(tmp_path: Path) -> None:
    """The PROJECT ROOT's own path must not satisfy --include.

    safelint echoes paths as given and the harness passes an absolute project
    path, so a checkout at `/tmp/crates/ty_root` made `--include crates/ty_`
    match every file in the repository - silently widening the subtree it is
    supposed to narrow.
    """
    project = tmp_path / "crates" / "ty_root"
    (project / "crates" / "ty_a").mkdir(parents=True)
    (project / "src").mkdir(parents=True)
    bad = "def f(a, b, c, d, e, f, g, h):\n    return a\n"
    (project / "crates" / "ty_a" / "in.py").write_text(bad, encoding="utf-8")
    (project / "src" / "out.py").write_text(bad, encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "t", include="crates/ty_", out_dir=tmp_path / "o")
    files = {v["filepath"] for v in harness.validate(target)[1].violations}
    assert len(files) == 1, f"only the subtree file may survive the filter, got {files}"
    assert all("ty_a" in f for f in files)


def test_a_scan_that_hangs_is_an_error_not_a_clean_run(tmp_path: Path) -> None:
    """A stalled scanner must be a HarnessError, never zero findings."""
    harness = _load_harness()
    with pytest.raises(harness.HarnessError, match="did not finish within"):
        harness._measured([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)


@pytest.mark.parametrize(
    "payload",
    (
        '{"rules":[{"name":"x"}]}',
        '{"rules":[{"name":"x","languages":null}]}',
        '{"rules":[{"name":123,"languages":["python"]}]}',
        '{"rules":[{"name":"x","languages":"python"}]}',
        '{"rules":[{"name":"x","languages":[1]}]}',
    ),
    ids=["missing-languages", "languages-null", "name-not-str", "languages-bare-str", "languages-item-not-str"],
)
def test_malformed_rule_entries_are_a_harness_error(tmp_path: Path, payload: str) -> None:
    """Entry SHAPE is validated, not merely the presence of the two keys.

    Each of these failed differently without the type check: `null` languages
    raised TypeError on the membership test; a non-string name yielded a rule
    name that would be interpolated into the generated TOML as `[rules.123]`;
    and a bare-string languages field silently degraded membership to a
    substring match, so `go` would have matched `golang`.
    """
    fake = tmp_path / "safelint"
    fake.write_text(f"#!/bin/sh\necho '{payload}'\n", encoding="utf-8")
    fake.chmod(0o755)
    harness = _load_harness()
    with pytest.raises(harness.HarnessError, match=re.escape("not {'name': str, 'languages': [str]}")):
        harness.rules_for(fake, "python")


def test_well_formed_rule_entries_are_accepted(tmp_path: Path) -> None:
    """The guard must not reject a valid registry - language filtering still works."""
    fake = tmp_path / "safelint"
    payload = '{"rules":[{"name":"x","languages":["python"]},{"name":"y","languages":["go"]}]}'
    fake.write_text(f"#!/bin/sh\necho '{payload}'\n", encoding="utf-8")
    fake.chmod(0o755)
    harness = _load_harness()
    assert harness.rules_for(fake, "python") == ["x"]


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
    with pytest.raises(harness.HarnessError, match="selects no scannable python file"):
        harness.validate(typo)


def test_a_symlinked_source_file_is_not_eligible(tmp_path: Path) -> None:
    """safelint refuses to follow symlinks, so one cannot make a subtree eligible.

    `Path.is_file()` follows symlinks, so a symlinked source satisfied the check
    while the scanner skipped it - `scanned=0, findings=0` recorded as clean.
    The reject-all stance is deliberate on safelint's side (2.8.4 hardening), so
    the harness has to mirror it rather than resolve the link.
    """
    project = tmp_path / "symproj"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.py"
    real.write_text("x = 1\n", encoding="utf-8")
    (project / "link.py").symlink_to(real)

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "sym", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="no scannable python file"):
        harness.validate(target)


def test_files_only_under_a_scanner_excluded_tree_are_not_eligible(tmp_path: Path) -> None:
    """Eligibility must know safelint's OWN exclusions, not just the harness's.

    A project whose only Python sits under `.venv/` satisfied the extension test
    while the scanner skipped every file, producing `scanned=0, findings=0` -
    written up as a clean result, which is the exact false pass this check
    exists to prevent.
    """
    project = tmp_path / "venvonly"
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "dep.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "v", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="no scannable python file"):
        harness.validate(target)


def test_generated_config_adds_only_the_harness_specific_excludes(tmp_path: Path) -> None:
    """`extend_exclude_paths` names what the harness ADDS, not safelint's own defaults.

    Asserts the WRITTEN config, parsed back, rather than the constants it is
    derived from: a tuple-membership check passes even if `write_config`
    serialises something safelint cannot read, which is the half that actually
    has to work.

    Eligibility has to know both sets; the config only needs the difference, and
    re-listing safelint's defaults would obscure what the harness changes.
    """
    harness = _load_harness()
    target = harness.Target(Path("safelint"), "python", tmp_path, "cfg")
    harness.write_config(tmp_path, target, [])
    written = tomllib.loads((tmp_path / "safelint.toml").read_text(encoding="utf-8"))

    excludes = written["extend_exclude_paths"]
    for name in harness.HARNESS_EXCLUDED_DIR_NAMES:
        assert f"{name}/**" in excludes, f"{name} missing its root-level pattern"
        assert f"**/{name}/**" in excludes, f"{name} missing its any-depth pattern"
    for name in harness.SCANNER_EXCLUDED_DIR_NAMES:
        assert f"{name}/**" not in excludes, f"{name} is already a safelint default"
        assert name in harness.EXCLUDED_DIR_NAMES, f"{name} must still block eligibility"


def test_the_generated_exclusions_actually_suppress_findings(tmp_path: Path) -> None:
    """The emitted globs must WORK, not merely be present in the file.

    Pairs with the test above: that one proves the config says the right thing,
    this one proves safelint acts on it. A glob that parses but never matches
    would satisfy the first and silently let vendored code into the results -
    which is how the programme's first pass came to lint dependency source and
    report it as the project's own.
    """
    project = tmp_path / "proj"
    (project / "vendor" / "dep").mkdir(parents=True)
    (project / "src").mkdir(parents=True)
    bad = "def f(a, b, c, d, e, f, g, h):\n    return a\n"
    (project / "vendor" / "dep" / "vendored.py").write_text(bad, encoding="utf-8")
    (project / "src" / "own.py").write_text(bad, encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "ex", out_dir=tmp_path / "o")
    files = {v["filepath"] for v in harness.validate(target)[1].violations}

    assert len(files) == 1, f"only the project's own file may report, got {files}"
    assert all("vendor" not in f for f in files)


def test_an_include_matching_only_vendored_files_is_an_error(tmp_path: Path) -> None:
    """Eligibility ignores vendored trees, which the run would have excluded anyway."""
    project = tmp_path / "mono"
    (project / "vendor" / "dep").mkdir(parents=True)
    (project / "vendor" / "dep" / "a.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "m", include="vendor", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="selects no scannable python file"):
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


def test_a_directory_named_like_a_source_file_is_not_eligible(tmp_path: Path) -> None:
    """Eligibility counts FILES: a directory named `generated.py` is not one.

    Without an is_file() test the extension match alone let an otherwise empty
    subtree pass, which is the case the check exists to reject.
    """
    project = tmp_path / "mono"
    (project / "crates" / "ty_a" / "generated.py").mkdir(parents=True)

    harness = _load_harness()
    target = harness.Target(_safelint_on_path(), "python", project, "m", include="crates/ty_", out_dir=tmp_path / "o")
    with pytest.raises(harness.HarnessError, match="selects no scannable python file"):
        harness.validate(target)


def test_unparseable_list_rules_output_is_a_harness_error(tmp_path: Path) -> None:
    """A binary that exits 0 with non-JSON output must not raise JSONDecodeError.

    It is the same user error as a non-zero exit - `--safelint` does not point at
    a safelint - so it takes the documented `error:` path, not a traceback.
    """
    fake = tmp_path / "safelint"
    fake.write_text("#!/bin/sh\necho 'safelint: not json at all'\n", encoding="utf-8")
    fake.chmod(0o755)
    harness = _load_harness()
    with pytest.raises(harness.HarnessError, match="did not return the expected JSON"):
        harness.rules_for(fake, "python")


def test_a_wedged_measurement_wrapper_is_an_error_not_a_hang() -> None:
    """The wrapper bounds the scan; something must bound the WRAPPER.

    Simulated by replacing the runner with one that ignores its own timeout
    argument and sleeps - the shape a wedged wrapper would have. Without an
    outer bound this call never returns, which is the one failure mode the
    timeout work exists to rule out.

    `METADATA_TIMEOUT` is patched down because the real outer bound is the scan
    timeout plus a minute, deliberately too long for a test to wait out.
    """
    harness = _load_harness()
    harness._MEASURED_RUNNER = "import time\ntime.sleep(60)\n"
    harness.METADATA_TIMEOUT = 1.0

    started = time.perf_counter()
    with pytest.raises(harness.HarnessError, match="wrapper did not return within"):
        harness._measured([sys.executable, "-c", "pass"], timeout=0.5)
    assert time.perf_counter() - started < 20, "the bound must fire, not wait out the sleep"


def test_the_eligibility_walk_prunes_excluded_trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Excluded directories are PRUNED, not enumerated and discarded.

    Asserted by recording which directories the walk actually enters, because
    the obvious alternatives do not test pruning at all: a symlink-loop test
    passes on any `os.walk` (`followlinks=False` terminates whether or not
    dirnames are pruned), and a timing test would be flaky. This spy fails if
    the implementation descends into an excluded tree and filters afterwards.
    """
    project = tmp_path / "proj"
    (project / "node_modules" / "dep" / "deeper").mkdir(parents=True)
    (project / "src").mkdir()

    harness = _load_harness()
    real_walk = harness.os.walk
    visited: list[str] = []

    def spy(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited.append(str(dirpath))
            # Yield the SAME dirnames list so the caller's in-place pruning works.
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(harness.os, "walk", spy)
    target = harness.Target(Path("safelint"), "python", project, "p")
    with pytest.raises(harness.HarnessError, match="no scannable python file"):
        harness._check_selection_has_files(target)

    assert str(project) in visited, "the project root is walked"
    assert str(project / "src") in visited, "non-excluded subtrees are still walked"
    descended = [v for v in visited if "node_modules" in v]
    assert descended == [], f"excluded trees must not be entered, but walked: {descended}"


def test_a_run_that_read_zero_files_is_an_error_not_a_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`files_checked == 0` is authoritative: no scan happened, so there is no result.

    The eligibility check that runs first re-derives safelint's discovery rules,
    and every version of that re-derivation has eventually disagreed with the
    scanner - five separate false-clean routes. This backstop needs no mirroring
    and cannot drift, so it is asserted with the mirrored check DISABLED, which
    is the whole point of having it. Issue #192.
    """
    project = tmp_path / "proj"
    (project / ".venv").mkdir(parents=True)
    (project / ".venv" / "dep.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    monkeypatch.setattr(harness, "_check_selection_has_files", lambda _target: None)
    target = harness.Target(_safelint_on_path(), "python", project, "zero", out_dir=tmp_path / "o")

    with pytest.raises(harness.HarnessError, match="read 0 files, so there is nothing to report"):
        harness.validate(target)


def test_the_zero_files_error_carries_safelints_own_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The message quotes safelint's 'no files linted' note, so the cause is visible.

    That note only reaches `--format json` stderr as of #191; before it, the
    harness could say *that* nothing was scanned but never *why*.
    """
    project = tmp_path / "proj"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.py").write_text("x = 1\n", encoding="utf-8")

    harness = _load_harness()
    monkeypatch.setattr(harness, "_check_selection_has_files", lambda _target: None)
    target = harness.Target(_safelint_on_path(), "python", project, "why", out_dir=tmp_path / "o")

    with pytest.raises(harness.HarnessError, match="no files linted under"):
        harness.validate(target)
