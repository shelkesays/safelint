"""TS-specific rule behaviour.

Tests that exercise TypeScript-only syntactic constructs (type
parameters, type annotations, ambient declarations, ``as``
expressions, non-null assertions, decorators) and verify each
cross-language rule does the right thing on them. Covers the
TS-specific handling the JS rule implementations would otherwise
miss — generic type parameters not counting toward
``max_arguments``, ``(globalThis as any).x = 1`` resolving via the
paren / cast unwrap, taint flowing through ``as`` / ``satisfies``
/ ``!``, etc.
"""

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
# SAFE103 max_arguments — generic type parameters must NOT count as arguments
# ---------------------------------------------------------------------------


def test_ts_generic_type_parameters_do_not_count_toward_max_arguments(tmp_path: Path) -> None:
    """``function f<T, U, V, W, X, Y, Z>(a: number)`` — 7 type params + 1 value param.

    Type parameters live in a separate ``type_parameters`` node, not
    inside ``formal_parameters``, so the rule's existing param walk
    should naturally exclude them. This test locks that behaviour.
    """
    sample = tmp_path / "generics.ts"
    sample.write_text(
        "function f<T, U, V, W, X, Y, Z>(a: number): T { return a as unknown as T; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE103" for v in result.violations), "Generic type parameters should not count toward max_arguments"


