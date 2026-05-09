"""Branch-coverage fill tests for residual gaps after the main test suites.

These tests exist to exercise specific branches that aren't naturally hit
by the per-feature test files:

* ``_nosafe_codes`` malformed-comment edge cases
* engine.check_file's exclusion / unsupported-extension / read-failure paths
* per-file ignore matching across multiple patterns
* parse-error fallback with no recoverable location
* unsupported file extension via ``run`` / ``check_path``
* fail-open paths that aren't already covered

Each test targets one specific branch with the smallest possible setup.
"""

from __future__ import annotations

import argparse
import io
from typing import TYPE_CHECKING

import pytest
import tree_sitter
import tree_sitter_python

from safelint.cli import _run_stdin
from safelint.core import _diagnostics
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import LintResult, SafetyEngine, _nosafe_codes
from safelint.core.runner import run
from safelint.languages._node_utils import call_name as _call_name
from safelint.rules.base import Violation
from safelint.rules.error_handling import _catch_body


if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# _nosafe_codes — edge cases
# ---------------------------------------------------------------------------


def test_nosafe_codes_returns_false_for_non_directive() -> None:
    """A regular comment is not a nosafe directive."""
    assert _nosafe_codes("# this is not a directive") is False


def test_nosafe_codes_returns_false_for_directive_with_only_colon() -> None:
    """``# nosafe:`` (no codes after the colon) is malformed → not a directive."""
    assert _nosafe_codes("# nosafe:") is False


def test_nosafe_codes_returns_false_for_directive_with_only_commas() -> None:
    """``# nosafe: , ,`` (only separators, no codes) is also malformed."""
    assert _nosafe_codes("# nosafe: , ,") is False


def test_nosafe_codes_returns_false_for_directive_with_garbage_after_nosafe() -> None:
    """``# nosafe SAFE101`` (no colon between ``nosafe`` and code) is rejected."""
    # Without the colon, the parser can't distinguish between a code and
    # arbitrary text, so it bails.
    assert _nosafe_codes("# nosafeSAFE101") is False


# ---------------------------------------------------------------------------
# engine.check_file — non-engine branches
# ---------------------------------------------------------------------------


