"""Tests for ``no_recursion`` (SAFE105) across every supported language.

Covers direct self-recursion (fires), iterative equivalents (clean), the
nested-same-name guard, and the receiver guard (``other.foo()`` inside
``foo`` must not fire; ``self``/``this`` qualified self-calls must).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe105(result) -> list:
    return [v for v in result.violations if v.code == "SAFE105"]


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_python_direct_recursion_fires(tmp_path: Path) -> None:
    """A bare self-call fires SAFE105."""
    sample = tmp_path / "rec.py"
    sample.write_text("def fact(n):\n    return n * fact(n - 1)\n", encoding="utf-8")
    hits = _safe105(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "fact" in hits[0].message


def test_python_iterative_is_clean(tmp_path: Path) -> None:
    """An iterative function with no self-call does not fire."""
    sample = tmp_path / "iter.py"
    sample.write_text("def fact(n):\n    acc = 1\n    for i in range(1, n + 1):\n        acc *= i\n    return acc\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_self_method_recursion_fires(tmp_path: Path) -> None:
    """``self.method()`` inside ``method`` is self-recursion."""
    sample = tmp_path / "selfrec.py"
    sample.write_text("class C:\n    def walk(self, n):\n        return self.walk(n - 1)\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_python_other_object_same_name_is_clean(tmp_path: Path) -> None:
    """``other.walk()`` inside ``walk`` must NOT fire (different receiver)."""
    sample = tmp_path / "other.py"
    sample.write_text("class C:\n    def walk(self, other, n):\n        return other.walk(n - 1)\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_nested_function_same_name_not_misattributed(tmp_path: Path) -> None:
    """A nested helper sharing the outer name fires once (for itself), not for the outer."""
    sample = tmp_path / "nested.py"
    sample.write_text(
        "def process(data):\n    def process(x):\n        return process(x - 1)\n    return len(data)\n",
        encoding="utf-8",
    )
    hits = _safe105(_engine().check_file(str(sample)))
    # The inner ``process`` recurses (1 hit). The outer ``process`` only
    # *defines* the helper and calls ``len`` - the inner self-call must not
    # be attributed to the outer function (the skip_types prune), so the
    # total is exactly 1, not 2.
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------


def test_javascript_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.js"
    sample.write_text("function fact(n) {\n  return n * fact(n - 1);\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_javascript_this_method_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "selfrec.js"
    sample.write_text("class C {\n  walk(n) {\n    return this.walk(n - 1);\n  }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_javascript_other_receiver_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "other.js"
    sample.write_text("class C {\n  walk(other, n) {\n    return other.walk(n - 1);\n  }\n}\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_javascript_anonymous_arrow_not_flagged(tmp_path: Path) -> None:
    """Anonymous arrow recursion via a binding is a documented blind spot - no false crash."""
    sample = tmp_path / "anon.js"
    sample.write_text("const f = (n) => (n <= 0 ? 0 : f(n - 1));\n", encoding="utf-8")
    # No name on the arrow function, so nothing fires. The point is the rule
    # neither crashes nor mis-fires on anonymous functions.
    assert _safe105(_engine().check_file(str(sample))) == []


def test_typescript_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.ts"
    sample.write_text("function fact(n: number): number {\n  return n * fact(n - 1);\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


def test_java_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "Rec.java"
    sample.write_text(
        "class Rec {\n  int fact(int n) {\n    return n * fact(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_this_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "Self.java"
    sample.write_text(
        "class Self {\n  int walk(int n) {\n    return this.walk(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_other_receiver_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "Other.java"
    sample.write_text(
        "class Other {\n  int walk(Other o, int n) {\n    return o.walk(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def test_rust_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.rs"
    sample.write_text("fn fact(n: u64) -> u64 {\n    if n == 0 { 1 } else { n * fact(n - 1) }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_self_method_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "selfrec.rs"
    sample.write_text(
        "struct C;\nimpl C {\n    fn walk(&self, n: u64) -> u64 {\n        self.walk(n - 1)\n    }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_iterative_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "iter.rs"
    sample.write_text("fn sum(xs: &[u64]) -> u64 {\n    let mut acc = 0;\n    for x in xs { acc += x; }\n    acc\n}\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_safe105_carries_informational_suggestion(tmp_path: Path) -> None:
    """Each SAFE105 violation carries the advisory loop/worklist suggestion (no edits)."""
    sample = tmp_path / "rec.py"
    sample.write_text("def fact(n):\n    return n * fact(n - 1)\n", encoding="utf-8")
    hits = _safe105(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert len(hits[0].suggestions) == 1
    assert hits[0].suggestions[0].edits == ()
    assert "loop" in hits[0].suggestions[0].description


def test_python_shadowing_nested_def_called_in_outer_body_is_clean(tmp_path: Path) -> None:
    """Outer body calling a same-named nested function is shadowing, not recursion."""
    sample = tmp_path / "shadow.py"
    sample.write_text(
        "def process(data):\n    def process(x):\n        return x\n    return process(data)\n",
        encoding="utf-8",
    )
    # The bare ``process(data)`` in the outer body resolves to the nested
    # ``process`` (Python function-scope shadowing), so the outer function is
    # NOT self-recursive; the nested one does not call itself either.
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_shadowed_self_qualified_call_still_fires(tmp_path: Path) -> None:
    """A ``self.``-qualified call still denotes the method even when a nested fn shadows the name."""
    sample = tmp_path / "shadowself.py"
    sample.write_text(
        "class C:\n    def walk(self, n):\n        def walk(x):\n            return x\n        return self.walk(n - 1)\n",
        encoding="utf-8",
    )
    # ``self.walk(...)`` is the method (real recursion); the nested ``walk``
    # only shadows the *bare* name, not the qualified receiver.
    assert len(_safe105(_engine().check_file(str(sample)))) == 1
