"""Tests for ``max_arguments`` (SAFE103) on JavaScript files."""

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


def test_js_too_many_named_params_fires_safe103(tmp_path: Path) -> None:
    """A function with more than max_args (default 7) fires."""
    sample = tmp_path / "many.js"
    sample.write_text("function many(a, b, c, d, e, f, g, h) { return a; }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_js_default_value_param_counts(tmp_path: Path) -> None:
    """``b = 5`` is one parameter (an ``assignment_pattern``)."""
    sample = tmp_path / "defaults.js"
    sample.write_text(
        "function f(a, b = 5, c = 6, d = 7, e = 8, f = 9, g = 10, h = 11) { return 1; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1


def test_js_rest_param_counts_as_one(tmp_path: Path) -> None:
    """``...args`` counts as one parameter, regardless of the unbounded call sites."""
    sample = tmp_path / "rest.js"
    # 7 named + 1 rest = 8 total.
    sample.write_text("function f(a, b, c, d, e, f, g, ...rest) { return rest; }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1


def test_js_destructured_param_counts_as_one(tmp_path: Path) -> None:
    """``{a, b, c}`` is *one* parameter — that's the whole point of using a config object."""
    # 7 named + 1 destructured = 8 total → fires; but the destructured object
    # contributes 1 to the count, not 3.
    sample = tmp_path / "destruct.js"
    sample.write_text(
        "function f(a, b, c, d, e, f, g, {p, q, r}) { return p + q + r; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_js_arrow_function_too_many_params_fires(tmp_path: Path) -> None:
    """Arrow functions are linted the same as ``function`` declarations."""
    sample = tmp_path / "arrow.js"
    sample.write_text(
        "const f = (a, b, c, d, e, f, g, h) => a + h;\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE103" for v in result.violations)


def test_js_method_with_many_params_fires(tmp_path: Path) -> None:
    """Class methods are linted. Unlike Python, JS has no ``self`` to exclude — every named param counts."""
    sample = tmp_path / "method.js"
    # 8 params on the method — exceeds default cap of 7.
    sample.write_text(
        "class C { method(a, b, c, d, e, f, g, h) { return a; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1


def test_js_no_self_or_cls_skip(tmp_path: Path) -> None:
    """Method ``self`` or ``cls`` parameters are NOT special-cased on JS — they count.

    JS doesn't have a ``self`` / ``cls`` convention; if a developer
    happens to name a parameter ``self``, it's just a regular parameter.
    """
    sample = tmp_path / "selflike.js"
    # 7 params; one happens to be named "self". Stays at 7 — under the cap.
    sample.write_text(
        "class C { method(self, a, b, c, d, e, f) { return a; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    # Under the cap (7 == max_args=7).
    assert not any(v.code == "SAFE103" for v in result.violations)

    # Now 8 params — fires; ``self`` is just a regular param so the count is 8, not 7.
    sample = tmp_path / "selflike8.js"
    sample.write_text(
        "class C { method(self, a, b, c, d, e, f, g) { return a; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe103 = [v for v in result.violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_js_few_params_does_not_fire(tmp_path: Path) -> None:
    """A function under the cap produces no SAFE103."""
    sample = tmp_path / "few.js"
    sample.write_text("function f(a, b) { return a + b; }\n", encoding="utf-8")
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE103" for v in result.violations)
