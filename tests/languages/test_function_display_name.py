"""A named function expression is reported by its binding, not ``<anonymous>`` (#165).

Modern JavaScript and TypeScript declare most functions as an expression bound
to a name - ``const Footer = () => {}`` - and an ``arrow_function`` has no
``name`` field of its own. Every per-function rule read that field alone, so on
a real project 8 of 8 SAFE101 findings said ``Function "<anonymous>"`` although
the source named every one. Measured across the JavaScript and TypeScript
corpora, the shared resolver renames 380 findings.

Two things are deliberately NOT changed, and both are pinned here, because
either would be a silent behaviour change rather than a better message:

* a genuinely nameless function keeps ``<anonymous>``; inventing a label for an
  IIFE or an inline callback would be worse than an honest absence.
* SAFE601 still identifies a test by the function's OWN name. A binding that
  happens to start with ``test`` is just a variable in JavaScript, and the
  ecosystem identifies tests by the registration call instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _messages(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return every violation message for *sample*."""
    engine = SafetyEngine(deep_merge(DEFAULTS, overrides or {}))
    return [v.message for v in engine.check_file(str(sample)).violations]


def _long_body(statement: str, lines: int = 70) -> str:
    """Return *lines* copies of *statement*, enough to trip SAFE101's 60-line limit."""
    return "\n".join(f"  {statement}" for _ in range(lines))


_NAMED_BINDINGS: list[tuple[str, str, str]] = [
    ("const arrow", "const Footer = () => {{\n{body}\n}};\n", "Footer"),
    ("let arrow", "let ArchivePage = ({{ data }}) => {{\n{body}\n}};\n", "ArchivePage"),
    ("const function expression", "const Jobs = function () {{\n{body}\n}};\n", "Jobs"),
    ("var function expression", "var Legacy = function () {{\n{body}\n}};\n", "Legacy"),
    ("object-literal arrow", "export const api = {{\n  loadUser: () => {{\n{body}\n  }},\n}};\n", "loadUser"),
    ("object-literal function expression", "export const api = {{\n  saveUser: function () {{\n{body}\n  }},\n}};\n", "saveUser"),
]


@pytest.mark.parametrize(["label", "template", "expected"], _NAMED_BINDINGS, ids=[case[0] for case in _NAMED_BINDINGS])
def test_a_named_function_expression_is_reported_by_its_binding(tmp_path: Path, label: str, template: str, expected: str) -> None:
    """SAFE101 names the binding, which is the whole point of the issue."""
    sample = tmp_path / "component.js"
    sample.write_text(template.format(body=_long_body("doWork();")), encoding="utf-8")
    assert _messages(sample) == [f'Function "{expected}" is 72 lines (max 60)'], label


def test_a_genuinely_anonymous_function_still_says_anonymous(tmp_path: Path) -> None:
    """``export default () => {}`` has no name anywhere, so the label must stay honest."""
    sample = tmp_path / "page.js"
    sample.write_text(f"export default () => {{\n{_long_body('doWork();')}\n}};\n", encoding="utf-8")
    assert _messages(sample) == ['Function "<anonymous>" is 72 lines (max 60)']


def test_an_inline_callback_still_says_anonymous(tmp_path: Path) -> None:
    """A callback passed straight into a call is not bound to anything."""
    sample = tmp_path / "handler.js"
    sample.write_text(f"register(() => {{\n{_long_body('doWork();')}\n}});\n", encoding="utf-8")
    assert _messages(sample) == ['Function "<anonymous>" is 72 lines (max 60)']


def test_a_plain_function_declaration_is_unchanged(tmp_path: Path) -> None:
    """The control: the ``name`` field path must keep working exactly as before."""
    sample = tmp_path / "util.js"
    sample.write_text(f"function doEverything() {{\n{_long_body('doWork();')}\n}}\n", encoding="utf-8")
    assert _messages(sample) == ['Function "doEverything" is 72 lines (max 60)']