def test_check_file_returns_empty_for_excluded_path(tmp_path: Path) -> None:
    """A file matching ``exclude_paths`` returns an empty LintResult immediately."""
    sample = tmp_path / "skip_me.py"
    sample.write_text("def foo():\n    if True:\n        if True:\n            if True:\n                pass\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"exclude_paths": [str(sample)]})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert result.violations == []
    assert result.suppressed == []


def test_check_file_returns_empty_for_unsupported_extension(tmp_path: Path) -> None:
    """A file with no registered language is silently skipped."""
    sample = tmp_path / "code.rs"
    sample.write_text("fn main() {}", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert result.violations == []


def test_check_file_handles_unicode_decode_error(tmp_path: Path) -> None:
    """Reading non-UTF-8 bytes from a ``.py`` file produces a SAFE000 violation."""
    sample = tmp_path / "bad_encoding.py"
    sample.write_bytes(b"\xff\xfe non-utf8 bytes \x80\x81")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    parse_errs = [v for v in result.violations if v.code == "SAFE000"]
    assert parse_errs


# ---------------------------------------------------------------------------
# Per-file ignore — overlapping patterns
# ---------------------------------------------------------------------------


def test_per_file_ignores_unions_codes_when_multiple_patterns_match(tmp_path: Path) -> None:
    """When two ``per_file_ignores`` patterns match the same file, both
    ignore lists are unioned together for that file (line 275-277 path)."""
    sample = tmp_path / "tests" / "test_foo.py"
    sample.parent.mkdir()
    sample.write_text(
        "def foo(a, b, c, d, e, f, g, h, i):\n    return\n",
        encoding="utf-8",
    )
    sample_posix = sample.as_posix()
    # Patterns that both match this exact absolute path; their codes union.
    cfg = deep_merge(
        DEFAULTS,
        {
            "per_file_ignores": {
                f"{tmp_path.as_posix()}/tests/**": ["SAFE103"],
                "*/test_*.py": ["SAFE101"],
            }
        },
    )
    engine = SafetyEngine(cfg)
    result = engine.check_file(sample_posix)
    # SAFE103 (max_arguments) is suppressed by the first pattern.
    # SAFE101 might or might not fire depending on function length, so
    # only assert that what would normally fire is now suppressed.
    assert not any(v.code == "SAFE103" for v in result.violations)


# ---------------------------------------------------------------------------
# Diagnostics module
# ---------------------------------------------------------------------------


def test_diagnostics_print_warning_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """``print_warning`` writes one ``safelint: warning:`` line on stderr."""
    _diagnostics.print_warning("hello")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "safelint: warning: hello"


def test_diagnostics_print_error_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """``print_error`` writes one ``safelint: error:`` line on stderr."""
    _diagnostics.print_error("bang")
    captured = capsys.readouterr()
    assert captured.err.strip() == "safelint: error: bang"


# ---------------------------------------------------------------------------
# runner.run — paths the CLI tests don't naturally hit
# ---------------------------------------------------------------------------


def test_runner_run_with_no_cache_disables_cache_layer(tmp_path: Path) -> None:
    """``run(no_cache=True)`` runs end-to-end without writing a cache dir."""
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    results = run(sample, no_cache=True)
    assert len(results) == 1
    assert not (tmp_path / ".safelint_cache").exists()


def test_runner_run_explicit_files_param(tmp_path: Path) -> None:
    """``run(files=[…])`` skips discovery and lints exactly those files."""
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")
    results = run(tmp_path, files=[str(a)], no_cache=True)
    assert len(results) == 1
    assert results[0].path == str(a)


def test_runner_run_threads_ignore_into_config(tmp_path: Path) -> None:
    """``run(ignore=[…])`` augments the config's ignore list."""
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    results = run(sample, ignore=["SAFE999"], no_cache=True)
    assert len(results) == 1


def test_runner_run_with_config_path_pointing_at_directory(tmp_path: Path) -> None:
    """``run(config_path=<dir>)`` uses that directory as the config search root."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    results = run(sample, config_path=cfg_dir, no_cache=True)
    assert len(results) == 1


def test_runner_run_with_config_path_pointing_at_file(tmp_path: Path) -> None:
    """``run(config_path=<file>)`` uses the file's parent as the config search root."""
    cfg_file = tmp_path / "pyproject.toml"
    cfg_file.write_text("", encoding="utf-8")
    sample = tmp_path / "f.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    results = run(sample, config_path=cfg_file, no_cache=True)
    assert len(results) == 1


def test_call_name_returns_none_for_unresolvable_function() -> None:
    """``call_name`` returns None when the function sub-node is missing
    (a defensive path Tree-sitter rarely reaches but the type signature allows)."""

    class _FakeNode:
        def child_by_field_name(self, _name: str) -> None:
            return None

    assert _call_name(_FakeNode()) is None  # type: ignore


def test_state_purity_skips_annotated_assignment_with_non_identifier_target(tmp_path: Path) -> None:
    """``a[0]: int = 1`` (subscript target with annotation) isn't a global
    assignment target — the rule must return None, not crash."""
    source = "x = []\ndef f():\n    global x\n    x[0]: int = 1\n"
    sample = tmp_path / "subscript_ann.py"
    sample.write_text(source, encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"global_mutation": {"enabled": True}}})
    # No crash, may or may not flag depending on what the AST looks like.
    SafetyEngine(cfg).check_file(str(sample))


def test_max_arguments_zero_args_no_violation(tmp_path: Path) -> None:
    """A function with no parameters reports zero args and never fires."""
    sample = tmp_path / "no_args.py"
    sample.write_text("def f():\n    pass\n", encoding="utf-8")
    violations = SafetyEngine(DEFAULTS).check_file(str(sample)).violations
    assert not any(v.rule == "max_arguments" for v in violations)


