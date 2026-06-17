"""Tests for resource_lifecycle (SAFE401) and unbounded_loops (SAFE501) on Go files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_unclosed_resource_fires_safe401(tmp_path: Path) -> None:
    """An ``os.Open`` with no deferred close fires SAFE401."""
    sample = tmp_path / "leak.go"
    sample.write_text("package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tuse(file)\n}\n", encoding="utf-8")
    safe401 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "Open" in safe401[0].message


def test_go_deferred_close_is_clean(tmp_path: Path) -> None:
    """``defer file.Close()`` in the same function clears SAFE401."""
    sample = tmp_path / "ok.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tdefer file.Close()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_defer_close_in_nested_closure_does_not_guard_outer(tmp_path: Path) -> None:
    """A ``defer`` inside a nested closure does not guard the outer acquirer."""
    sample = tmp_path / "nested.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tgo func() {\n\t\tdefer file.Close()\n\t}()\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_bare_expression_acquirer_always_leaks(tmp_path: Path) -> None:
    """An acquirer with no assignment (no handle) can never be closed - always SAFE401."""
    sample = tmp_path / "bare.go"
    sample.write_text("package main\nfunc f(p string) {\n\tos.Open(p)\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_defer_non_close_does_not_guard(tmp_path: Path) -> None:
    """A ``defer file.Sync()`` (not ``Close``) does not satisfy SAFE401."""
    sample = tmp_path / "wrongdefer.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tdefer file.Sync()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_defer_close_on_other_var_does_not_guard(tmp_path: Path) -> None:
    """A ``defer other.Close()`` on a different variable does not guard this acquirer."""
    sample = tmp_path / "otherclose.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tdefer other.Close()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_returned_acquirer_is_clean(tmp_path: Path) -> None:
    """``return os.Open(p)`` transfers ownership to the caller - not a local leak, so no SAFE401."""
    sample = tmp_path / "returned.go"
    sample.write_text("package main\nfunc f(p string) (*File, error) {\n\treturn os.Open(p)\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_package_scope_acquirer_fires_with_tailored_message(tmp_path: Path) -> None:
    """A package-scope ``var f, _ = os.Open(p)`` fires SAFE401 with package-scope guidance (defer is not valid there)."""
    sample = tmp_path / "pkgscope.go"
    sample.write_text('package main\nvar f, _ = os.Open("config")\n', encoding="utf-8")
    safe401 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "package-scoped" in safe401[0].message


def test_go_bare_identifier_defer_does_not_guard(tmp_path: Path) -> None:
    """A bare ``defer cleanup()`` (not a ``recv.Close()`` selector) does not guard the acquirer."""
    sample = tmp_path / "barecleanup.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tdefer cleanup()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_chained_selector_defer_does_not_guard(tmp_path: Path) -> None:
    """A ``defer obj.inner.Close()`` (non-identifier operand) does not match the simple form."""
    sample = tmp_path / "chained.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tfile, _ := os.Open(p)\n\tdefer obj.inner.Close()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_var_form_acquirer_with_defer_is_clean(tmp_path: Path) -> None:
    """A ``var file, _ = os.Open(p)`` paired with ``defer file.Close()`` is clean.

    ``os.Open`` returns ``(*os.File, error)``, so the valid ``var`` form binds
    both results; this exercises the ``var_spec`` acquirer path.
    """
    sample = tmp_path / "varform.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tvar file, _ = os.Open(p)\n\tdefer file.Close()\n\tuse(file)\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_multi_acquirer_only_one_deferred_fires_for_the_other(tmp_path: Path) -> None:
    """``a, b := os.Open(p1), os.Open(p2)`` with only ``defer a.Close()`` leaks ``b``."""
    sample = tmp_path / "multi.go"
    sample.write_text(
        "package main\nfunc f(p1, p2 string) {\n\ta, b := os.Open(p1), os.Open(p2)\n\tdefer a.Close()\n\tuse(a, b)\n}\n",
        encoding="utf-8",
    )
    safe401 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE401"]
    assert len(safe401) == 1  # only the b acquirer leaks


def test_go_defer_before_acquisition_does_not_guard(tmp_path: Path) -> None:
    """A ``defer f.Close()`` written before ``f`` is acquired cannot close it (Go evaluates the receiver at defer time)."""
    sample = tmp_path / "deferbefore.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tdefer f.Close()\n\tf, _ := os.Open(p)\n\tuse(f)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_conditional_defer_does_not_guard(tmp_path: Path) -> None:
    """A ``defer f.Close()`` nested inside an ``if`` does not run on every exit path."""
    sample = tmp_path / "conddefer.go"
    sample.write_text(
        "package main\nfunc f(p string) {\n\tf, _ := os.Open(p)\n\tif cond {\n\t\tdefer f.Close()\n\t}\n\tuse(f)\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine().check_file(str(sample)).violations)


def test_go_bare_infinite_for_fires_safe501(tmp_path: Path) -> None:
    """A bare ``for {}`` with no break fires SAFE501."""
    sample = tmp_path / "loop.go"
    sample.write_text("package main\nfunc f() {\n\tfor {\n\t\twork()\n\t}\n}\n", encoding="utf-8")
    safe501 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE501"]
    assert len(safe501) == 1
    assert "for {}" in safe501[0].message


def test_go_for_with_break_is_clean(tmp_path: Path) -> None:
    """A ``for {}`` with a reachable break is clean."""
    sample = tmp_path / "break.go"
    sample.write_text("package main\nfunc f() {\n\tfor {\n\t\tif done() {\n\t\t\tbreak\n\t\t}\n\t}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE501" for v in _engine().check_file(str(sample)).violations)


def test_go_bounded_for_is_clean(tmp_path: Path) -> None:
    """A three-clause and a range ``for`` are bounded shapes, never SAFE501."""
    sample = tmp_path / "bounded.go"
    sample.write_text(
        "package main\nfunc f(xs []int) {\n\tfor i := 0; i < 10; i++ {\n\t}\n\tfor _, x := range xs {\n\t\t_ = x\n\t}\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE501" for v in _engine().check_file(str(sample)).violations)


def test_go_labelled_break_clears_both_loops(tmp_path: Path) -> None:
    """``break outer`` from the inner loop terminates both loops, so neither fires SAFE501.

    Without labelled-break resolution both bare ``for {}`` loops would be
    flagged; resolving the label correctly recognises that ``break outer``
    provides a reachable exit for each.
    """
    sample = tmp_path / "label.go"
    sample.write_text(
        "package main\nfunc f() {\nouter:\n\tfor {\n\t\tfor {\n\t\t\tbreak outer\n\t\t}\n\t}\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE501" for v in _engine().check_file(str(sample)).violations)


def test_go_inner_loop_without_break_still_fires(tmp_path: Path) -> None:
    """An inner bare ``for {}`` with no exit fires even when the outer loop has one."""
    sample = tmp_path / "innerleak.go"
    sample.write_text(
        "package main\nfunc f() {\n\tfor {\n\t\tfor {\n\t\t\twork()\n\t\t}\n\t\tif done() {\n\t\t\tbreak\n\t\t}\n\t}\n}\n",
        encoding="utf-8",
    )
    # Outer loop has a reachable break; inner bare ``for {}`` does not.
    safe501 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE501"]
    assert len(safe501) == 1