def test_ts_value_parameters_still_count(tmp_path: Path) -> None:
    """Eight value parameters in TS still fires SAFE103 (default cap is 7)."""
    sample = tmp_path / "manyargs.ts"
    sample.write_text(
        "function f<T>(a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number): T { return a as unknown as T; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE103" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE302 global_mutation — declare global and (globalThis as any).foo
# ---------------------------------------------------------------------------


def test_ts_declare_global_block_does_not_fire_safe302(tmp_path: Path) -> None:
    """``declare global { interface Window { ... } }`` is a type-only TS block.

    Wrapped in an ``ambient_declaration`` node. Contains no
    ``assignment_expression``, so the rule should not fire — the
    block exists at compile time only and has no runtime effect.
    """
    sample = tmp_path / "ambient.ts"
    sample.write_text(
        "declare global { interface Window { myProp: string; } }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE302" for v in result.violations)


def test_ts_runtime_assignment_to_global_via_as_cast_fires(tmp_path: Path) -> None:
    """``(globalThis as any).counter = 1`` — TS users wrap globalThis in an ``as`` cast.

    The LHS chain has ``parenthesized_expression`` → ``as_expression`` →
    ``identifier`` (``globalThis``). The rule's leftward walk must
    unwrap the ``as_expression`` (in addition to the parens that
    already unwrap) to resolve the root identifier; otherwise this
    very common TS pattern silently slips past SAFE302.
    """
    sample = tmp_path / "as_cast.ts"
    sample.write_text(
        "function setUp(): void {\n  (globalThis as any).counter = 1;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE302" for v in result.violations), "(globalThis as any).foo = ... should fire — runtime write to a global namespace"


# ---------------------------------------------------------------------------
# SAFE803 null_dereference — non-null assertion must NOT bypass the check
# ---------------------------------------------------------------------------


def test_ts_non_null_assertion_does_not_bypass_safe803(tmp_path: Path) -> None:
    """``users.find(...)!.name`` — the ``!`` is a TS compile-time annotation.

    At runtime the code is ``users.find(...).name`` — if ``.find()``
    returns ``undefined``, accessing ``.name`` crashes. The ``!`` says
    "trust me it's not null" but provides zero runtime safety. SAFE803
    should still fire because the underlying call IS nullable.

    Tree-sitter wraps the call in a ``non_null_expression`` node:
    ``member_expression(object=non_null_expression(call_expression(...)))``.
    The rule must unwrap ``non_null_expression`` before checking
    whether the object is a nullable call.
    """
    sample = tmp_path / "nonnull.ts"
    sample.write_text(
        "function f(users: any[]): string {\n  return users.find((u: any) => u.id === 1)!.name;\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"null_dereference": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE803" for v in result.violations), "users.find(...)!.name should fire — the ``!`` is a TS-only annotation, not a runtime guard"


def test_ts_optional_chaining_still_does_not_fire(tmp_path: Path) -> None:
    """``users.find(...)?.name`` is the real null-safe form — should NOT fire (positive control)."""
    sample = tmp_path / "optchain.ts"
    sample.write_text(
        "function f(users: any[]): string | undefined {\n  return users.find((u: any) => u.id === 1)?.name;\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"null_dereference": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE803" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE801 tainted_sink — `as` cast must not break taint propagation
# ---------------------------------------------------------------------------


def test_ts_as_expression_preserves_taint(tmp_path: Path) -> None:
    """``eval(userInput as string)`` — the ``as`` cast is type-only, taint flows through.

    Tree-sitter wraps the cast in ``as_expression(identifier, type)``.
    The JS taint tracker doesn't know this node type, so it would
    drop taint without an explicit handler. SAFE801 must still fire
    because at runtime ``userInput as string`` IS ``userInput``.
    """
    sample = tmp_path / "as_taint.ts"
    sample.write_text(
        "function run(userInput: unknown): void {\n  eval(userInput as string);\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations), "eval(userInput as string) should fire — the cast is type-only and taint flows through"


def test_ts_satisfies_expression_preserves_taint(tmp_path: Path) -> None:
    """``eval(userInput satisfies string)`` — ``satisfies`` is another TS-only annotation.

    Like ``as``, ``satisfies`` is compile-time-only and doesn't change
    the runtime value. Taint must propagate through it.
    """
    sample = tmp_path / "satisfies_taint.ts"
    sample.write_text(
        "function run(userInput: string): void {\n  eval(userInput satisfies string);\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_ts_non_null_assertion_preserves_taint(tmp_path: Path) -> None:
    """``eval(userInput!)`` — non-null assertion preserves taint, same reasoning."""
    sample = tmp_path / "nonnull_taint.ts"
    sample.write_text(
        "function run(userInput: string | null): void {\n  eval(userInput!);\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


# ---------------------------------------------------------------------------
# SAFE701 test_existence — must recognise *.test.ts / *.spec.ts patterns
# ---------------------------------------------------------------------------


def test_ts_test_existence_finds_paired_test_ts_file(tmp_path: Path) -> None:
    """``src/foo.ts`` paired with ``tests/foo.test.ts`` — SAFE701 must NOT fire.

    Currently the rule's ``_candidate_test_filenames`` only generates
    JS-extension patterns (.test.js, .spec.cjs, etc.); it doesn't
    know about ``.test.ts`` / ``.spec.tsx`` / ``.test.as``. Result:
    SAFE701 would falsely fire on any TS source file that DOES have
    a paired test, because it's looking for the wrong filenames.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "foo.ts"
    sample.write_text("export function f(): number { return 1; }\n", encoding="utf-8")
    paired = test_dir / "foo.test.ts"
    paired.write_text("import { f } from '../src/foo';\ntest('f', () => {});\n", encoding="utf-8")

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(test_dir)]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE701" for v in result.violations), "src/foo.ts paired with tests/foo.test.ts — SAFE701 should be satisfied"


def test_ts_test_existence_fires_when_no_paired_test(tmp_path: Path) -> None:
    """``src/lonely.ts`` with no paired test — SAFE701 SHOULD fire (positive control)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    sample = src_dir / "lonely.ts"
    sample.write_text("export function f(): number { return 1; }\n", encoding="utf-8")
    # Note: no paired test file created.

    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"test_existence": {"enabled": True, "test_dirs": [str(test_dir)]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE701" for v in result.violations)


# ---------------------------------------------------------------------------
# Sanity: TS-specific syntax that should "just work" via JS dispatch
# ---------------------------------------------------------------------------


def test_ts_decorators_do_not_break_function_dispatch(tmp_path: Path) -> None:
    """``@Component class Foo`` — decorators are class-level metadata; rules ignore them cleanly.

    A long method inside a decorated class should still fire SAFE101.
    The ``decorator`` node is a child of ``class_declaration`` /
    ``method_definition`` / ``public_field_definition`` and doesn't
    affect how the rules walk the function body.
    """
    long_body = "\n".join(f"    const x{i} = {i};" for i in range(65))
    sample = tmp_path / "decorated.ts"
    sample.write_text(
        f"@Component\nclass MyClass {{\n  @Method\n  myMethod(): void {{\n{long_body}\n  }}\n}}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE101" for v in result.violations)


def test_ts_long_type_signature_does_not_inflate_function_length(tmp_path: Path) -> None:
    """A function with a long type signature (one line) and a short body should not fire SAFE101.

    The type annotations are part of the function signature line —
    they don't add to the function body's line count regardless of
    whether they're verbose.
    """
    sample = tmp_path / "longsig.ts"
    sample.write_text(
        "function f<T extends Record<string, unknown>, U extends keyof T>(a: T, b: U, c: T[U], d: Array<T>, e: Promise<T>): Promise<T[U]> {\n  return Promise.resolve(a[b]);\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE101" for v in result.violations)


# ---------------------------------------------------------------------------
# Per-language config precedence: TS → JS fallback
# ---------------------------------------------------------------------------


def test_ts_inherits_javascript_config_when_typescript_key_unset(tmp_path: Path) -> None:
    """A TS file inherits the ``_javascript``-keyed config when ``_typescript`` is not set.

    Default behaviour: ``sinks_javascript = ["eval"]`` (built-in DEFAULTS).
    The TS file's ``eval(userInput)`` should fire SAFE801 because the
    rule reads the JS list via the TS → JS fallback.
    """
    sample = tmp_path / "fallback.ts"
    sample.write_text(
        "function run(userInput: string): void { eval(userInput); }\n",
        encoding="utf-8",
    )
    cfg = deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}})
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations), "TS file with default config should fire SAFE801 — TS inherits sinks_javascript"


def test_ts_typescript_key_overrides_javascript_when_explicitly_set(tmp_path: Path) -> None:
    """When ``sinks_typescript`` is explicitly set, the TS file uses it (NOT the JS list).

    Verifies the override door: the user can split TS-specific sinks
    from JS sinks when they really want different behaviour.
    """
    sample = tmp_path / "override.ts"
    sample.write_text(
        # ``eval`` is in the JS default sinks but NOT in our custom TS list,
        # so SAFE801 should NOT fire (TS-specific list overrides JS default).
        "function run(userInput: string): void { eval(userInput); }\n",
        encoding="utf-8",
    )
    cfg = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "tainted_sink": {
                    "enabled": True,
                    # Override: TS-specific list — only "myCustomDangerous" is a sink.
                    "sinks_typescript": ["myCustomDangerous"],
                }
            }
        },
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE801" for v in result.violations), "sinks_typescript explicit override should replace the JS list — eval should NOT fire"