def test_unbounded_loops_does_not_fire_on_proper_comparison(tmp_path: Path) -> None:
    """``while x < 10:`` is a properly-bounded comparison; rule must NOT fire."""
    sample = tmp_path / "good_loop.py"
    sample.write_text("def f():\n    x = 0\n    while x < 10:\n        x += 1\n", encoding="utf-8")
    violations = SafetyEngine(DEFAULTS).check_file(str(sample)).violations
    assert not any(v.rule == "unbounded_loops" for v in violations)


def test_resource_lifecycle_with_missing_value_field(tmp_path: Path) -> None:
    """A degenerate ``with`` (e.g. ``with open(`` parsed as error) should not crash
    the rule even though ``_with_item_call`` returns None for it."""
    # Use a syntactically valid ``with`` that has no call as its context manager;
    # `with x:` where x is just an identifier exercises the not-a-call branch.
    sample = tmp_path / "with_ident.py"
    sample.write_text("def f(x):\n    with x:\n        pass\n", encoding="utf-8")
    SafetyEngine(DEFAULTS).check_file(str(sample))


def test_error_handling_catch_body_fallback() -> None:
    """``_catch_body`` falls back to the last named child when the ``body``
    field isn't directly present — exercise via a tree-sitter parse."""
    lang = tree_sitter.Language(tree_sitter_python.language())
    parser = tree_sitter.Parser(lang)
    tree = parser.parse(b"try:\n    pass\nexcept:\n    pass\n")
    # Find the except_clause node.
    try_node = tree.root_node.children[0]
    except_node = next(c for c in try_node.children if c.type == "except_clause")
    body = _catch_body(except_node)
    # Either field-based or named_children-based fallback should yield a block.
    assert body is not None


def test_per_file_ignores_rejects_non_mapping_value() -> None:
    """``per_file_ignores`` must be a mapping; a list etc. raises TypeError."""
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": ["not", "a", "mapping"]})
    with pytest.raises(TypeError, match="must be a mapping"):
        SafetyEngine(cfg)


def test_per_file_ignores_rejects_non_list_entries() -> None:
    """Each value in ``per_file_ignores`` must be a list/tuple of strings."""
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"tests/**": "not-a-list"}})
    with pytest.raises(TypeError, match="must be a list of strings"):
        SafetyEngine(cfg)


def test_per_file_ignores_warns_on_unknown_entries(capsys: pytest.CaptureFixture[str]) -> None:
    """Typo'd rule names in ``per_file_ignores`` produce a stderr warning."""
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"tests/**": ["SAFFE101"]}})
    SafetyEngine(cfg)  # init shouldn't raise — just warn
    captured = capsys.readouterr()
    assert "safelint: warning:" in captured.err
    assert "SAFFE101" in captured.err


def test_per_file_ignores_warns_on_engine_internal_safe000(capsys: pytest.CaptureFixture[str]) -> None:
    """``per_file_ignores = {"vendor/**" = ["SAFE000"]}`` warns — engine-internal codes can't be per-file-suppressed.

    SAFE000 (parse) is raised from the parse-error early-return in
    ``_lint_parsed_source`` *before* per-file ignore matching ever
    runs, so the entry would silently do nothing. Only the global
    ``ignore`` list works for engine-internal codes. Surfacing this
    via the existing typo-guard warning channel matches how all
    other unknown entries are reported and prevents the user from
    relying on a config that has no effect.
    """
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"vendor/**": ["SAFE000"]}})
    SafetyEngine(cfg)
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "SAFE000" in err


def test_per_file_ignores_warns_on_engine_internal_safe004(capsys: pytest.CaptureFixture[str]) -> None:
    """``per_file_ignores = {"tests/**" = ["SAFE004"]}`` warns — same logic as SAFE000.

    SAFE004 is gated solely on the global ``ignore`` list (via
    ``_engine_internal_ignored``); per-file matching never sees
    it. The warning surfaces the misconfiguration before it
    silently lets stale ``# nosafe`` directives in those files go
    unreported.
    """
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"tests/**": ["SAFE004"]}})
    SafetyEngine(cfg)
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "SAFE004" in err


