"""Tests for ``side_effects_hidden`` (SAFE303) and ``side_effects`` (SAFE304) on JavaScript files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# side_effects_hidden (SAFE303) - pure-named function doing I/O
# ---------------------------------------------------------------------------


def test_js_get_function_with_console_log_fires_safe303(tmp_path: Path) -> None:
    """A function named ``getX`` that calls ``console.log`` is hidden I/O."""
    sample = tmp_path / "hidden.js"
    sample.write_text(
        "function getUser(id) {\n  console.log('fetching');\n  return id;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe303 = [v for v in result.violations if v.code == "SAFE303"]
    assert len(safe303) == 1
    assert "getUser" in safe303[0].message
    assert "log" in safe303[0].message


def test_js_calculate_function_with_fetch_fires_safe303(tmp_path: Path) -> None:
    """``calculate*`` calling ``fetch()`` is hidden network I/O."""
    sample = tmp_path / "hiddenfetch.js"
    sample.write_text(
        "function calculateTotal(items) {\n  fetch('/api/total');\n  return items.length;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe303 = [v for v in result.violations if v.code == "SAFE303"]
    assert len(safe303) == 1


def test_js_validate_function_with_fs_readfile_fires_safe303(tmp_path: Path) -> None:
    """``validate*`` calling ``fs.readFile`` is hidden file I/O."""
    sample = tmp_path / "validate.js"
    sample.write_text(
        "function validateConfig(path) {\n  const data = fs.readFile(path);\n  return data;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe303 = [v for v in result.violations if v.code == "SAFE303"]
    assert len(safe303) == 1
    assert "readFile" in safe303[0].message


def test_js_arrow_function_pure_named_with_io_fires(tmp_path: Path) -> None:
    """Arrow function bound via ``const`` resolves its name through the
    enclosing ``variable_declarator`` - the pure-prefix check fires."""
    sample = tmp_path / "arrow.js"
    sample.write_text(
        "const getData = () => { console.log('side effect'); return 1; };\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe303 = [v for v in result.violations if v.code == "SAFE303"]
    assert len(safe303) == 1
    assert "getData" in safe303[0].message


def test_js_io_named_function_with_io_does_not_fire(tmp_path: Path) -> None:
    """A function named to signal I/O (no pure-prefix match) doesn't fire SAFE303."""
    sample = tmp_path / "intentional.js"
    sample.write_text(
        "function logUser(id) {\n  console.log(id);\n  return id;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE303" for v in result.violations)


# ---------------------------------------------------------------------------
# side_effects (SAFE304) - any non-I/O-named function doing I/O
# ---------------------------------------------------------------------------


