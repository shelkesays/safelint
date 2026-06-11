"""Tests for ``dynamic_code_execution`` (SAFE309), disabled by default.

Structural detection of eval / exec / reflection across Python, JS, TS, Java.
The Python and JS matchers require a bare-identifier callee so method calls
(``model.eval()``) do not fire; Java matches reflection by method name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(extra: dict | None = None) -> SafetyEngine:
    overrides = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    if extra:
        overrides["rules"]["dynamic_code_execution"].update(extra)
    return SafetyEngine(deep_merge(DEFAULTS, overrides))


def _safe309(result: LintResult) -> list[Violation]:
    return [v for v in result.violations if v.code == "SAFE309"]


# ---- Python ----


def test_python_eval_with_constant_fires(tmp_path: Path) -> None:
    """Even a constant argument fires - rule is structural, not taint-based."""
    sample = tmp_path / "e.py"
    sample.write_text('result = eval("1 + 1")\n', encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


def test_python_exec_and_import_fire(tmp_path: Path) -> None:
    sample = tmp_path / "e.py"
    sample.write_text("exec(code)\nmod = __import__(name)\n", encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 2


def test_python_method_eval_is_clean(tmp_path: Path) -> None:
    """``model.eval()`` (PyTorch idiom) is a method call, not builtin eval."""
    sample = tmp_path / "m.py"
    sample.write_text("model.eval()\n", encoding="utf-8")
    assert _safe309(_engine().check_file(str(sample))) == []


def test_python_builtins_eval_fires(tmp_path: Path) -> None:
    sample = tmp_path / "b.py"
    sample.write_text("import builtins\nbuiltins.eval(x)\n", encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


# ---- JavaScript / TypeScript ----


def test_javascript_eval_fires(tmp_path: Path) -> None:
    sample = tmp_path / "e.js"
    sample.write_text("const r = eval(src);\n", encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


def test_javascript_new_function_fires(tmp_path: Path) -> None:
    sample = tmp_path / "f.js"
    sample.write_text('const f = new Function("return 1");\n', encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


def test_javascript_method_eval_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "m.js"
    sample.write_text("obj.eval(x);\n", encoding="utf-8")
    assert _safe309(_engine().check_file(str(sample))) == []


def test_typescript_eval_fires(tmp_path: Path) -> None:
    sample = tmp_path / "e.ts"
    sample.write_text("const r: unknown = eval(src);\n", encoding="utf-8")
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


# ---- Java ----


def test_java_class_forname_fires(tmp_path: Path) -> None:
    sample = tmp_path / "R.java"
    sample.write_text(
        "class R {\n  void run(String n) throws Exception {\n    Class.forName(n);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


def test_java_method_invoke_fires(tmp_path: Path) -> None:
    sample = tmp_path / "I.java"
    sample.write_text(
        "class I {\n  void run(java.lang.reflect.Method m, Object o) throws Exception {\n    m.invoke(o);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe309(_engine().check_file(str(sample)))) == 1


# ---- defaults / config ----


def test_disabled_by_default(tmp_path: Path) -> None:
    sample = tmp_path / "e.py"
    sample.write_text("eval(x)\n", encoding="utf-8")
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert [v for v in result.violations if v.code == "SAFE309"] == []


def test_custom_call_list(tmp_path: Path) -> None:
    """Narrowing the Python list drops ``eval``."""
    sample = tmp_path / "e.py"
    sample.write_text("eval(x)\n", encoding="utf-8")
    eng = _engine({"dynamic_exec_calls": ["exec"]})
    assert _safe309(eng.check_file(str(sample))) == []
