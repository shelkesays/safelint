"""Tests for the dataflow rules (SAFE801 tainted_sink, SAFE802 return_value_ignored) on Go files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


_SAFE801 = {"rules": {"tainted_sink": {"enabled": True}}}
_SAFE802 = {"rules": {"return_value_ignored": {"enabled": True}}}


def test_go_tainted_request_value_into_exec_fires_safe801(tmp_path: Path) -> None:
    """A request form value flowing into ``exec.Command`` fires SAFE801."""
    sample = tmp_path / "taint.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("name")\n\texec.Command(name)\n}\n',
        encoding="utf-8",
    )
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "name" in safe801[0].message
    assert "Command" in safe801[0].message


def test_go_literal_argument_is_clean(tmp_path: Path) -> None:
    """A literal command argument is not tainted."""
    sample = tmp_path / "clean.go"
    sample.write_text('package main\nfunc h() {\n\texec.Command("ls")\n}\n', encoding="utf-8")
    assert not any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_sanitized_value_is_clean(tmp_path: Path) -> None:
    """A sanitized value clears taint before reaching the sink."""
    sample = tmp_path / "san.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("n")\n\tsafe := sanitize(name)\n\texec.Command(safe)\n}\n',
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_tainted_capture_in_closure_fires_safe801(tmp_path: Path) -> None:
    """A tainted local captured by a goroutine closure reaching a sink fires SAFE801."""
    sample = tmp_path / "closure.go"
    sample.write_text(
        'package main\nfunc h() {\n\te := os.Getenv("CMD")\n\tgo func() {\n\t\texec.Command(e)\n\t}()\n}\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_var_form_source_propagates_taint(tmp_path: Path) -> None:
    """``var name = r.FormValue(...)`` taints ``name`` (var_spec propagation path)."""
    sample = tmp_path / "varform.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tvar name = r.FormValue("n")\n\texec.Command(name)\n}\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_taint_preserving_through_method_receiver(tmp_path: Path) -> None:
    """``exec.Command(name.Trim())`` stays tainted through the receiver (assume_taint_preserving)."""
    sample = tmp_path / "preserve.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("n")\n\texec.Command(name.Trim())\n}\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_non_identifier_tainted_arg_reports_expr(tmp_path: Path) -> None:
    """A tainted concat expression into a sink reports the variable as ``<expr>``."""
    sample = tmp_path / "concat.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("n")\n\texec.Command(name + "!")\n}\n',
        encoding="utf-8",
    )
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert safe801
    assert "<expr>" in safe801[0].message


def test_go_multi_assign_from_multi_value_source_taints_all(tmp_path: Path) -> None:
    """A 2-name / 1-call assignment from a source taints every bound name (unequal-arity OR path)."""
    sample = tmp_path / "multi.go"
    sample.write_text(
        "package main\nfunc h(r *Request) {\n\ta, b := r.Multi()\n\texec.Command(a)\n\texec.Command(b)\n}\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"tainted_sink": {"enabled": True, "sources_go": ["Multi"]}}}
    safe801 = [v for v in _engine(cfg).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 2


def test_go_tainted_field_access_into_sink(tmp_path: Path) -> None:
    """A tainted receiver's field access (``name.Field``) into a sink fires (selector propagation)."""
    sample = tmp_path / "field.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("n")\n\texec.Command(name.Field)\n}\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_blank_target_in_multi_assign_is_skipped(tmp_path: Path) -> None:
    """The blank ``_`` in ``_, name := source()`` never enters the tainted set."""
    sample = tmp_path / "blankmulti.go"
    sample.write_text(
        "package main\nfunc h(r *Request) {\n\t_, name := r.Multi()\n\texec.Command(name)\n}\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"tainted_sink": {"enabled": True, "sources_go": ["Multi"]}}}
    # ``name`` is tainted and fires; ``_`` was skipped without error.
    assert any(v.code == "SAFE801" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_tainted_index_into_sink(tmp_path: Path) -> None:
    """A tainted index expression flowing into a sink fires (index propagation path)."""
    sample = tmp_path / "index.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := r.FormValue("n")\n\texec.Command(args[name])\n}\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_go_unknown_call_not_preserving_is_clean(tmp_path: Path) -> None:
    """With assume_taint_preserving=false an unknown wrapper call drops taint."""
    sample = tmp_path / "drop.go"
    sample.write_text(
        'package main\nfunc h(r *Request) {\n\tname := wrap(r.FormValue("n"))\n\texec.Command(name)\n}\n',
        encoding="utf-8",
    )
    cfg = {"rules": {"tainted_sink": {"enabled": True, "assume_taint_preserving": False}}}
    assert not any(v.code == "SAFE801" for v in _engine(cfg).check_file(str(sample)).violations)


def test_go_discarded_error_fires_safe802(tmp_path: Path) -> None:
    """A bare ``f.Write(b)`` whose error return is discarded fires SAFE802."""
    sample = tmp_path / "discard.go"
    sample.write_text("package main\nfunc h(f *File, b []byte) {\n\tf.Write(b)\n}\n", encoding="utf-8")
    safe802 = [v for v in _engine(_SAFE802).check_file(str(sample)).violations if v.code == "SAFE802"]
    assert len(safe802) == 1
    assert "Write" in safe802[0].message


def test_go_blank_assignment_discard_is_clean(tmp_path: Path) -> None:
    """``_ = f.Write(b)`` and ``n, _ := f.Write(b)`` are explicit, auditable discards."""
    sample = tmp_path / "explicit.go"
    sample.write_text(
        "package main\nfunc h(f *File, b []byte) {\n\t_ = f.Write(b)\n\tn, _ := f.Write(b)\n\t_ = n\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE802" for v in _engine(_SAFE802).check_file(str(sample)).violations)