_PER_FUNCTION_RULES: list[tuple[str, str, str]] = [
    (
        "SAFE102 nesting_depth",
        "const render = () => {\n  if (a) {\n    if (b) {\n      if (c) {\n        doWork();\n      }\n    }\n  }\n};\n",
        'Function "render" nesting depth is 3 (max 2)',
    ),
    (
        "SAFE103 max_arguments",
        "const build = (a, b, c, d, e, f, g, h) => {\n  return a;\n};\n",
        'Function "build" has 8 arguments (max 7)',
    ),
]


@pytest.mark.parametrize(["label", "source", "expected"], _PER_FUNCTION_RULES, ids=[case[0] for case in _PER_FUNCTION_RULES])
def test_every_per_function_rule_shares_the_resolver(tmp_path: Path, label: str, source: str, expected: str) -> None:
    """One resolver, so a rule cannot regress to the naive lookup on its own.

    Six rules each carried their own copy of ``name_node or "<anonymous>"``
    before this, which is how the issue came to affect all of them at once.
    """
    sample = tmp_path / "widget.js"
    sample.write_text(source, encoding="utf-8")
    assert _messages(sample) == [expected], label


def test_an_io_named_binding_is_now_exempt_from_safe304(tmp_path: Path) -> None:
    """The one place the resolved name changes a verdict rather than a message.

    SAFE304 exempts a function whose name already signals I/O, so the user is
    not told to rename ``readFile`` to signal what it plainly signals. While the
    name read ``<anonymous>`` the exemption could never match, so the rule
    reported exactly the functions it is written to leave alone. Taken from the
    corpus: this is Vue core's ``vite.config.ts`` and, with ``sendCode``, the
    Cloudflare templates repo.
    """
    exempt = tmp_path / "config.js"
    exempt.write_text("export const fs = {\n  readFile: (file) => nodeFs.readFileSync(file, 'utf-8'),\n};\n", encoding="utf-8")
    assert _messages(exempt) == []
    # A name that does NOT signal I/O is still reported, so the exemption has
    # not become a blanket one.
    reported = tmp_path / "other.js"
    reported.write_text("export const fs = {\n  grabThing: (file) => nodeFs.readFileSync(file, 'utf-8'),\n};\n", encoding="utf-8")
    assert _messages(reported) == ['Function "grabThing" calls I/O primitive "readFileSync" - rename to signal intent or use dependency injection']


def test_safe601_identifies_a_test_by_the_declared_name_not_the_binding(tmp_path: Path) -> None:
    """A binding starting with ``test`` is a variable, not a test case.

    The resolver must not reach ``test_function_prefixes``. Measured when it
    did: chartjs read four ``testA:`` / ``testB:`` entries of a TypeScript type
    fixture as tests, and elysia a ``const test = (app) => app.group(...)``
    helper. Five findings, all false, against no true one. JavaScript's real
    test-identity route is the registration call, which SAFE601 handles
    separately.
    """
    rule = {"rules": {"missing_assertions": {"enabled": True}}}
    binding = tmp_path / "thing.test.js"
    binding.write_text("const testHelper = () => {\n  buildFixture();\n};\n", encoding="utf-8")
    assert _messages(binding, rule) == []
    pair = tmp_path / "types.test.js"
    pair.write_text("const impl = {\n  testA: (ctx) => ctx.parsed,\n};\n", encoding="utf-8")
    assert _messages(pair, rule) == []
    # A registered test in the same file is still found, so the rule has not
    # gone blind in the shapes that matter.
    registered = tmp_path / "real.test.js"
    registered.write_text("test('adds', () => {\n  compute(1);\n});\n", encoding="utf-8")
    assert _messages(registered, rule) == ['Test "adds" has no assertions']


def test_safe601_still_labels_a_reported_binding_by_name(tmp_path: Path) -> None:
    """Identity is one question and the label is another; only identity is held back.

    With ``test_functions_only = false`` the rule checks every function, so this
    pins that a reported binding is still named in the message - the usability
    fix reaches SAFE601 too, even though the prefix route does not.
    """
    sample = tmp_path / "math.js"
    sample.write_text("const addNumbers = (a, b) => {\n  return a + b;\n};\n", encoding="utf-8")
    overrides = {"rules": {"missing_assertions": {"enabled": True, "test_functions_only": False}}}
    assert _messages(sample, overrides) == ['Function "addNumbers" has no assertions']
