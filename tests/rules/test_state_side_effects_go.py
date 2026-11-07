"""Tests for the state / side-effect rules (SAFE302/303/304/309) on Go files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_mutated_package_var_fires_safe302(tmp_path: Path) -> None:
    """A package-level ``var`` fires when it is actually mutated (#204).

    Rewritten for #204. It previously asserted that a bare ``var counter int``
    and a sentinel ``ErrNF`` both fired, and explicitly recorded "sentinel
    errors are flagged too" as intended. A sentinel error is the canonical Go
    binding that is never mutated, so that assertion was documenting the
    defect: the rule reported the *construct* rather than the hazard it names.
    """
    sample = tmp_path / "state.go"
    sample.write_text(
        'package main\nvar counter int\nvar ErrNF = errors.New("nf")\nconst Limit = 10\n\nfunc Inc() { counter++ }\n',
        encoding="utf-8",
    )

    safe302 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]
    names = " ".join(v.message for v in safe302)

    assert len(safe302) == 1
    assert "counter" in names  # mutated by Inc()
    assert "ErrNF" not in names  # a sentinel error is never reassigned
    assert "Limit" not in names  # const is clean


def test_go_unmutated_package_var_is_clean(tmp_path: Path) -> None:
    """The headline of #204: a ``var`` that is only read does not fire.

    Go's ``const`` accepts only compile-time basic values, so a package-level
    slice, map, struct or linker-written string **cannot** be a ``const``. The
    rule was reporting an idiom with no alternative, and on fzf that was 120
    findings, 97% of them in library code.
    """
    sample = tmp_path / "readonly.go"
    sample.write_text(
        'package main\n\nvar version = "dev"\nvar defaultShapes = []string{"round", "sharp"}\n\nfunc Show() string { return version + defaultShapes[0] }\n',
        encoding="utf-8",
    )

    assert not [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]


@pytest.mark.parametrize(
    ["label", "body"],
    (
        ["plain assignment", "func f() { target = 2 }"],
        ["compound assignment", "func f() { target += 2 }"],
        ["increment", "func f() { target++ }"],
        ["decrement", "func f() { target-- }"],
        ["address taken", "func f() { use(&target) }\nfunc use(p *int) {}"],
    ),
)
def test_every_mutation_shape_still_reports(tmp_path: Path, label: str, body: str) -> None:
    """Each way Go can mutate a package var has to keep firing.

    Address-of is in the list because it hands mutation rights to whoever
    receives the pointer: no write is visible in this file, but the binding is
    no longer effectively constant.
    """
    sample = tmp_path / "shape.go"
    sample.write_text(f"package main\n\nvar target int\n\n{body}\n", encoding="utf-8")

    assert [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"], label


def test_mutating_a_vars_contents_counts(tmp_path: Path) -> None:
    """Element and field writes mutate the shared state, so they must report.

    ``shapes[0] = "b"`` and ``cfg.N = 5`` never rebind the name, so a check
    that only looked for a bare identifier on the left would miss them - and
    they are exactly the hazard SAFE302 names.
    """
    sample = tmp_path / "contents.go"
    sample.write_text(
        'package main\n\nvar shapes = []string{"a"}\nvar cfg struct{ N int }\nvar untouched = "x"\n\nfunc f() {\n\tshapes[0] = "b"\n\tcfg.N = 5\n\t_ = untouched\n}\n',
        encoding="utf-8",
    )

    names = " ".join(v.message for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302")

    assert "shapes" in names
    assert "cfg" in names
    assert "untouched" not in names


def test_go_block_local_var_is_clean(tmp_path: Path) -> None:
    """Block-scoped ``var`` / ``:=`` inside a function is a local, not shared state."""
    sample = tmp_path / "local.go"
    sample.write_text("package main\nfunc f() {\n\tvar x int\n\ty := 1\n\t_ = x\n\t_ = y\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE302" for v in _engine().check_file(str(sample)).violations)


def test_go_grouped_var_block_fires_per_mutated_name(tmp_path: Path) -> None:
    """A grouped ``var ( a; b, c )`` block still fires once per name - per MUTATED name.

    The grouped and single declaration forms are parsed differently
    (``var_spec_list`` versus a bare ``var_spec``), so the mutation filter has
    to reach both. Only ``a`` and ``c`` are written here.
    """
    sample = tmp_path / "grouped.go"
    sample.write_text(
        'package main\nvar (\n\ta int\n\tb, c string\n)\n\nfunc f() {\n\ta = 1\n\tc = "x"\n\t_ = b\n}\n',
        encoding="utf-8",
    )

    safe302 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]
    names = " ".join(v.message for v in safe302)

    assert len(safe302) == 2
    assert "a" in names
    assert "c" in names
    assert '"b"' not in names


def test_go_blank_interface_assertion_is_not_flagged(tmp_path: Path) -> None:
    """``var _ io.Reader = (*T)(nil)`` is a compile-time assertion, not mutable state."""
    sample = tmp_path / "assert.go"
    sample.write_text("package main\nvar _ io.Reader = (*T)(nil)\n", encoding="utf-8")
    assert not any(v.code == "SAFE302" for v in _engine().check_file(str(sample)).violations)


def test_go_var_inside_func_literal_initializer_not_package_level(tmp_path: Path) -> None:
    """A local ``var`` inside a package var's func-literal initializer is not package-level state."""
    sample = tmp_path / "nested.go"
    sample.write_text(
        "package main\nvar handler = func() {\n\tvar local int\n\t_ = local\n}\n\nfunc reset() { handler = nil }\n",
        encoding="utf-8",
    )
    safe302 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE302"]
    # Only the package-level ``handler`` fires; the nested ``local`` does not.
    # ``handler`` is reassigned by ``reset`` so it survives the #204 filter.
    assert len(safe302) == 1
    assert "handler" in safe302[0].message


def test_go_pure_named_function_doing_io_fires_safe303(tmp_path: Path) -> None:
    """A ``get``-prefixed function that performs I/O fires SAFE303."""
    sample = tmp_path / "hidden.go"
    sample.write_text('package main\nfunc getName() {\n\tfmt.Println("io")\n}\n', encoding="utf-8")
    cfg = {"rules": {"side_effects_hidden": {"pure_prefixes": ["get"]}}}
    assert any(v.code == "SAFE303" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_io_call_fires_safe304(tmp_path: Path) -> None:
    """A non-I/O-named function calling ``fmt.Println`` fires SAFE304."""
    sample = tmp_path / "side.go"
    sample.write_text('package main\nfunc compute() {\n\tfmt.Println("x")\n}\n', encoding="utf-8")
    safe304 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE304"]
    assert len(safe304) == 1
    assert "Println" in safe304[0].message


def test_go_pure_function_is_clean(tmp_path: Path) -> None:
    """A function with no I/O calls fires neither SAFE303 nor SAFE304."""
    sample = tmp_path / "pure.go"
    sample.write_text("package main\nfunc add(a, b int) int {\n\treturn a + b\n}\n", encoding="utf-8")
    out = _engine().check_file(str(sample)).violations
    assert not any(v.code in ("SAFE303", "SAFE304") for v in out)


def test_go_reflection_fires_safe309_when_enabled(tmp_path: Path) -> None:
    """``v.MethodByName(...)`` fires SAFE309 (off by default, enabled here)."""
    sample = tmp_path / "reflect.go"
    sample.write_text('package main\nfunc f(v R) {\n\tv.MethodByName("X")\n}\n', encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_no_reflection_is_clean(tmp_path: Path) -> None:
    """A function without reflection / plugin calls is clean for SAFE309."""
    sample = tmp_path / "noreflect.go"
    sample.write_text("package main\nfunc f() {\n\tg()\n}\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert not any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)
