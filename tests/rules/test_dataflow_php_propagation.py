"""Taint-propagation coverage for the PHP tracker (SAFE801).

Exercises the propagation shapes the PhpTaintTracker handles beyond the
direct source-into-sink case: ``assume_taint_preserving`` through unknown
calls, method-receiver propagation, member / subscript access, array literals,
compound assignment, and the array-target write shape. Each asserts that a
tainted superglobal reaching ``system(...)`` through that shape fires SAFE801.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine() -> SafetyEngine:
    """SafetyEngine with the opt-in tainted_sink rule enabled."""
    return SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}}))


def _fires(tmp_path: Path, body: str) -> bool:
    """Return True if *body* (a PHP snippet) produces a SAFE801 violation."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n" + body, encoding="utf-8")
    return any(v.code == "SAFE801" for v in _engine().check_file(str(sample)).violations)


def test_unknown_call_preserves_taint(tmp_path: Path) -> None:
    """An unknown (non-sanitizer) call keeps its tainted argument tainted."""
    assert _fires(tmp_path, "$x = trim($_GET['c']); system($x);")


def test_method_receiver_propagates_taint(tmp_path: Path) -> None:
    """A method call on a tainted receiver yields a tainted value."""
    assert _fires(tmp_path, "$x = $_GET['c']; system($x->raw());")


def test_member_access_propagates_taint(tmp_path: Path) -> None:
    """Property access on a tainted object stays tainted."""
    assert _fires(tmp_path, "$x = $_GET['c']; system($x->prop);")


def test_array_literal_element_propagates_taint(tmp_path: Path) -> None:
    """A tainted element inside an array literal taints the array argument."""
    assert _fires(tmp_path, "system([$_GET['c']]);")


def test_subscript_array_target_taints_base(tmp_path: Path) -> None:
    """Writing a tainted value into ``$arr[]`` taints the base array."""
    assert _fires(tmp_path, "$arr[] = $_GET['c']; system($arr);")


def test_tainted_array_subscript_read(tmp_path: Path) -> None:
    """Reading a key from a tainted array is tainted."""
    assert _fires(tmp_path, "$a['k'] = $_GET['c']; system($a['k']);")


def test_compound_assignment_keeps_prior_taint(tmp_path: Path) -> None:
    """``.=`` is read-modify-write: a clean RHS does not clear prior taint."""
    assert _fires(tmp_path, "$x = $_GET['c']; $x .= 'safe'; system($x);")


def test_static_value_is_clean(tmp_path: Path) -> None:
    """A wholly static value never taints the sink."""
    assert not _fires(tmp_path, "$x = 'static'; system($x);")


def test_assume_taint_preserving_false_drops_unknown_call(tmp_path: Path) -> None:
    """With ``assume_taint_preserving=False`` an unknown call clears taint."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$x = wrap($_GET['c']); system($x);", encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True, "assume_taint_preserving": False}}}))
    assert not any(v.code == "SAFE801" for v in engine.check_file(str(sample)).violations)


def test_call_name_source_injects_taint(tmp_path: Path) -> None:
    """A configured call-name source (not a superglobal) injects taint."""
    sample = tmp_path / "x.php"
    sample.write_text("<?php\n$x = read_input(); system($x);", encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True, "sources_php": ["read_input"]}}}))
    assert any(v.code == "SAFE801" for v in engine.check_file(str(sample)).violations)


def test_property_write_target_not_tracked(tmp_path: Path) -> None:
    """A property write (``$this->prop = ...``) is not a tracked local target; clean with no sink."""
    assert not _fires(tmp_path, "function f(){ $this->prop = $_GET['c']; }")


def test_literal_include_is_clean(tmp_path: Path) -> None:
    """A literal ``include`` path carries no taint."""
    assert not _fires(tmp_path, "include 'config.php';")


def test_namespaced_sink_resolves_trailing_name(tmp_path: Path) -> None:
    """A namespaced sink call (``\\ns\\system(...)``) resolves to the trailing bareword sink."""
    assert _fires(tmp_path, "$x = $_GET['c']; \\ns\\system($x);")