def test_ts_typescript_key_used_when_javascript_unset(tmp_path: Path) -> None:
    """Setting ``_typescript`` keys without ``_javascript`` keys works for TS files.

    Positive control: confirms the lookup is ``ts_key first, then js_key``,
    not ``js_key always (with ts_key only being a sometimes-overlay)``.
    """
    sample = tmp_path / "tsonly.ts"
    sample.write_text(
        "function run(userInput: string): void { customTsSink(userInput); }\n",
        encoding="utf-8",
    )
    cfg = deep_merge(
        DEFAULTS,
        {
            "rules": {
                "tainted_sink": {
                    "enabled": True,
                    "sinks_typescript": ["customTsSink"],
                }
            }
        },
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE801" for v in result.violations)


def test_ts_io_functions_inherits_javascript_default(tmp_path: Path) -> None:
    """SAFE304 on a TS file uses ``io_functions_javascript`` defaults.

    Regression guard: ``side_effects.py:_io_funcs_for_lang`` previously built
    its config key from ``f"io_functions_{lang_name}"``, producing
    ``io_functions_typescript`` for TS files — which has no default.
    The TS→JS fallback in ``get_per_language_config`` restores the
    expected behaviour: TS files see the JS I/O primitive list and
    SAFE304 fires correctly.
    """
    sample = tmp_path / "io.ts"
    # ``console.log`` is in the default ``io_functions_javascript`` list.
    # SAFE304 fires when a function NOT named to signal I/O calls an I/O primitive.
    sample.write_text(
        "function processOrder(order: string): string {\n  console.log(order);\n  return order;\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE304" for v in result.violations), "TS file with default config should fire SAFE304 — TS inherits io_functions_javascript"
