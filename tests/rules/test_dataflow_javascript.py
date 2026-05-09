"""Tests for ``tainted_sink`` (SAFE801), ``return_value_ignored`` (SAFE802),
and ``null_dereference`` (SAFE803) on JavaScript files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _enabled_engine(rule: str, overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with the given dataflow rule enabled (off by default)."""
    base = {"rules": {rule: {"enabled": True}}}
    if overrides:
        base = deep_merge(base, overrides)
    config = deep_merge(DEFAULTS, base)
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# tainted_sink (SAFE801)
# ---------------------------------------------------------------------------


def test_js_direct_param_to_eval_fires(tmp_path: Path) -> None:
    """A tainted parameter passed directly to ``eval`` fires SAFE801."""
    sample = tmp_path / "direct.js"
    sample.write_text(
        "function f(userInput) { eval(userInput); }\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "userInput" in safe801[0].message
    assert "eval" in safe801[0].message


def test_js_taint_through_assignment_fires(tmp_path: Path) -> None:
    """``const y = userInput; eval(y);`` propagates taint through the const declaration."""
    sample = tmp_path / "assign.js"
    sample.write_text(
        "function f(userInput) {\n  const y = userInput;\n  eval(y);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_let_assignment_fires(tmp_path: Path) -> None:
    """``let`` assignment also propagates taint."""
    sample = tmp_path / "let.js"
    sample.write_text(
        "function f(userInput) {\n"
        "  let y;\n"
        "  y = userInput;\n"
        "  Function(y);\n"  # ``Function`` constructor is in the JS sink list
        "}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_template_string_fires(tmp_path: Path) -> None:
    """Template string with ``${tainted}`` interpolation carries taint."""
    sample = tmp_path / "template.js"
    sample.write_text(
        "function f(userInput) {\n  const y = `prefix ${userInput} suffix`;\n  eval(y);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_destructured_param_is_tainted(tmp_path: Path) -> None:
    """``function f({userInput}) { eval(userInput); }`` — destructured params are taint sources."""
    sample = tmp_path / "destruct.js"
    sample.write_text(
        "function f({userInput, other}) {\n  eval(userInput);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_array_destructured_param_is_tainted(tmp_path: Path) -> None:
    """``function f([userInput, ...rest]) { ... }`` — array-destructured params are tainted."""
    sample = tmp_path / "array_destruct.js"
    sample.write_text(
        "function f([userInput, ...rest]) {\n  Function(userInput);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_sanitizer_clears_taint(tmp_path: Path) -> None:
    """``eval(escape(userInput))`` does NOT fire — escape is a sanitizer."""
    sample = tmp_path / "sanitize.js"
    sample.write_text(
        "function f(userInput) {\n  eval(escape(userInput));\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_js_dompurify_sanitizer(tmp_path: Path) -> None:
    """``DOMPurify`` is in the default sanitizer list."""
    sample = tmp_path / "dompurify.js"
    sample.write_text(
        "function f(userInput) {\n  eval(DOMPurify(userInput));\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_js_source_call_injects_taint(tmp_path: Path) -> None:
    """``prompt()`` is in the default source list — its result is tainted."""
    sample = tmp_path / "source.js"
    sample.write_text(
        "function f() {\n  const userInput = prompt('enter:');\n  eval(userInput);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_clean_function_does_not_fire(tmp_path: Path) -> None:
    """A function with no taint flow into a sink is clean."""
    sample = tmp_path / "clean.js"
    sample.write_text(
        "function f(x, y) { return x + y; }\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_js_assume_taint_preserving_false_drops_unknown_calls(tmp_path: Path) -> None:
    """With ``assume_taint_preserving = false``, taint through unknown wrappers is dropped."""
    sample = tmp_path / "wrapper.js"
    sample.write_text(
        "function f(userInput) {\n  const y = wrap(userInput);\n  eval(y);\n}\n",
        encoding="utf-8",
    )
    # Default mode: taint flows through unknown ``wrap``.
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)

    # Less-conservative mode: ``wrap`` drops taint.
    result = _enabled_engine(
        "tainted_sink",
        {"rules": {"tainted_sink": {"assume_taint_preserving": False}}},
    ).check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


# ---------------------------------------------------------------------------
# return_value_ignored (SAFE802)
# ---------------------------------------------------------------------------


def test_js_bare_writefile_call_fires_safe802(tmp_path: Path) -> None:
    """``fs.writeFile(...)`` as a bare statement (not assigned) fires."""
    sample = tmp_path / "writefile.js"
    sample.write_text(
        "fs.writeFile('out.txt', 'data');\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    safe802 = [v for v in result.violations if v.code == "SAFE802"]
    assert len(safe802) == 1
    assert "writeFile" in safe802[0].message


def test_js_assigned_writefile_call_does_not_fire(tmp_path: Path) -> None:
    """Same call but the result is captured — clean."""
    sample = tmp_path / "captured.js"
    sample.write_text(
        "const promise = fs.writeFile('out.txt', 'data');\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert not any(v.code == "SAFE802" for v in result.violations)


def test_js_unlink_call_fires(tmp_path: Path) -> None:
    """``fs.unlink(...)`` as a bare call fires."""
    sample = tmp_path / "unlink.js"
    sample.write_text(
        "fs.unlink('temp.txt');\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert any(v.code == "SAFE802" for v in result.violations)


def test_js_unrelated_function_does_not_fire(tmp_path: Path) -> None:
    """A bare call to a function NOT in the flagged list is clean."""
    sample = tmp_path / "unrelated.js"
    sample.write_text(
        "doSomething('foo');\n",
        encoding="utf-8",
    )
    result = _enabled_engine("return_value_ignored").check_file(str(sample))
    assert not any(v.code == "SAFE802" for v in result.violations)


# ---------------------------------------------------------------------------
# null_dereference (SAFE803)
# ---------------------------------------------------------------------------


def test_js_chained_find_method_fires_safe803(tmp_path: Path) -> None:
    """``arr.find(...).name`` is unsafe — ``find`` returns undefined when no match."""
    sample = tmp_path / "find.js"
    sample.write_text(
        "const name = users.find(u => u.id === 1).name;\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    safe803 = [v for v in result.violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    assert "find" in safe803[0].message


def test_js_optional_chaining_does_not_fire(tmp_path: Path) -> None:
    """``arr.find(...)?.name`` is null-safe by construction — no fire."""
    sample = tmp_path / "optional.js"
    sample.write_text(
        "const name = users.find(u => u.id === 1)?.name;\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert not any(v.code == "SAFE803" for v in result.violations)


def test_js_get_method_chained_fires(tmp_path: Path) -> None:
    """``map.get(key).value`` is unsafe — ``get`` returns undefined for missing keys."""
    sample = tmp_path / "mapget.js"
    sample.write_text(
        "const v = cache.get('key').value;\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_js_getelementbyid_chained_fires(tmp_path: Path) -> None:
    """``document.getElementById(id).value`` is unsafe — DOM lookup may return null."""
    sample = tmp_path / "dom.js"
    sample.write_text(
        "const v = document.getElementById('x').value;\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_js_subscript_on_pop_fires(tmp_path: Path) -> None:
    """``arr.pop()[idx]`` is unsafe — ``pop`` returns undefined on empty array."""
    sample = tmp_path / "pop.js"
    sample.write_text(
        "const v = stack.pop()[0];\n",
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations)


def test_js_safe_method_does_not_fire(tmp_path: Path) -> None:
    """Methods not in the nullable list are exempt."""
    sample = tmp_path / "safe.js"
    sample.write_text(
        "const v = arr.length.toString();\n",  # length is a property; toString never returns null
        encoding="utf-8",
    )
    result = _enabled_engine("null_dereference").check_file(str(sample))
    assert not any(v.code == "SAFE803" for v in result.violations)


# ---------------------------------------------------------------------------
# JsTaintTracker — targeted coverage for taint propagation branches.
# ---------------------------------------------------------------------------


def test_js_taint_through_destructured_assignment(tmp_path: Path) -> None:
    """``const {a} = userInput;`` propagates taint through object destructuring."""
    sample = tmp_path / "destruct_assign.js"
    sample.write_text(
        "function f(userInput) {\n  const {value} = userInput;\n  eval(value);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_array_destructuring(tmp_path: Path) -> None:
    """``const [a, ...rest] = userInput;`` propagates taint to every bound name."""
    sample = tmp_path / "array_destruct_assign.js"
    sample.write_text(
        "function f(userInput) {\n  const [first, ...rest] = userInput;\n  eval(first);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_object_destruct_alias(tmp_path: Path) -> None:
    """``const {key: alias} = userInput;`` taints alias, not key."""
    sample = tmp_path / "alias_destruct.js"
    sample.write_text(
        "function f(userInput) {\n  const {key: alias} = userInput;\n  eval(alias);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_augmented_assignment(tmp_path: Path) -> None:
    """``x += userInput;`` taints x via aug-assignment."""
    sample = tmp_path / "aug.js"
    sample.write_text(
        "function f(userInput) {\n  let x = '';\n  x += userInput;\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_binary_expression(tmp_path: Path) -> None:
    """``const x = 'prefix' + userInput;`` taints via string concat."""
    sample = tmp_path / "concat.js"
    sample.write_text(
        "function f(userInput) {\n  const x = 'prefix' + userInput;\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_ternary(tmp_path: Path) -> None:
    """``const x = cond ? userInput : 'safe';`` taints through ternary."""
    sample = tmp_path / "ternary.js"
    sample.write_text(
        "function f(userInput, cond) {\n  const x = cond ? userInput : 'safe';\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_array_literal(tmp_path: Path) -> None:
    """``const arr = [userInput, 'safe'];`` taints via array literal."""
    sample = tmp_path / "arr.js"
    sample.write_text(
        "function f(userInput) {\n  const arr = [userInput, 'safe'];\n  eval(arr);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_member_expression(tmp_path: Path) -> None:
    """``const x = userInput.field;`` taints x because the receiver is tainted."""
    sample = tmp_path / "member.js"
    sample.write_text(
        "function f(userInput) {\n  const x = userInput.field;\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_subscript_expression(tmp_path: Path) -> None:
    """``const x = userInput[0];`` taints x because the receiver is tainted."""
    sample = tmp_path / "sub.js"
    sample.write_text(
        "function f(userInput) {\n  const x = userInput[0];\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_through_parenthesized(tmp_path: Path) -> None:
    """``const x = (userInput);`` propagates through parens."""
    sample = tmp_path / "paren.js"
    sample.write_text(
        "function f(userInput) {\n  const x = (userInput);\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_taint_expr_arg_to_sink(tmp_path: Path) -> None:
    """A non-identifier expression arg to a sink reports as ``<expr>``."""
    sample = tmp_path / "expr.js"
    sample.write_text(
        "function f(userInput) {\n  eval(userInput + 'suffix');\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    safe801 = [v for v in result.violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "<expr>" in safe801[0].message


def test_js_assignment_with_no_value_does_not_crash(tmp_path: Path) -> None:
    """``var x;`` (no initial value) shouldn't crash the analyser."""
    sample = tmp_path / "novalue.js"
    sample.write_text(
        "function f() {\n  var x;\n  return x;\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_js_template_string_no_substitution(tmp_path: Path) -> None:
    """A plain template string (no ``${...}``) is not tainted, even with tainted vars in scope."""
    sample = tmp_path / "plain_template.js"
    sample.write_text(
        "function f(userInput) {\n  const x = `plain template`;\n  eval(x);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations)


def test_js_default_value_param_is_tainted(tmp_path: Path) -> None:
    """``function f(x = 5)`` — the param ``x`` is a taint source via assignment_pattern."""
    sample = tmp_path / "default_param.js"
    sample.write_text(
        "function f(userInput = 'fallback') {\n  eval(userInput);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_js_pair_pattern_param_taints_alias(tmp_path: Path) -> None:
    """``function f({key: alias})`` — the alias is the bound (and tainted) name."""
    sample = tmp_path / "pair_pattern.js"
    sample.write_text(
        "function f({raw: userInput}) {\n  eval(userInput);\n}\n",
        encoding="utf-8",
    )
    result = _enabled_engine("tainted_sink").check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)
