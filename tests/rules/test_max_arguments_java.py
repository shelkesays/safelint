"""Tests for ``max_arguments`` (SAFE103) on Java files.

Java-specific tests focused on the three lambda parameter shapes that
tree-sitter-java exposes via the ``parameters`` field. The cross-language
positive case (a regular method with >7 params) is exercised by the
broader Java fixture suite; this file targets the lambda counting path
that previously dropped to zero for untyped lambdas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe103_messages(violations: list) -> list[str]:
    return [v.message for v in violations if v.code == "SAFE103"]


def test_java_method_over_max_args_fires(tmp_path: Path) -> None:
    """Plain method with 8 typed args (over default 7) fires the rule."""
    sample = tmp_path / "Many.java"
    sample.write_text("class Many {\n    void many(int a, int b, int c, int d, int e, int f, int g, int h) {}\n}\n")
    result = _engine().check_file(str(sample))
    msgs = _safe103_messages(result.violations)
    assert any("8 arguments" in m for m in msgs)


def test_java_typed_lambda_over_max_args_fires(tmp_path: Path) -> None:
    """Typed multi-arg lambda counts via formal_parameters."""
    sample = tmp_path / "TypedLambda.java"
    sample.write_text("class TypedLambda {\n    static void use(Object x) {\n        Object lam = (int a, int b, int c, int d, int e, int f, int g, int h) -> a + b;\n    }\n}\n")
    result = _engine().check_file(str(sample))
    msgs = _safe103_messages(result.violations)
    assert any("8 arguments" in m for m in msgs), "Typed lambda with 8 params should fire SAFE103"


def test_java_inferred_lambda_over_max_args_fires(tmp_path: Path) -> None:
    """Untyped multi-arg lambda (inferred_parameters) is now counted.

    Was previously zero-counted because the children of ``inferred_parameters``
    are ``identifier`` nodes, not ``formal_parameter`` / ``spread_parameter``.
    """
    sample = tmp_path / "InferredLambda.java"
    sample.write_text("class InferredLambda {\n    static void use(Object x) {\n        Object lam = (a, b, c, d, e, f, g, h) -> a;\n    }\n}\n")
    result = _engine().check_file(str(sample))
    msgs = _safe103_messages(result.violations)
    assert any("8 arguments" in m for m in msgs), "Untyped multi-arg lambda should now fire SAFE103"


def test_java_single_arg_bare_lambda_counts_as_one(tmp_path: Path) -> None:
    """``a -> ...`` is one parameter, well below the limit; rule does NOT fire."""
    sample = tmp_path / "SingleArg.java"
    sample.write_text("class SingleArg {\n    static void use(Object x) {\n        Object lam = a -> a;\n    }\n}\n")
    result = _engine().check_file(str(sample))
    msgs = _safe103_messages(result.violations)
    assert not any("lam" in m or "<anonymous>" in m for m in msgs)


def test_java_zero_arg_lambda_does_not_fire(tmp_path: Path) -> None:
    """``() -> ...`` has zero parameters; rule does NOT fire."""
    sample = tmp_path / "ZeroArg.java"
    sample.write_text('class ZeroArg {\n    static void use(Runnable r) {\n        use(() -> System.out.println("hi"));\n    }\n}\n')
    result = _engine().check_file(str(sample))
    msgs = _safe103_messages(result.violations)
    # The enclosing `use(Runnable)` has 1 param, also clean
    assert not any("lambda" in m.lower() for m in msgs)
