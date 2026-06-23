"""Tests for resource_lifecycle (SAFE401) and unbounded_loops (SAFE501) on PHP files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


# ---------------------------------------------------------------------------
# resource_lifecycle (SAFE401)
#
# PHP acquirers are global functions (fopen, fsockopen, popen, proc_open,
# curl_init, opendir, tmpfile). PHP has try/finally, so the heuristic is the
# JS-style one: a tracked acquirer must sit inside ``try { ... } finally { ... }``.
# ---------------------------------------------------------------------------


def _cfg401() -> dict:
    """Config with resource_lifecycle enabled (off by default)."""
    return {"rules": {"resource_lifecycle": {"enabled": True}}}


def test_php_fopen_without_try_finally_fires_safe401(tmp_path: Path) -> None:
    """An ``fopen`` with no try/finally guard fires SAFE401."""
    sample = tmp_path / "x.php"
    sample.write_text('<?php\nfunction f(){ $h = fopen("x","r"); }\n', encoding="utf-8")
    safe401 = [v for v in _engine(_cfg401()).check_file(str(sample)).violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "fopen" in safe401[0].message


def test_php_fopen_in_try_finally_is_clean(tmp_path: Path) -> None:
    """An ``fopen`` wrapped in ``try { ... } finally { fclose(...); }`` is clean."""
    sample = tmp_path / "x.php"
    sample.write_text(
        '<?php\nfunction f(){ try { $h = fopen("x","r"); } finally { fclose($h); } }\n',
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE401" for v in _engine(_cfg401()).check_file(str(sample)).violations)


def test_php_try_without_finally_fires_safe401(tmp_path: Path) -> None:
    """A ``try { ... } catch (...) {}`` with no ``finally`` does not guarantee cleanup - fires SAFE401."""
    sample = tmp_path / "x.php"
    sample.write_text(
        '<?php\nfunction f(){ try { $h = fopen("x","r"); } catch(\\E $e){} }\n',
        encoding="utf-8",
    )
    assert any(v.code == "SAFE401" for v in _engine(_cfg401()).check_file(str(sample)).violations)


def test_php_curl_init_without_guard_fires_safe401(tmp_path: Path) -> None:
    """A ``curl_init`` with no try/finally guard fires SAFE401."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ $c = curl_init(); }\n", encoding="utf-8")
    safe401 = [v for v in _engine(_cfg401()).check_file(str(sample)).violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "curl_init" in safe401[0].message


def test_php_no_acquirer_is_clean(tmp_path: Path) -> None:
    """A function that acquires no tracked resource never fires SAFE401."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ $x = 1; }\n", encoding="utf-8")
    assert not any(v.code == "SAFE401" for v in _engine(_cfg401()).check_file(str(sample)).violations)


# ---------------------------------------------------------------------------
# unbounded_loops (SAFE501)
#
# ``while(true)`` and the headerless ``for(;;)`` are the infinite-loop shapes.
# PHP has no named labels; ``break N`` exits N enclosing loop / switch levels,
# so a numeric-level break is what clears (or fails to clear) an infinite loop.
# ---------------------------------------------------------------------------


def _cfg501() -> dict:
    """Config with unbounded_loops enabled (off by default)."""
    return {"rules": {"unbounded_loops": {"enabled": True}}}


def test_php_while_true_without_break_fires_safe501(tmp_path: Path) -> None:
    """A ``while(true)`` with no break fires SAFE501."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ while(true){ doStuff(); } }\n", encoding="utf-8")
    safe501 = [v for v in _engine(_cfg501()).check_file(str(sample)).violations if v.code == "SAFE501"]
    assert len(safe501) == 1


def test_php_while_true_with_break_is_clean(tmp_path: Path) -> None:
    """A ``while(true)`` with a reachable break is clean."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ while(true){ if($x) break; } }\n", encoding="utf-8")
    assert not any(v.code == "SAFE501" for v in _engine(_cfg501()).check_file(str(sample)).violations)


def test_php_headerless_for_without_break_fires_safe501(tmp_path: Path) -> None:
    """A headerless ``for(;;)`` with no break fires SAFE501."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ for(;;){ work(); } }\n", encoding="utf-8")
    safe501 = [v for v in _engine(_cfg501()).check_file(str(sample)).violations if v.code == "SAFE501"]
    assert len(safe501) == 1


def test_php_headerless_for_with_break_is_clean(tmp_path: Path) -> None:
    """A headerless ``for(;;)`` with a reachable break is clean."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ for(;;){ if($x) break; } }\n", encoding="utf-8")
    assert not any(v.code == "SAFE501" for v in _engine(_cfg501()).check_file(str(sample)).violations)


def test_php_bounded_for_is_clean(tmp_path: Path) -> None:
    """A bounded three-clause ``for`` is never SAFE501."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ for($i=0;$i<5;$i++){} }\n", encoding="utf-8")
    assert not any(v.code == "SAFE501" for v in _engine(_cfg501()).check_file(str(sample)).violations)


def test_php_while_false_is_clean(tmp_path: Path) -> None:
    """A ``while(false)`` is not an infinite loop and is never SAFE501."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\nfunction f(){ while(false){} }\n", encoding="utf-8")
    assert not any(v.code == "SAFE501" for v in _engine(_cfg501()).check_file(str(sample)).violations)


def test_php_break_inside_switch_does_not_clear_while_true(tmp_path: Path) -> None:
    """A bare ``break`` inside a ``switch`` exits only the switch, not the enclosing ``while(true)``.

    The numeric break level is 1, which exits the switch; the while still has
    no reachable exit, so SAFE501 fires.
    """
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f(){ while(true){ switch($x){ case 1: break; } } }\n",
        encoding="utf-8",
    )
    safe501 = [v for v in _engine(_cfg501()).check_file(str(sample)).violations if v.code == "SAFE501"]
    assert len(safe501) == 1


def test_php_break_two_clears_while_true_through_switch(tmp_path: Path) -> None:
    """A ``break 2`` exits both the switch and the enclosing ``while(true)`` - clean.

    The numeric break level is 2, which exits two enclosing constructs (the
    switch and the while), giving the loop a reachable exit.
    """
    sample = tmp_path / "x.php"
    sample.write_text(
        "<?php\nfunction f(){ while(true){ switch($x){ case 1: break 2; } } }\n",
        encoding="utf-8",
    )
    assert not any(v.code == "SAFE501" for v in _engine(_cfg501()).check_file(str(sample)).violations)
