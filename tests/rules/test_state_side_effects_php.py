"""Tests for the state / side-effect rules (SAFE301/302/303/304/309) on PHP files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


# SAFE301 (global_state) -----------------------------------------------------
# PHP is the first non-Python language registered for SAFE301; the rule keys
# off the ``global`` keyword inside a function body, so the behaviour mirrors
# Python's ``global`` statement.


def test_php_global_declaration_fires_safe301(tmp_path: Path) -> None:
    """A ``global $cfg;`` inside a function reads shared state (SAFE301)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { global $cfg; return $cfg; }\n", encoding="utf-8")
    cfg = {"rules": {"global_state": {"enabled": True}}}
    safe301 = [v for v in _engine(cfg).check_file(str(sample)).violations if v.code == "SAFE301"]
    assert len(safe301) == 1
    assert "$cfg" in safe301[0].message
    assert "global" in safe301[0].message


def test_php_parameter_is_clean_for_safe301(tmp_path: Path) -> None:
    """Passing the value in as a parameter avoids global state (clean)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($cfg) { return $cfg; }\n", encoding="utf-8")
    cfg = {"rules": {"global_state": {"enabled": True}}}
    assert not any(v.code == "SAFE301" for v in _engine(cfg).check_file(str(sample)).violations)


# SAFE302 (global_mutation) --------------------------------------------------


def test_php_write_to_declared_global_fires_safe302(tmp_path: Path) -> None:
    """Writing to a ``global``-declared name mutates shared state (SAFE302)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { global $cfg; $cfg = 1; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True}}}
    assert any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_declaration_without_write_is_clean_by_default(tmp_path: Path) -> None:
    """A bare ``global $cfg;`` with only a read is clean under the lenient default."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { global $cfg; return $cfg; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True}}}
    assert not any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_bare_global_fires_safe302_in_strict_mode(tmp_path: Path) -> None:
    """In strict mode the declaration alone fires, even without a write."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { global $cfg; return $cfg; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True, "strict": True}}}
    assert any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_globals_superglobal_write_fires_safe302(tmp_path: Path) -> None:
    """A ``$GLOBALS['x'] = 1;`` write mutates a superglobal (SAFE302)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { $GLOBALS['x'] = 1; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True}}}
    assert any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_chained_globals_write_fires_safe302(tmp_path: Path) -> None:
    """A chained ``$GLOBALS['a']['b'] = 1;`` write is still a superglobal mutation."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { $GLOBALS['a']['b'] = 1; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True}}}
    assert any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_pure_local_is_clean_for_safe302(tmp_path: Path) -> None:
    """A purely local assignment is not shared-state mutation (clean)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f() { $x = 1; return $x; }\n", encoding="utf-8")
    cfg = {"rules": {"global_mutation": {"enabled": True}}}
    assert not any(v.code == "SAFE302" for v in _engine(cfg).check_file(str(sample)).violations)


# SAFE303 (side_effects_hidden) ----------------------------------------------


def test_php_pure_named_function_doing_io_fires_safe303(tmp_path: Path) -> None:
    """A ``get``-prefixed function doing file I/O has a hidden side effect (SAFE303)."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction getData() { return file_get_contents('x'); }\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"side_effects_hidden": {"enabled": True, "pure_prefixes": ["get", "calculate"]}}}
    assert any(v.code == "SAFE303" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_pure_named_function_without_io_is_clean(tmp_path: Path) -> None:
    """A ``get``-prefixed function that does no I/O is clean for SAFE303."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction getData() { return 1; }\n", encoding="utf-8")
    cfg = {"rules": {"side_effects_hidden": {"enabled": True, "pure_prefixes": ["get", "calculate"]}}}
    assert not any(v.code == "SAFE303" for v in _engine(cfg).check_file(str(sample)).violations)


# SAFE304 (side_effects) -----------------------------------------------------


def test_php_io_call_fires_safe304(tmp_path: Path) -> None:
    """A non-I/O-named function doing file I/O fires SAFE304."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction calc() { return file_get_contents('x'); }\n", encoding="utf-8")
    cfg = {"rules": {"side_effects": {"enabled": True, "io_name_keywords": ["write", "read"]}}}
    assert any(v.code == "SAFE304" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_io_named_function_is_exempt_from_safe304(tmp_path: Path) -> None:
    """A function whose name carries an I/O keyword is exempt (clean)."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction writeLog() { return file_get_contents('x'); }\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"side_effects": {"enabled": True, "io_name_keywords": ["write", "read"]}}}
    assert not any(v.code == "SAFE304" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_pure_function_is_clean_for_safe304(tmp_path: Path) -> None:
    """A pure function with no I/O calls is clean for SAFE304."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction calc() { return 1 + 1; }\n", encoding="utf-8")
    cfg = {"rules": {"side_effects": {"enabled": True, "io_name_keywords": ["write", "read"]}}}
    assert not any(v.code == "SAFE304" for v in _engine(cfg).check_file(str(sample)).violations)


# SAFE309 (dynamic_code_execution) -------------------------------------------


def test_php_eval_fires_safe309(tmp_path: Path) -> None:
    """An ``eval($code);`` call fires SAFE309 (off by default, enabled here)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($code) { eval($code); }\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_call_user_func_fires_safe309(tmp_path: Path) -> None:
    """A ``call_user_func($f);`` call is dynamic dispatch (SAFE309)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($f) { call_user_func($f); }\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_create_function_fires_safe309(tmp_path: Path) -> None:
    """A ``create_function(...)`` call compiles code at runtime (SAFE309)."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f() { create_function('$a', 'return $a;'); }\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_assert_string_fires_safe309(tmp_path: Path) -> None:
    """An ``assert($s)`` call can evaluate a string as code (SAFE309)."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($s) { assert($s); }\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_call_user_func_array_fires_safe309(tmp_path: Path) -> None:
    """A ``call_user_func_array($f, $a);`` call is dynamic dispatch (SAFE309)."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f($f, $a) { call_user_func_array($f, $a); }\n",
        encoding="utf-8",
    )
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_method_named_eval_does_not_fire_safe309(tmp_path: Path) -> None:
    """A method call ``$obj->eval($x);`` is not a global eval and stays clean."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($obj, $x) { $obj->eval($x); }\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert not any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)


def test_php_normal_call_is_clean_for_safe309(tmp_path: Path) -> None:
    """An ordinary function call is clean for SAFE309."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($x) { foo($x); }\n", encoding="utf-8")
    cfg = {"rules": {"dynamic_code_execution": {"enabled": True}}}
    assert not any(v.code == "SAFE309" for v in _engine(cfg).check_file(str(sample)).violations)
