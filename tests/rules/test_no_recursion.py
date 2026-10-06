"""Tests for ``no_recursion`` (SAFE105) across every supported language.

Covers direct self-recursion (fires), iterative equivalents (clean), the
nested-same-name guard, and the receiver guard (``other.foo()`` inside
``foo`` must not fire; ``self``/``this`` qualified self-calls must).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.core.engine import LintResult
    from safelint.rules.base import Violation

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


def _safe105(result: LintResult) -> list[Violation]:
    return [v for v in result.violations if v.code == "SAFE105"]


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def test_python_direct_recursion_fires(tmp_path: Path) -> None:
    """A bare self-call fires SAFE105."""
    sample = tmp_path / "rec.py"
    sample.write_text("def fact(n):\n    return n * fact(n - 1)\n", encoding="utf-8")
    hits = _safe105(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert "fact" in hits[0].message


def test_python_iterative_is_clean(tmp_path: Path) -> None:
    """An iterative function with no self-call does not fire."""
    sample = tmp_path / "iter.py"
    sample.write_text("def fact(n):\n    acc = 1\n    for i in range(1, n + 1):\n        acc *= i\n    return acc\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_self_method_recursion_fires(tmp_path: Path) -> None:
    """``self.method()`` inside ``method`` is self-recursion."""
    sample = tmp_path / "selfrec.py"
    sample.write_text("class C:\n    def walk(self, n):\n        return self.walk(n - 1)\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_python_other_object_same_name_is_clean(tmp_path: Path) -> None:
    """``other.walk()`` inside ``walk`` must NOT fire (different receiver)."""
    sample = tmp_path / "other.py"
    sample.write_text("class C:\n    def walk(self, other, n):\n        return other.walk(n - 1)\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_nested_function_same_name_not_misattributed(tmp_path: Path) -> None:
    """A nested helper sharing the outer name fires once (for itself), not for the outer."""
    sample = tmp_path / "nested.py"
    sample.write_text(
        "def process(data):\n    def process(x):\n        return process(x - 1)\n    return len(data)\n",
        encoding="utf-8",
    )
    hits = _safe105(_engine().check_file(str(sample)))
    # The inner ``process`` recurses (1 hit). The outer ``process`` only
    # *defines* the helper and calls ``len`` - the inner self-call must not
    # be attributed to the outer function (the skip_types prune), so the
    # total is exactly 1, not 2.
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------


def test_javascript_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.js"
    sample.write_text("function fact(n) {\n  return n * fact(n - 1);\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_javascript_this_method_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "selfrec.js"
    sample.write_text("class C {\n  walk(n) {\n    return this.walk(n - 1);\n  }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_javascript_other_receiver_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "other.js"
    sample.write_text("class C {\n  walk(other, n) {\n    return other.walk(n - 1);\n  }\n}\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_javascript_anonymous_arrow_not_flagged(tmp_path: Path) -> None:
    """Anonymous arrow recursion via a binding is a documented blind spot - no false crash."""
    sample = tmp_path / "anon.js"
    sample.write_text("const f = (n) => (n <= 0 ? 0 : f(n - 1));\n", encoding="utf-8")
    # No name on the arrow function, so nothing fires. The point is the rule
    # neither crashes nor mis-fires on anonymous functions.
    assert _safe105(_engine().check_file(str(sample))) == []


def test_typescript_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.ts"
    sample.write_text("function fact(n: number): number {\n  return n * fact(n - 1);\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


def test_java_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "Rec.java"
    sample.write_text(
        "class Rec {\n  int fact(int n) {\n    return n * fact(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_this_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "Self.java"
    sample.write_text(
        "class Self {\n  int walk(int n) {\n    return this.walk(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_other_receiver_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "Other.java"
    sample.write_text(
        "class Other {\n  int walk(Other o, int n) {\n    return o.walk(n - 1);\n  }\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def test_rust_direct_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "rec.rs"
    sample.write_text("fn fact(n: u64) -> u64 {\n    if n == 0 { 1 } else { n * fact(n - 1) }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_self_method_recursion_fires(tmp_path: Path) -> None:
    sample = tmp_path / "selfrec.rs"
    sample.write_text(
        "struct C;\nimpl C {\n    fn walk(&self, n: u64) -> u64 {\n        self.walk(n - 1)\n    }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_iterative_is_clean(tmp_path: Path) -> None:
    sample = tmp_path / "iter.rs"
    sample.write_text("fn sum(xs: &[u64]) -> u64 {\n    let mut acc = 0;\n    for x in xs { acc += x; }\n    acc\n}\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_safe105_carries_informational_suggestion(tmp_path: Path) -> None:
    """Each SAFE105 violation carries the advisory loop/worklist suggestion (no edits)."""
    sample = tmp_path / "rec.py"
    sample.write_text("def fact(n):\n    return n * fact(n - 1)\n", encoding="utf-8")
    hits = _safe105(_engine().check_file(str(sample)))
    assert len(hits) == 1
    assert len(hits[0].suggestions) == 1
    assert hits[0].suggestions[0].edits == ()
    assert "loop" in hits[0].suggestions[0].description


def test_python_shadowing_nested_def_called_in_outer_body_is_clean(tmp_path: Path) -> None:
    """Outer body calling a same-named nested function is shadowing, not recursion."""
    sample = tmp_path / "shadow.py"
    sample.write_text(
        "def process(data):\n    def process(x):\n        return x\n    return process(data)\n",
        encoding="utf-8",
    )
    # The bare ``process(data)`` in the outer body resolves to the nested
    # ``process`` (Python function-scope shadowing), so the outer function is
    # NOT self-recursive; the nested one does not call itself either.
    assert _safe105(_engine().check_file(str(sample))) == []


def test_python_shadowed_self_qualified_call_still_fires(tmp_path: Path) -> None:
    """A ``self.``-qualified call still denotes the method even when a nested fn shadows the name."""
    sample = tmp_path / "shadowself.py"
    sample.write_text(
        "class C:\n    def walk(self, n):\n        def walk(x):\n            return x\n        return self.walk(n - 1)\n",
        encoding="utf-8",
    )
    # ``self.walk(...)`` is the method (real recursion); the nested ``walk``
    # only shadows the *bare* name, not the qualified receiver.
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


# ---------------------------------------------------------------------------
# Java: argument count separates a convenience overload from real recursion
# ---------------------------------------------------------------------------


def test_java_overload_with_different_arity_is_not_recursion(tmp_path: Path) -> None:
    """A call whose argument count differs from the signature is a different overload.

    The convenience-overload-delegates-to-the-general-one pattern is what Commons
    Lang and Guava are built from, so the rule was loudest on the most idiomatic
    Java in the ecosystem - 2814 findings across the two, 51% of Commons Lang's
    default output. Arity settles it without any type resolution. Issue #153.
    """
    sample = tmp_path / "Over.java"
    sample.write_text(
        "class A {\n"
        "    boolean[] add(boolean[] a, int i, boolean e) { return (boolean[]) add(a, i, Boolean.valueOf(e), Boolean.TYPE); }\n"
        "    Object add(Object a, int i, Object e, Class<?> t) { return null; }\n"
        "}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_java_same_arity_self_call_still_fires(tmp_path: Path) -> None:
    """Matching arity is still reported - the arity check must not silence real recursion."""
    sample = tmp_path / "Fact.java"
    sample.write_text("class A {\n    int fact(int n) { return n * fact(n - 1); }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_varargs_mismatch_still_fires(tmp_path: Path) -> None:
    """Varargs accept any argument count, so a mismatch proves nothing and stays reported.

    `vg(String... s)` has one parameter and `vg("a", "b")` passes two; that is a
    genuine self-call. Arity can only rule a call OUT when the signature is fixed.
    """
    sample = tmp_path / "Var.java"
    sample.write_text('class A {\n    void vg(String... s) { vg("a", "b"); }\n}\n', encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_zero_arg_self_call_still_fires(tmp_path: Path) -> None:
    """Zero parameters and zero arguments match, so the call is real recursion."""
    sample = tmp_path / "Zero.java"
    sample.write_text("class A {\n    void spin() { spin(); }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_argument_cast_to_object_rules_out_a_non_object_parameter(tmp_path: Path) -> None:
    """`remove((Object) array, index)` inside `remove(boolean[], int)` is delegation.

    Same arity, so the arity check cannot settle it, but `Object` is not assignable
    to `boolean[]`, which makes the enclosing method inapplicable. Issue #153.
    """
    sample = tmp_path / "Cast.java"
    sample.write_text(
        "class A {\n"
        "    static boolean[] remove(boolean[] array, int index) { return (boolean[]) remove((Object) array, index); }\n"
        "    static Object remove(Object array, int index) { return array; }\n"
        "}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_java_cast_to_object_against_an_object_parameter_still_fires(tmp_path: Path) -> None:
    """A cast to `Object` proves nothing when the parameter is already `Object`."""
    sample = tmp_path / "CastObj.java"
    sample.write_text(
        "class A {\n    static Object f(Object a, int i) { return f((Object) a, i); }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_cast_to_object_against_a_type_variable_still_fires(tmp_path: Path) -> None:
    """`<T> T f(T a, int i)` really does accept `f((Object) a, i)`, inferring T as Object.

    The negative control that keeps the cast rule from over-reaching: a parameter
    declared as a type variable accepts anything, so the cast rules nothing out.
    """
    sample = tmp_path / "CastTvar.java"
    sample.write_text(
        "class A {\n    static <T> T f(T a, int i) { return f((Object) a, i); }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_array_element_of_the_same_positions_parameter_is_delegation(tmp_path: Path) -> None:
    """`append(lhs[0], ..)` inside `append(Object[] lhs, ..)` reaches the element overload.

    An element type is never assignable to its own array type, so this needs no
    type hierarchy to decide. The shape is Commons Lang's `CompareToBuilder`.
    """
    sample = tmp_path / "Elem.java"
    sample.write_text(
        "class A {\n    int append(Object[] lhs, Object[] rhs) { return append(lhs[0], rhs[0]); }\n    int append(Object a, Object b) { return 0; }\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_java_foreach_variable_over_an_array_parameter_is_delegation(tmp_path: Path) -> None:
    """`for (boolean e : array) append(e);` inside `append(boolean[] array)` is delegation.

    The same fact as the array-element rule, spelled through a for-each variable
    rather than an index. This is Commons Lang's `HashCodeBuilder` family, six
    findings in one file, none of which carries a cast.
    """
    sample = tmp_path / "ForEach.java"
    sample.write_text(
        "class A {\n    void append(boolean[] array) { for (boolean element : array) { append(element); } }\n    void append(boolean e) {}\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_java_varargs_with_an_incompatible_fixed_arity_sibling_still_fires(tmp_path: Path) -> None:
    """A fixed-arity sibling at the same arity does NOT rule out a varargs self-call.

    JLS 15.12.2 reaches phase 3 (varargs) only when nothing is applicable in phases
    1 and 2, and applicability needs compatible argument *types*, not a matching
    count. `j(int, int, int)` cannot take `j(a, "b", "c")`, so phases 1 and 2 find
    nothing and phase 3 selects `j(String, String...)` - genuine recursion. An
    earlier revision suppressed this on arity alone; that was unsound and was
    withdrawn.
    """
    sample = tmp_path / "Varargs.java"
    sample.write_text(
        'class A {\n    static String j(int a, int b, int c) { return ""; }\n    static String j(String a, String... rest) { return j(a, "b", "c"); }\n}\n',
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_cast_rule_treats_java_lang_object_as_object(tmp_path: Path) -> None:
    """A parameter declared `java.lang.Object` accepts an `(Object)` cast.

    Comparing the raw source text reads the two spellings as different types and
    silences a genuine self-call.
    """
    sample = tmp_path / "Fqn.java"
    sample.write_text(
        "class A {\n    static Object f(java.lang.Object a, int i) { return f((Object) a, i); }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_overloaded_name_with_no_same_arity_rival_is_not_hedged(tmp_path: Path) -> None:
    """Ambiguity is a per-call question, not a per-name one.

    A type holding `f(int)` and `f(int, int)` has an overloaded name, but a
    one-argument call inside `f(int)` has exactly one candidate, so the message
    must not hedge.
    """
    sample = tmp_path / "ArityRival.java"
    sample.write_text(
        "class A {\n    int f(int n) { return f(n); }\n    int f(int a, int b) { return 0; }\n}\n",
        encoding="utf-8",
    )
    found = _safe105(_engine().check_file(str(sample)))
    assert len(found) == 1
    assert found[0].message.startswith('Function "f" calls itself;')


def test_java_varargs_rival_can_claim_a_wider_arity(tmp_path: Path) -> None:
    """A varargs sibling accepts any count from its fixed prefix up, so it is a rival.

    `g(int, Object...)` can take a one-argument call, so the call inside `g(int)`
    has two candidates and the message hedges.
    """
    sample = tmp_path / "VarargsRival.java"
    sample.write_text(
        "class A {\n    int g(int n) { return g(n); }\n    int g(int a, Object... rest) { return 0; }\n}\n",
        encoding="utf-8",
    )
    found = _safe105(_engine().check_file(str(sample)))
    assert len(found) == 1
    assert "overloaded in this type" in found[0].message


def test_java_varargs_without_a_fixed_arity_sibling_still_fires(tmp_path: Path) -> None:
    """With no fixed-arity candidate, phase 3 selects the varargs method itself.

    The negative control for the rule above: remove the sibling and the same call
    is genuine recursion.
    """
    sample = tmp_path / "VarargsOnly.java"
    sample.write_text(
        'class A {\n    static String j(String a, String... rest) { return j(a, "b", "c"); }\n}\n',
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_overloaded_name_reports_that_the_target_is_unresolvable(tmp_path: Path) -> None:
    """A same-arity call to an overloaded name is reported, but not as certain recursion.

    Neither silence nor a flat assertion is honest here: the call may reach the
    sibling, and safelint cannot tell without a classpath. Suppressing instead
    would silence genuine recursion in any overloaded method.
    """
    sample = tmp_path / "Amb.java"
    sample.write_text(
        "class A {\n    int f(int a, int b) { return f(a, b); }\n    int f(String a, String b) { return 0; }\n}\n",
        encoding="utf-8",
    )
    found = _safe105(_engine().check_file(str(sample)))
    assert len(found) == 1
    assert "overloaded in this type" in found[0].message
    assert "cannot be resolved without type information" in found[0].message


def test_java_sole_declaration_asserts_recursion_outright(tmp_path: Path) -> None:
    """When the name is declared once, the call provably is recursion, so say so.

    The counterpart to the test above, and the reason the message is split rather
    than weakened everywhere: `getAllInterfaces` in Commons Lang's `ClassUtils` is
    real recursion and should read as such.
    """
    sample = tmp_path / "Sole.java"
    sample.write_text("class A {\n    int fact(int n) { return n * fact(n - 1); }\n}\n", encoding="utf-8")
    found = _safe105(_engine().check_file(str(sample)))
    assert len(found) == 1
    assert found[0].message.startswith('Function "fact" calls itself;')
    assert "overloaded" not in found[0].message


def test_java_explicit_receiver_parameter_is_not_counted_as_an_argument(tmp_path: Path) -> None:
    """An explicit receiver parameter is never passed at the call site.

    Java 8's `void tick(Outer Outer.this, int n)` form parses the receiver as a
    `receiver_parameter` named child of `formal_parameters`, so counting it makes
    the two-parameter signature look like a mismatch against the one-argument
    self-call and silences genuine recursion.
    """
    sample = tmp_path / "Recv.java"
    sample.write_text(
        "class Outer {\n    void tick(Outer Outer.this, int n) { if (n > 0) tick(n - 1); }\n}\n",
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_java_receiver_parameter_with_real_arity_mismatch_is_still_silent(tmp_path: Path) -> None:
    """Discounting the receiver must not disable the arity check itself.

    The negative control for the test above: with the receiver excluded the
    signature takes one argument, so a two-argument call is a different overload.
    """
    sample = tmp_path / "RecvOver.java"
    sample.write_text(
        "class Outer {\n    void tick(Outer Outer.this, int n) { tick(n, n); }\n    void tick(int a, int b) {}\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


# ---------------------------------------------------------------------------
# Rust: a bare call inside an impl / trait, and a function-local `use`
# ---------------------------------------------------------------------------


def test_rust_bare_call_in_impl_method_is_not_recursion(tmp_path: Path) -> None:
    """A bare call inside an inherent method can never reach the method itself.

    Calling it requires `self.name()` or `Type::name(..)`, so a bare `name(..)`
    always resolves to a free function or an import. Issue #160.
    """
    sample = tmp_path / "impl.rs"
    sample.write_text(
        'impl Script {\n    pub fn schema_hash(&self) -> String { schema_hash("x") }\n}\n',
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_bare_call_in_trait_default_method_is_not_recursion(tmp_path: Path) -> None:
    """A trait default method has the same reachability rule as an inherent one."""
    sample = tmp_path / "trait.rs"
    sample.write_text("trait T {\n    fn render(&self) -> String { render() }\n}\n", encoding="utf-8")
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_self_qualified_method_call_still_fires(tmp_path: Path) -> None:
    """`self.name()` inside an impl IS recursion - the suppression is bare-call only."""
    sample = tmp_path / "selfcall.rs"
    sample.write_text("impl S {\n    fn walk(&self) { self.walk(); }\n}\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_free_function_recursion_still_fires(tmp_path: Path) -> None:
    """A free function calling itself is unaffected by the impl rule."""
    sample = tmp_path / "free.rs"
    sample.write_text("fn real(n: u32) -> u32 { if n == 0 { 0 } else { real(n - 1) } }\n", encoding="utf-8")
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_function_local_use_shadows_the_name(tmp_path: Path) -> None:
    """A `use` inside the body rebinds the name for the rest of the block.

    This exact shape is in ripgrep (`crates/ignore/src/walk.rs`). Issue #173.
    """
    sample = tmp_path / "localuse.rs"
    sample.write_text(
        "fn symlink(a: u32, b: u32) -> u32 {\n    use std::os::unix::fs::symlink;\n    symlink(a, b)\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_function_local_use_list_shadows_the_name(tmp_path: Path) -> None:
    """A brace list binds each name in it, so `use p::{symlink, other}` shadows too."""
    sample = tmp_path / "uselist.rs"
    sample.write_text(
        "fn symlink(a: u32) -> u32 {\n    use std::os::unix::fs::{symlink, chown};\n    symlink(a)\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_function_local_use_alias_shadows_the_name(tmp_path: Path) -> None:
    """With `use p::inner as name`, the ALIAS is what binds the bare identifier."""
    sample = tmp_path / "usealias.rs"
    sample.write_text(
        "fn hash(a: u32) -> u32 {\n    use crate::other::compute as hash;\n    hash(a)\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_unrelated_local_use_does_not_silence_recursion(tmp_path: Path) -> None:
    """A `use` of a DIFFERENT name must not suppress a genuine self-call.

    The negative control for the shadowing check: importing something unrelated
    leaves the bare identifier bound to the enclosing function.
    """
    sample = tmp_path / "unrelated.rs"
    sample.write_text(
        'fn walk(n: u32) -> u32 {\n    use std::fs::read_dir;\n    let _ = read_dir(".");\n    walk(n - 1)\n}\n',
        encoding="utf-8",
    )
    assert len(_safe105(_engine().check_file(str(sample)))) == 1


def test_rust_use_in_a_nested_block_does_not_silence_a_call_outside_it(tmp_path: Path) -> None:
    """A `use` is an item, so it binds throughout its own block but no further.

    Treating any import anywhere in the body as function-wide hides the genuine
    recursion on the last line, which is the failure mode the shadowing check
    exists to avoid creating.
    """
    sample = tmp_path / "nestedblock.rs"
    sample.write_text(
        "fn walk(n: u32) -> u32 {\n    { use std::fs::walk; let _ = walk; }\n    walk(n - 1)\n}\n",
        encoding="utf-8",
    )
    assert [v.lineno for v in _safe105(_engine().check_file(str(sample)))] == [3]


def test_rust_use_in_a_nested_block_still_silences_a_call_inside_it(tmp_path: Path) -> None:
    """Within the shadowing block the bare name does resolve to the import.

    The positive half of the scoping rule: the span is the block, not the file and
    not the whole function.
    """
    sample = tmp_path / "insideblock.rs"
    sample.write_text(
        "fn walk(n: u32) -> u32 {\n    { use std::fs::walk; let _ = walk(n); }\n    n\n}\n",
        encoding="utf-8",
    )
    assert _safe105(_engine().check_file(str(sample))) == []


def test_rust_aliased_use_does_not_bind_the_paths_final_segment(tmp_path: Path) -> None:
    """`use other::bar as helper` binds `helper`, not `bar`.

    Collecting every identifier under the `use` reads the path's trailing segment
    as bound, which silences a genuine `bar()` self-call in `fn bar`.
    """
    sample = tmp_path / "aliaspath.rs"
    sample.write_text(
        "fn bar(n: u32) -> u32 {\n    use other::bar as helper;\n    let _ = helper;\n    bar(n - 1)\n}\n",
        encoding="utf-8",
    )
    assert [v.lineno for v in _safe105(_engine().check_file(str(sample)))] == [4]
