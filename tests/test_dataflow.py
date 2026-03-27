"""Tests for the AST + dataflow hybrid rules and analysis infrastructure."""

from __future__ import annotations

import ast
import textwrap

import pytest

from safelint.analysis.dataflow import TaintTracker, _call_name
from safelint.rules.dataflow import NullDereferenceRule, ReturnValueIgnoredRule, TaintedSinkRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(src: str) -> ast.AST:
    return ast.parse(textwrap.dedent(src))


def violations(rule_cls, src: str, config: dict | None = None):
    cfg = config or {"enabled": True, "severity": "error"}
    rule = rule_cls(cfg)
    return rule.check_file("<test>", parse(src))


# ---------------------------------------------------------------------------
# _call_name (module-level helper in analysis.dataflow)
# ---------------------------------------------------------------------------


def test_call_name_from_name_node():
    tree = parse("foo()")
    call = tree.body[0].value
    assert _call_name(call.func) == "foo"


def test_call_name_from_attribute_node():
    tree = parse("obj.method()")
    call = tree.body[0].value
    assert _call_name(call.func) == "method"


def test_call_name_unknown_returns_none():
    # Subscript call: func_map["key"]() - not a Name or Attribute
    tree = parse("func_map['key']()")
    call = tree.body[0].value
    assert _call_name(call.func) is None


# ---------------------------------------------------------------------------
# TaintTracker unit tests
# ---------------------------------------------------------------------------


SINKS = frozenset(["eval", "exec", "system"])
SANITIZERS = frozenset(["escape", "sanitize"])
SOURCES = frozenset(["input"])


def make_tracker(params: set[str]) -> TaintTracker:
    return TaintTracker(params, SINKS, SANITIZERS, SOURCES)


def test_tracker_direct_param_to_sink():
    src = """
    def process(user_input):
        eval(user_input)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"user_input"})
    tracker.visit(func)
    assert len(tracker.sink_hits) == 1
    lineno, var, sink = tracker.sink_hits[0]
    assert var == "user_input"
    assert sink == "eval"


def test_tracker_propagation_through_assignment():
    src = """
    def process(data):
        x = data
        exec(x)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    assert any(v == "x" and s == "exec" for _, v, s in tracker.sink_hits)


def test_tracker_sanitizer_clears_taint():
    src = """
    def process(user_input):
        safe = escape(user_input)
        eval(safe)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"user_input"})
    tracker.visit(func)
    # safe is cleaned by escape() so eval(safe) must NOT be flagged
    assert not tracker.sink_hits


def test_tracker_source_call_injects_taint():
    src = """
    def read_and_run():
        data = input()
        exec(data)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker(set())  # no params tainted initially
    tracker.visit(func)
    assert len(tracker.sink_hits) == 1
    _, var, sink = tracker.sink_hits[0]
    assert var == "data"
    assert sink == "exec"


def test_tracker_fstring_propagates_taint():
    src = """
    def process(name):
        cmd = f"echo {name}"
        system(cmd)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"name"})
    tracker.visit(func)
    assert any(s == "system" for _, _, s in tracker.sink_hits)


def test_tracker_clean_param_no_hit():
    src = """
    def greet(name):
        print(name)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker(set())  # name is NOT tainted
    tracker.visit(func)
    assert not tracker.sink_hits


