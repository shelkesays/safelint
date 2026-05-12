"""End-to-end smoke tests for TypeScript discovery and rule dispatch.

These are the "Slice 1 / Foundation" tests: they verify that ``.ts``,
``.tsx``, and ``.as`` files are discovered, parsed via the right
Tree-sitter grammar, and routed to the JavaScript-family rule
implementations. Detailed per-rule TS behaviour is tested in the
per-rule test files (``test_*_typescript.py`` in the rules folder)
once Slice 2 lands TS-specific tweaks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine
from safelint.languages import TSX, TYPESCRIPT, get_language_for_file, supported_extensions


# ---------------------------------------------------------------------------
# Registry plumbing
# ---------------------------------------------------------------------------


def test_typescript_extensions_in_supported_extensions() -> None:
    """``.ts``, ``.tsx``, and ``.as`` are registered and discoverable."""
    exts = supported_extensions()
    assert ".ts" in exts
    assert ".tsx" in exts
    assert ".as" in exts


def test_typescript_extension_maps_to_typescript_definition() -> None:
    """``.ts`` and ``.as`` route to the ``TYPESCRIPT`` (non-TSX) grammar."""
    ts_lang = get_language_for_file("foo.ts")
    as_lang = get_language_for_file("foo.as")
    assert ts_lang is TYPESCRIPT
    assert as_lang is TYPESCRIPT
    assert ts_lang.name == "typescript"


def test_tsx_extension_maps_to_tsx_definition() -> None:
    """``.tsx`` routes to the ``TSX`` grammar (separate parser) but shares the ``typescript`` logical name."""
    tsx_lang = get_language_for_file("foo.tsx")
    assert tsx_lang is TSX
    assert tsx_lang.name == "typescript"


# ---------------------------------------------------------------------------
# End-to-end: a real TS file fires the expected rules
# ---------------------------------------------------------------------------


def test_typescript_file_function_length_violation_fires(tmp_path: Path) -> None:
    """A long TS function fires SAFE101 — the JS rule implementation is reused."""
    long_body = "\n".join(f"  const x{i}: number = {i};" for i in range(65))
    sample = tmp_path / "big.ts"
    sample.write_text(
        f"function tooLong(): void {{\n{long_body}\n}}\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert any(v.code == "SAFE101" for v in result.violations)


def test_typescript_file_nesting_depth_violation_fires(tmp_path: Path) -> None:
    """Deeply-nested TS control flow fires SAFE102 — same dispatch path as JS."""
    sample = tmp_path / "deep.ts"
    sample.write_text(
        "function deep(x: number): void {\n  if (x > 0) {\n    for (let i = 0; i < 10; i++) {\n      while (i < x) {\n        process(i);\n      }\n    }\n  }\n}\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert any(v.code == "SAFE102" for v in result.violations)


def test_typescript_var_declaration_fires_safe305(tmp_path: Path) -> None:
    """``var`` in TS still fires SAFE305 — TS users should prefer ``let`` / ``const``."""
    sample = tmp_path / "vary.ts"
    sample.write_text(
        "function f(): number {\n  var x: number = 1;\n  return x;\n}\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    assert any(v.code == "SAFE305" for v in result.violations)


def test_tsx_file_with_jsx_parses_and_dispatches(tmp_path: Path) -> None:
    """A ``.tsx`` file with JSX content routes through the TSX grammar and is linted.

    Regression guard for the two-grammar split: if ``.tsx`` were incorrectly
    routed to the plain TypeScript grammar, the JSX tokens would produce
    parse errors. The file below has JSX *and* a SAFE101-triggering long
    function; we verify the file parses cleanly (no SAFE000 parse error)
    AND that the function-length rule still fires correctly.
    """
    long_body = "\n".join(f"  const x{i}: number = {i};" for i in range(65))
    sample = tmp_path / "comp.tsx"
    sample.write_text(
        f"function MyComponent(): JSX.Element {{\n{long_body}\n  return <div>hello</div>;\n}}\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    # No parse errors — TSX grammar handled the JSX.
    assert not any(v.code == "SAFE000" for v in result.violations), f"TSX file produced parse errors: {[v for v in result.violations if v.code == 'SAFE000']}"
    # Function-length rule still fires through the JS-family dispatch.
    assert any(v.code == "SAFE101" for v in result.violations)


def test_assemblyscript_file_parses_as_typescript(tmp_path: Path) -> None:
    """``.as`` files parse with the TypeScript grammar (AssemblyScript is a TS subset)."""
    sample = tmp_path / "math.as"
    sample.write_text(
        # AssemblyScript-flavoured but valid TS — ``i32`` is a type alias in AS;
        # the TS grammar doesn't know the alias but accepts it as a normal type ref.
        "export function add(a: i32, b: i32): i32 {\n  return a + b;\n}\n",
        encoding="utf-8",
    )
    result = SafetyEngine(DEFAULTS).check_file(str(sample))
    # No parse errors — TS grammar handled the AS source.
    assert not any(v.code == "SAFE000" for v in result.violations)