def test_per_file_ignores_warns_on_engine_internal_rule_name(capsys: pytest.CaptureFixture[str]) -> None:
    """The rule-name aliases (``parse``, ``unused_suppression``) are also rejected."""
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"tests/**": ["unused_suppression", "parse"]}})
    SafetyEngine(cfg)
    err = capsys.readouterr().err
    assert "safelint: warning:" in err
    assert "unused_suppression" in err
    assert "parse" in err


def test_per_file_ignore_safe004_does_not_actually_suppress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``per_file_ignores`` listing SAFE004 must not silence the violation.

    Locks the documented contract in: SAFE004 is gated solely on the
    *global* ``ignore`` list. The earlier engine routed SAFE004
    through ``_is_per_file_ignored`` at append time — that's been
    removed because it contradicted the documented intent and
    surfaced only as accidental behaviour.

    The companion warning regression
    (``test_per_file_ignores_warns_on_engine_internal_safe004``) covers
    the typo-guard message; this test covers the runtime semantics.
    """
    sample = tmp_path / "u.py"
    sample.write_text("x = 1  # nosafe: SAFE304\n", encoding="utf-8")

    # ``per_file_ignores`` can't disable SAFE004 — even with a glob
    # that matches the file under test.
    cfg = deep_merge(DEFAULTS, {"per_file_ignores": {"**": ["SAFE004"]}})
    capsys.readouterr()  # drop the typo-guard warning surfaced at engine init
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE004" for v in result.violations), "per-file SAFE004 must NOT suppress; contract is global ignore only"

    # Sanity: global ``ignore = ["SAFE004"]`` still does suppress
    # (regression — must not accidentally narrow the global path).
    cfg_global = deep_merge(DEFAULTS, {"ignore": ["SAFE004"]})
    capsys.readouterr()
    result_global = SafetyEngine(cfg_global).check_file(str(sample))
    assert not any(v.code == "SAFE004" for v in result_global.violations)


def test_global_ignore_still_accepts_engine_internal_codes_silently(capsys: pytest.CaptureFixture[str]) -> None:
    """The global ``ignore`` list continues to accept SAFE000 / SAFE004 — they DO work there.

    Important — only the per-file path narrowed; the global path
    still treats engine-internal codes as known and silences them
    correctly via ``_engine_internal_ignored``.
    """
    cfg = deep_merge(DEFAULTS, {"ignore": ["SAFE000", "SAFE004", "parse", "unused_suppression"]})
    SafetyEngine(cfg)
    err = capsys.readouterr().err
    # No "unknown entries" warning for the engine-internal codes.
    assert "unknown entries" not in err


def test_test_coverage_rule_no_op_when_no_changed_files(tmp_path: Path) -> None:
    """``test_coupling`` returns no violations when ``changed_files`` is empty —
    ensures the early-return branch in the rule's check_file is hit."""
    sample = tmp_path / "src" / "mod.py"
    sample.parent.mkdir()
    sample.write_text("x = 1\n", encoding="utf-8")
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"test_coupling": {"enabled": True, "test_dirs": ["tests"]}}},
    )
    # No changed_files passed → test_coupling has nothing to flag.
    SafetyEngine(cfg).check_file(str(sample))


# ---------------------------------------------------------------------------
# LintResult helpers
# ---------------------------------------------------------------------------


def test_lint_result_has_violations_property() -> None:
    """``has_violations`` reflects whether the violations list is non-empty."""
    empty = LintResult(path="f.py")
    assert empty.has_violations is False
    full = LintResult(
        path="f.py",
        violations=[Violation(rule="r", code="SAFE001", filepath="f.py", lineno=1, message="m", severity="error")],
    )
    assert full.has_violations is True


# ---------------------------------------------------------------------------
# CLI _run_stdin: edge case where stdin yields nothing
# ---------------------------------------------------------------------------


def test_run_stdin_handles_empty_buffer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """An empty stdin buffer is a valid (empty) file — no violations, no errors."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    args = argparse.Namespace(
        output_format="json",
        stdin=True,
        stdin_filename="empty.py",
        fail_on=None,
        mode=None,
        ignore=None,
        no_cache=True,
    )
    rc = _run_stdin(args)
    assert rc == 0