def test_tracker_aug_assign_propagates_taint():
    src = """
    def build(fragment):
        cmd = "echo "
        cmd += fragment
        system(cmd)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"fragment"})
    tracker.visit(func)
    assert any(s == "system" for _, _, s in tracker.sink_hits)


# ---------------------------------------------------------------------------
# TaintedSinkRule integration tests
# ---------------------------------------------------------------------------


def test_tainted_sink_detects_eval():
    src = """
    def run_code(user_code):
        eval(user_code)
    """
    vs = violations(TaintedSinkRule, src)
    assert len(vs) == 1
    assert "Tainted" in vs[0].message
    assert "eval" in vs[0].message


def test_tainted_sink_no_violation_for_literal():
    src = """
    def run_code():
        eval("1 + 1")
    """
    vs = violations(TaintedSinkRule, src)
    assert not vs


def test_tainted_sink_chained_taint():
    src = """
    def run(cmd, args):
        full = cmd + " " + args
        system(full)
    """
    vs = violations(TaintedSinkRule, src)
    assert len(vs) >= 1
    assert any("system" in v.message for v in vs)


def test_tainted_sink_respects_custom_sinks():
    src = """
    def query(user_input):
        db_execute(user_input)
    """
    cfg = {"enabled": True, "severity": "error", "sinks": ["db_execute"], "sanitizers": [], "sources": []}
    vs = violations(TaintedSinkRule, src, cfg)
    assert len(vs) == 1
    assert "db_execute" in vs[0].message


def test_tainted_sink_self_cls_not_tainted():
    src = """
    class Processor:
        def run(self, data):
            eval("1 + 1")
    """
    # self is excluded from params so this must NOT flag eval("1 + 1")
    vs = violations(TaintedSinkRule, src)
    # "1 + 1" is a literal, not tainted - expect zero hits
    assert not vs


# ---------------------------------------------------------------------------
# ReturnValueIgnoredRule tests
# ---------------------------------------------------------------------------


def test_return_value_ignored_flags_bare_run():
    src = """
    import subprocess
    subprocess.run(["ls"])
    """
    vs = violations(ReturnValueIgnoredRule, src)
    assert len(vs) == 1
    assert "run" in vs[0].message


def test_return_value_ignored_ok_when_assigned():
    src = """
    import subprocess
    result = subprocess.run(["ls"])
    """
    vs = violations(ReturnValueIgnoredRule, src)
    assert not vs


def test_return_value_ignored_flags_write():
    src = """
    with open("f.txt", "w") as f:
        f.write("hello")
    """
    vs = violations(ReturnValueIgnoredRule, src)
    assert len(vs) == 1
    assert "write" in vs[0].message


def test_return_value_ignored_ok_when_write_assigned():
    src = """
    with open("f.txt", "w") as f:
        n = f.write("hello")
    """
    vs = violations(ReturnValueIgnoredRule, src)
    assert not vs


def test_return_value_ignored_custom_flagged():
    src = """
    cache.invalidate()
    """
    cfg = {"enabled": True, "severity": "warning", "flagged_calls": ["invalidate"]}
    vs = violations(ReturnValueIgnoredRule, src, cfg)
    assert len(vs) == 1
    assert "invalidate" in vs[0].message


def test_return_value_ignored_unflagged_call_ok():
    src = """
    print("hello")
    """
    vs = violations(ReturnValueIgnoredRule, src)
    assert not vs


# ---------------------------------------------------------------------------
# NullDereferenceRule tests
# ---------------------------------------------------------------------------


def test_null_deref_flags_dict_get_attr():
    src = """
    d = {"name": "Alice"}
    length = d.get("name").upper()
    """
    vs = violations(NullDereferenceRule, src)
    assert len(vs) == 1
    assert "get" in vs[0].message


def test_null_deref_flags_dict_get_subscript():
    src = """
    d = {"items": [1, 2]}
    first = d.get("items")[0]
    """
    vs = violations(NullDereferenceRule, src)
    assert len(vs) == 1
    assert "get" in vs[0].message


def test_null_deref_safe_when_result_guarded():
    # No chained dereference - result stored first
    src = """
    d = {"name": "Alice"}
    name = d.get("name")
    if name is not None:
        length = name.upper()
    """
    vs = violations(NullDereferenceRule, src)
    assert not vs


def test_null_deref_fetchone_attr():
    src = """
    row = cursor.fetchone().value
    """
    vs = violations(NullDereferenceRule, src)
    assert len(vs) == 1
    assert "fetchone" in vs[0].message


def test_null_deref_custom_nullable_method():
    src = """
    item = repo.find_by_id(42).name
    """
    cfg = {"enabled": True, "severity": "error", "nullable_methods": ["find_by_id"]}
    vs = violations(NullDereferenceRule, src, cfg)
    assert len(vs) == 1
    assert "find_by_id" in vs[0].message


def test_null_deref_non_nullable_call_ok():
    src = """
    name = str(42).upper()
    """
    vs = violations(NullDereferenceRule, src)
    assert not vs


# ---------------------------------------------------------------------------
# Registry integration - new rules appear in RULE_BY_NAME
# ---------------------------------------------------------------------------


def test_new_rules_in_registry():
    from safelint.rules import RULE_BY_NAME

    assert "tainted_sink" in RULE_BY_NAME
    assert "return_value_ignored" in RULE_BY_NAME
    assert "null_dereference" in RULE_BY_NAME


def test_new_rules_disabled_by_default():
    from safelint.core.config import DEFAULTS

    for name in ("tainted_sink", "return_value_ignored", "null_dereference"):
        assert DEFAULTS["rules"][name]["enabled"] is False, f"{name} should be off by default"


# ---------------------------------------------------------------------------
# TaintTracker edge-case coverage
# ---------------------------------------------------------------------------


def test_tracker_container_propagates_taint():
    """A list literal containing a tainted element is itself tainted."""
    src = """
    def process(data):
        items = [data, "safe"]
        system(items)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    assert any(s == "system" for _, _, s in tracker.sink_hits)


def test_tracker_clean_assignment_discards_taint():
    """Assigning a clean value to a previously tainted variable removes the taint."""
    src = """
    def process(data):
        x = data
        x = "safe_string"
        system(x)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    assert not tracker.sink_hits


def test_tracker_subscript_assignment_target_ignored():
    """Subscript assignment targets (a["key"] = val) don't crash _update_name."""
    src = """
    def process(data):
        a = {}
        a["key"] = data
        eval(data)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    # data is still tainted, eval should still fire
    assert any(s == "eval" for _, _, s in tracker.sink_hits)


def test_tracker_aug_assign_clean_value_no_propagation():
    """An augmented assignment with a clean RHS does not add taint to the target."""
    src = """
    def process():
        cmd = "echo"
        cmd += " hello"
        system(cmd)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker(set())
    tracker.visit(func)
    assert not tracker.sink_hits


def test_tracker_ann_assign_propagates_taint():
    """Annotated assignment (x: str = tainted) marks the target as tainted."""
    src = """
    def process(data):
        x: str = data
        system(x)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    assert any(s == "system" for _, _, s in tracker.sink_hits)


def test_tracker_regular_call_propagates_taint_to_result():
    """A non-source, non-sanitizer call with a tainted arg produces a tainted result."""
    src = """
    def process(data):
        result = fmt(data)
        system(result)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    assert any(s == "system" for _, _, s in tracker.sink_hits)


def test_tracker_ann_assign_no_value_skipped():
    """Annotated assignment with no value (x: int) does not crash or taint."""
    src = """
    def process(data):
        x: int
        system(data)
    """
    tree = parse(src)
    func = tree.body[0]
    tracker = make_tracker({"data"})
    tracker.visit(func)
    # data is still tainted via params; x: int (no value) is a no-op for taint
    assert any(s == "system" for _, _, s in tracker.sink_hits)
