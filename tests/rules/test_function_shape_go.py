"""Tests for the function-shape rules (SAFE101-105) on Go files.

Go-specific cases that exercise the dispatch added for Go:

* ``function_declaration`` / ``method_declaration`` / ``func_literal`` are
  the three ``FUNCTION_TYPES``.
* SAFE103 counts parameter *names* (``a, b int`` is two), and the method
  receiver is excluded.
* SAFE105 recognises receiver-qualified self-recursion (``s.Walk()`` inside
  ``func (s *Svc) Walk()``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


def test_go_long_function_fires_safe101(tmp_path: Path) -> None:
    """A function over the default 60-line cap fires SAFE101."""
    sample = tmp_path / "long.go"
    body = "\n".join(f"\t_ = {i}" for i in range(70))
    sample.write_text(f"package main\nfunc longFn() {{\n{body}\n}}\n", encoding="utf-8")
    safe101 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "longFn" in safe101[0].message


def test_go_short_function_is_clean(tmp_path: Path) -> None:
    """A short function fires nothing."""
    sample = tmp_path / "short.go"
    sample.write_text("package main\nfunc small() int {\n\tx := 1\n\treturn x\n}\n", encoding="utf-8")
    assert not _engine().check_file(str(sample)).violations


def test_go_deep_nesting_fires_safe102(tmp_path: Path) -> None:
    """Control-flow nested beyond max_depth=2 fires SAFE102 (switch counts once)."""
    sample = tmp_path / "deep.go"
    sample.write_text(
        "package main\nfunc deep() {\n\tif a {\n\t\tfor b {\n\t\t\tswitch c {\n\t\t\tcase 1:\n\t\t\t}\n\t\t}\n\t}\n}\n",
        encoding="utf-8",
    )
    assert any(v.code == "SAFE102" for v in _engine().check_file(str(sample)).violations)


def test_go_shallow_nesting_is_clean(tmp_path: Path) -> None:
    """Nesting within the cap is clean."""
    sample = tmp_path / "shallow.go"
    sample.write_text("package main\nfunc f() {\n\tif a {\n\t\tg()\n\t}\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE102" for v in _engine().check_file(str(sample)).violations)


def test_go_too_many_arguments_fires_safe103_counting_names(tmp_path: Path) -> None:
    """``a, b int`` counts as two; eight params over the default 7 fires SAFE103."""
    sample = tmp_path / "args.go"
    sample.write_text("package main\nfunc many(a, b, c, d int, e, f, g, h string) {}\n", encoding="utf-8")
    safe103 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_go_method_receiver_not_counted_as_argument(tmp_path: Path) -> None:
    """The method receiver is on a separate field and must not count toward SAFE103."""
    sample = tmp_path / "recv.go"
    sample.write_text("package main\nfunc (s *Svc) M(a, b, c, d, e, f, g int) {}\n", encoding="utf-8")
    # 7 real params == max, receiver excluded, so no violation.
    assert not any(v.code == "SAFE103" for v in _engine().check_file(str(sample)).violations)


def test_go_high_complexity_fires_safe104(tmp_path: Path) -> None:
    """Switch arms plus ``&&`` / ``||`` push cyclomatic complexity over the cap."""
    sample = tmp_path / "cx.go"
    arms = "\n".join(f"\tcase {i}:" for i in range(12))
    sample.write_text(f"package main\nfunc cx() {{\n\tswitch x {{\n{arms}\n\t}}\n}}\n", encoding="utf-8")
    assert any(v.code == "SAFE104" for v in _engine().check_file(str(sample)).violations)


def test_go_simple_function_complexity_is_clean(tmp_path: Path) -> None:
    """A linear function is under the complexity cap."""
    sample = tmp_path / "lin.go"
    sample.write_text("package main\nfunc lin() int {\n\treturn 1\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE104" for v in _engine().check_file(str(sample)).violations)


def test_go_plain_recursion_fires_safe105(tmp_path: Path) -> None:
    """A package function calling itself fires SAFE105."""
    sample = tmp_path / "rec.go"
    sample.write_text("package main\nfunc recurse(n int) int {\n\treturn recurse(n - 1)\n}\n", encoding="utf-8")
    safe105 = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE105"]
    assert len(safe105) == 1
    assert "recurse" in safe105[0].message


def test_go_receiver_qualified_recursion_fires_safe105(tmp_path: Path) -> None:
    """``s.Walk()`` inside ``func (s *Svc) Walk()`` is receiver-qualified self-recursion."""
    sample = tmp_path / "method.go"
    sample.write_text("package main\nfunc (s *Svc) Walk(n int) {\n\ts.Walk(n - 1)\n}\n", encoding="utf-8")
    assert any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)


def test_go_bare_call_in_method_is_not_recursion(tmp_path: Path) -> None:
    """A bare same-named call inside a method denotes a package function, not the method."""
    sample = tmp_path / "notrec.go"
    sample.write_text("package main\nfunc (s *Svc) Other() {\n\thelper()\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)


def test_go_other_receiver_call_is_not_recursion(tmp_path: Path) -> None:
    """``o.Walk()`` (different receiver) inside ``Walk`` is not self-recursion."""
    sample = tmp_path / "other.go"
    sample.write_text("package main\nfunc (s *Svc) Walk() {\n\to.Walk()\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)


def test_go_unnamed_receiver_method_self_call_not_flagged(tmp_path: Path) -> None:
    """A method with an unnamed receiver cannot reference itself, so no SAFE105."""
    sample = tmp_path / "unnamed.go"
    sample.write_text("package main\nfunc (*Svc) Walk() {\n\tg()\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)


def test_go_unnamed_parameters_count_toward_safe103(tmp_path: Path) -> None:
    """Unnamed parameters (``func f(int, string, ...)``) each count as one argument."""
    sample = tmp_path / "unnamed_args.go"
    sample.write_text("package main\nfunc f(int, string, bool, int, string, bool, int, string) {}\n", encoding="utf-8")
    assert any(v.code == "SAFE103" for v in _engine().check_file(str(sample)).violations)


def test_go_anonymous_closure_is_not_self_recursion(tmp_path: Path) -> None:
    """A ``func_literal`` closure has no name, so SAFE105 never fires on it."""
    sample = tmp_path / "closure.go"
    sample.write_text("package main\nfunc f() {\n\tg := func(n int) { recurse() }\n\t_ = g\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE105" for v in _engine().check_file(str(sample)).violations)