def test_js_unnamed_function_with_console_log_fires_safe304(tmp_path: Path) -> None:
    """A function whose name doesn't signal I/O fires SAFE304 on ``console.log``."""
    sample = tmp_path / "unnamed.js"
    sample.write_text(
        "function processOrder(order) {\n  console.log('processing');\n  return order;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe304 = [v for v in result.violations if v.code == "SAFE304"]
    assert len(safe304) == 1
    assert "processOrder" in safe304[0].message


def test_js_io_keyword_in_name_exempts_safe304(tmp_path: Path) -> None:
    """A function whose name *contains* an I/O keyword (``log``, ``write``, ``fetch``, ``send``, ``load``) is exempt."""
    for func_name in ("logEvent", "writeData", "fetchUser", "sendMessage", "loadConfig"):
        sample = tmp_path / f"{func_name}.js"
        sample.write_text(
            f"function {func_name}(x) {{ console.log(x); return x; }}\n",
            encoding="utf-8",
        )
        result = _engine().check_file(str(sample))
        assert not any(v.code == "SAFE304" for v in result.violations), f"{func_name} should be exempt"


def test_js_arithmetic_only_function_does_not_fire_safe304(tmp_path: Path) -> None:
    """A function with no I/O calls is clean."""
    sample = tmp_path / "pure.js"
    sample.write_text(
        "function add(a, b) { return a + b; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE304" for v in result.violations)


def test_js_user_can_override_io_functions_via_config(tmp_path: Path) -> None:
    """``[tool.safelint.rules.side_effects]`` ``io_functions_javascript`` is honoured."""
    sample = tmp_path / "custom.js"
    # ``customIO`` isn't in the default JS list, so without override no fire.
    sample.write_text(
        "function processData(x) { customIO(x); return x; }\n",
        encoding="utf-8",
    )
    # No override: doesn't fire (customIO unknown).
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE304" for v in result.violations)

    # With override naming customIO as I/O: fires.
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"side_effects": {"io_functions_javascript": ["customIO"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE304" for v in result.violations)


def test_js_python_io_list_does_not_leak_into_js(tmp_path: Path) -> None:
    """Default Python list ``[open, print, input]`` doesn't fire on JS - JS uses its own list.

    Regression guard for the per-language defaults: a Python user setting
    ``io_functions = ["error"]`` shouldn't suddenly have every JS
    ``logger.error()`` call flagged via the wrong language's list.
    """
    sample = tmp_path / "pythoncalls.js"
    # ``print`` and ``input`` are Python's I/O verbs; on JS files those
    # names should NOT be in the default I/O list, so a JS function
    # calling ``print()`` is treated as just calling some user function.
    sample.write_text(
        "function processOrder(x) { print(x); input(x); return x; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE304" for v in result.violations)


def test_js_anonymous_arrow_with_io_uses_anonymous_fallback(tmp_path: Path) -> None:
    """A nameless arrow function that calls I/O fires SAFE304 with ``<anonymous>`` in the message.

    Regression guard: the JS function-defining nodes (``arrow_function``,
    ``function_expression``) have no ``name`` field. Without an explicit
    fallback the message would render as ``Function "" calls I/O primitive
    "log"`` - unreadable and visually identical to a real bug. The
    ``<anonymous>`` fallback matches the structural rules' behaviour
    (SAFE101 etc.) and signals the cause directly.
    """
    sample = tmp_path / "anon.js"
    sample.write_text(
        "queue.push(() => { console.log('processing'); });\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe304 = [v for v in result.violations if v.code == "SAFE304"]
    assert len(safe304) == 1
    assert "<anonymous>" in safe304[0].message
    # Defensive: the obviously-wrong empty-name form is gone.
    assert 'Function ""' not in safe304[0].message


def test_js_anonymous_function_expression_uses_anonymous_fallback(tmp_path: Path) -> None:
    """``function () { console.log(...); }`` (anonymous function expression) - same fallback."""
    sample = tmp_path / "anon_fn.js"
    sample.write_text(
        "queue.push(function () { console.log('processing'); });\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe304 = [v for v in result.violations if v.code == "SAFE304"]
    assert len(safe304) == 1
    assert "<anonymous>" in safe304[0].message


def test_js_arrow_function_named_via_const_resolves_binding_name(tmp_path: Path) -> None:
    """``const fetchUser = () => fetch(...);`` - name comes from the enclosing variable_declarator.

    Without the ``variable_declarator`` fallback the function would
    render as ``<anonymous>`` AND silently slip past SAFE304's
    io_name_keyword exemption (the lowercase prefix check would never
    see ``fetch``). This is the most common JS code shape - almost
    every callback / hook / handler is bound this way - so the
    fallback is essential, not cosmetic.
    """
    sample = tmp_path / "named_arrow.js"
    sample.write_text(
        "const fetchUser = () => fetch('/users');\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"side_effects": {"io_name_keywords": ["fetch"]}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    safe304 = [v for v in result.violations if v.code == "SAFE304"]
    assert not safe304  # ``fetchUser`` matches ``fetch`` keyword → exempt


def test_js_pure_named_arrow_function_fires_safe303(tmp_path: Path) -> None:
    """``const getCount = () => fetch(...);`` - pure-prefix match works on the bound name."""
    sample = tmp_path / "pure_arrow.js"
    sample.write_text(
        "const getCount = () => fetch('/count');\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"side_effects_hidden": {"pure_prefixes": ["get"]}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    safe303 = [v for v in result.violations if v.code == "SAFE303"]
    assert len(safe303) == 1
    assert "getCount" in safe303[0].message


def test_js_io_functions_javascript_must_be_list_not_string(tmp_path: Path) -> None:
    """A bare-string typo for ``io_functions_javascript`` raises TypeError, not silently disable.

    ``io_functions_javascript = "log"`` would otherwise be coerced into
    a set of single characters (``{'l', 'o', 'g'}``) by frozenset(...)
    and quietly stop detecting any I/O call. Validate up front so the
    misconfiguration fails loud on the first run.
    """
    sample = tmp_path / "anything.js"
    sample.write_text("function f() { console.log('x'); }\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"side_effects": {"io_functions_javascript": "log"}}})
    with pytest.raises(TypeError, match="io_functions_javascript"):
        SafetyEngine(cfg).check_file(str(sample))


def test_js_io_functions_javascript_rejects_non_string_entries(tmp_path: Path) -> None:
    """Lists with non-string entries also fail clearly."""
    sample = tmp_path / "anything.js"
    sample.write_text("function f() { console.log('x'); }\n", encoding="utf-8")
    cfg = deep_merge(DEFAULTS, {"rules": {"side_effects": {"io_functions_javascript": ["log", 42]}}})
    with pytest.raises(TypeError, match="io_functions_javascript"):
        SafetyEngine(cfg).check_file(str(sample))
