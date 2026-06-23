"""Tests for the dataflow rules (SAFE801 tainted_sink, SAFE802 return_value_ignored, SAFE803 null_dereference) on PHP files."""

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
_SAFE803 = {"rules": {"null_dereference": {"enabled": True}}}


# --- SAFE801 tainted_sink ---------------------------------------------------


def test_php_toplevel_get_into_system_fires_safe801(tmp_path: Path) -> None:
    """A ``$_GET`` superglobal flowing into ``system`` at script scope fires SAFE801."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$x = $_GET['cmd'];\nsystem($x);\n", encoding="utf-8")
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "$x" in safe801[0].message
    assert "system" in safe801[0].message


def test_php_toplevel_post_into_eval_fires_safe801(tmp_path: Path) -> None:
    """A ``$_POST`` superglobal flowing into ``eval`` at script scope fires SAFE801."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$y = $_POST['c'];\neval($y);\n", encoding="utf-8")
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "$y" in safe801[0].message
    assert "eval" in safe801[0].message


def test_php_sanitized_value_is_clean(tmp_path: Path) -> None:
    """A value passed through ``escapeshellarg`` clears taint before the sink."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$x = escapeshellarg($_GET['cmd']);\nsystem($x);\n", encoding="utf-8")
    assert not any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


def test_php_method_sink_via_concat_fires_safe801(tmp_path: Path) -> None:
    """A tainted superglobal concatenated into a query string and passed to ``$db->query`` fires SAFE801."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f($db) {\n    $q = 'SELECT '.$_GET['id'];\n    $db->query($q);\n}\n",
        encoding="utf-8",
    )
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "query" in safe801[0].message


def test_php_tainted_include_fires_safe801(tmp_path: Path) -> None:
    """A tainted path flowing into an ``include`` statement fires SAFE801."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$p = $_GET['page'];\ninclude $p;\n", encoding="utf-8")
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "include" in safe801[0].message


def test_php_param_into_sink_fires_safe801(tmp_path: Path) -> None:
    """Function parameters seed taint, so a bare param into ``exec`` fires SAFE801."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction run($cmd) {\n    exec($cmd);\n}\n", encoding="utf-8")
    safe801 = [v for v in _engine(_SAFE801).check_file(str(sample)).violations if v.code == "SAFE801"]
    assert len(safe801) == 1
    assert "$cmd" in safe801[0].message
    assert "exec" in safe801[0].message


def test_php_literal_argument_is_clean(tmp_path: Path) -> None:
    """A literal command argument carries no taint."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nsystem('ls -la');\n", encoding="utf-8")
    assert not any(v.code == "SAFE801" for v in _engine(_SAFE801).check_file(str(sample)).violations)


# --- SAFE802 return_value_ignored ------------------------------------------


def test_php_discarded_fwrite_fires_safe802(tmp_path: Path) -> None:
    """A bare ``fwrite($h, 'x')`` whose return value is discarded fires SAFE802."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($h) {\n    fwrite($h, 'x');\n}\n", encoding="utf-8")
    safe802 = [v for v in _engine(_SAFE802).check_file(str(sample)).violations if v.code == "SAFE802"]
    assert len(safe802) == 1
    assert "fwrite" in safe802[0].message


def test_php_assigned_fwrite_is_clean(tmp_path: Path) -> None:
    """Assigning ``fwrite``'s return value to a named variable clears SAFE802."""
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f($h) {\n    $n = fwrite($h, 'x');\n    return $n;\n}\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE802" for v in _engine(_SAFE802).check_file(str(sample)).violations)


# --- SAFE803 null_dereference ----------------------------------------------


def test_php_chained_nullable_method_fires_safe803(tmp_path: Path) -> None:
    """Chaining ``->getName()`` off a nullable ``find()`` result fires SAFE803."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($r) {\n    return $r->find(1)->getName();\n}\n", encoding="utf-8")
    safe803 = [v for v in _engine(_SAFE803).check_file(str(sample)).violations if v.code == "SAFE803"]
    assert len(safe803) == 1
    assert "find" in safe803[0].message


def test_php_nullsafe_chain_is_clean(tmp_path: Path) -> None:
    """The nullsafe ``?->`` operator is the safe form and clears SAFE803."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f($r) {\n    return $r->find(1)?->getName();\n}\n", encoding="utf-8")
    assert not any(v.code == "SAFE803" for v in _engine(_SAFE803).check_file(str(sample)).violations)
