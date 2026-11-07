"""SAFE000 on a Rust macro named after a primitive type (#174).

``str![...]`` is snapbox's inline-snapshot macro and it cannot be parsed by
``tree-sitter-rust``: the lexer resolves ``str`` as a type token before it can
be a macro identifier, and ``<primitive> !`` is not a valid invocation in the
grammar. The whole file then gets a ``SAFE000`` and **no analysis at all**,
which is worse than a false positive: a false positive is visible and
suppressible, this silently removes a file. On the Ruff run that found it, three
such errors sat among 6,066 findings.

Still unfixable by a dependency bump: tree-sitter-rust 0.24.2 is the latest
release on PyPI and still fails. So what safelint can control is the *message* -
"check syntax near this location" points the reader at correct Rust.

The risk in a per-cause detector is the opposite error: telling someone there is
"nothing here to fix" when their code really is broken. That is what most of
this file guards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import RUST
from safelint.languages.rust import _PRIMITIVE_TYPE_NAMES, primitive_macro_parse_cause


if TYPE_CHECKING:
    from pathlib import Path


_GENERIC = "check syntax near this location"
_CAUSE = "cannot be parsed by tree-sitter-rust"


def _engine() -> SafetyEngine:
    """Engine on stock defaults."""
    return SafetyEngine(deep_merge(DEFAULTS, {}))


def _message(tmp_path: Path, source: str, name: str = "sample.rs") -> str:
    """Lint *source* and return its single SAFE000 message."""
    sample = tmp_path / name
    sample.write_text(source, encoding="utf-8")
    parse_errors = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE000"]
    assert len(parse_errors) == 1, f"expected one SAFE000, got {len(parse_errors)}"
    return parse_errors[0].message


def _cause(source: str) -> str | None:
    """Run the detector directly against *source*."""
    return primitive_macro_parse_cause(RUST.create_parser().parse(source.encode()).root_node)


# ── the three delimiter forms, which recover differently ─────────────────────


@pytest.mark.parametrize(
    ["label", "source"],
    (
        ["bracket, the snapbox shape", "fn t() {\n    let s = str![[1]];\n}\n"],
        ["bracket, single", "fn t() {\n    let s = str![1];\n}\n"],
        ["paren", "fn t() {\n    let s = str!(1);\n}\n"],
        ["brace", "fn t() {\n    let s = str!{1};\n}\n"],
    ),
)
def test_every_delimiter_form_is_recognised(label: str, source: str) -> None:
    """All three macro delimiters must be caught, because they recover differently.

    The bracket and paren forms leave the bare ``!`` as the ``ERROR`` with the
    name as its previous sibling; the brace form puts the NAME in the error
    node instead. Missing the second shape would have left ``str!{...}`` on the
    generic advice.
    """
    assert _cause(source) is not None, f"{label}: not recognised"


@pytest.mark.parametrize("primitive", tuple(sorted(_PRIMITIVE_TYPE_NAMES)))
def test_every_primitive_name_is_recognised(primitive: str) -> None:
    """The trigger is the name being a primitive, so the whole set must match.

    Driven from ``_PRIMITIVE_TYPE_NAMES`` rather than a hand-written list.
    The list held 8 of the 17 names while the docstring claimed the whole set,
    so a regression in any of the other nine would have passed (#276 review).
    Sourcing it from the constant means adding a name adds a case for free.
    """
    assert _cause(f"fn t() {{\n    let s = {primitive}![1];\n}}\n") is not None


def test_the_snapbox_reproducer_from_the_issue_gets_the_specific_advice(tmp_path: Path) -> None:
    """End to end on the exact source #174 reported, raw string and all."""
    source = 'fn t() {\n    let expected = str![[r#"\nerror: oops\n"#]];\n}\n'

    message = _message(tmp_path, source)

    assert _CAUSE in message
    assert "nothing here to fix" in message
    assert _GENERIC not in message


# ── the important half: a real mistake must NOT be excused ───────────────────


@pytest.mark.parametrize(
    ["label", "source"],
    (
        ["unbalanced paren", "fn broken( {\n    let x = 1;\n}\n"],
        ["missing semicolon", "fn t() {\n    let x = 1\n}\n"],
        ["stray brace", "fn t() {\n    let x = 1;\n}\n}\n"],
        ["unclosed string", 'fn t() {\n    let x = "oops;\n}\n'],
        ["non-primitive macro, genuinely broken", "fn t() {\n    let s = foo![1;\n}\n"],
    ),
)
def test_a_genuine_syntax_error_keeps_the_generic_advice(tmp_path: Path, label: str, source: str) -> None:
    """Telling someone their broken code is fine would be worse than the original bug.

    The detector is narrow by construction - a missing token carries empty
    text, and an unbalanced delimiter puts unrelated nodes either side - but
    "narrow by construction" is exactly the claim a test should check rather
    than accept.
    """
    assert _cause(source) is None, f"{label}: wrongly excused as a primitive-macro failure"


def test_a_genuine_error_message_is_unchanged_end_to_end(tmp_path: Path) -> None:
    """The generic path still produces the original wording."""
    message = _message(tmp_path, "fn broken( {\n    let x = 1;\n}\n", name="typo.rs")

    assert _GENERIC in message
    assert _CAUSE not in message


def test_valid_rust_has_no_parse_error_at_all(tmp_path: Path) -> None:
    """No new noise: a clean file stays clean."""
    sample = tmp_path / "ok.rs"
    sample.write_text("fn ok() -> i32 {\n    1\n}\n", encoding="utf-8")

    assert not [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE000"]


def test_a_macro_whose_name_merely_contains_a_primitive_is_not_matched() -> None:
    """``string!`` and ``i32x4!`` are ordinary identifiers and parse fine.

    Guards against a substring check creeping in where an exact match belongs.
    """
    for name in ("string", "i32x4", "stringify", "boolean"):
        source = f"fn t() {{\n    let s = {name}![1];\n}}\n"
        assert not RUST.create_parser().parse(source.encode()).root_node.has_error, f"{name}! should parse"


# ── the tier ordering, which is the part that could silently regress ─────────


def test_rust_has_no_blanket_hint_only_a_cause_detector() -> None:
    """Rust parse failures are usually real, so the unconditional hint stays unset.

    Pinned because adding a ``parse_error_hint`` to Rust would quietly excuse
    every genuine syntax error in the language.
    """
    assert RUST.parse_error_hint is None
    assert RUST.parse_error_cause is primitive_macro_parse_cause


def test_the_c_preprocessor_hint_still_applies(tmp_path: Path) -> None:
    """Tier 2 is intact: C has no cause detector but keeps its blanket hint (#206)."""
    sample = tmp_path / "shape.c"
    sample.write_text("static void cb(EV_P_ int revents)\n{\n}\n", encoding="utf-8")

    message = next(v.message for v in _engine().check_file(str(sample)).violations if v.code == "SAFE000")

    assert "without running the preprocessor" in message


def test_python_still_gets_the_generic_advice(tmp_path: Path) -> None:
    """Tier 3 is intact: a language with neither hook is unchanged."""
    assert _GENERIC in _message(tmp_path, "def broken(\n", name="broken.py")


# ── a file with BOTH problems must not be excused (#275 review) ──────────────


@pytest.mark.parametrize(
    ["label", "source"],
    (
        ["genuine error first", "fn broken( {\n    let x = 1;\n}\nfn t() {\n    let s = str![1];\n}\n"],
        ["macro first", "fn t() {\n    let s = str![1];\n}\nfn broken( {\n    let x = 1;\n}\n"],
    ),
)
def test_a_file_with_a_real_error_too_is_not_excused(label: str, source: str) -> None:
    """ "Nothing here to fix" is only honest when nothing else is broken.

    Returning the advice on the first match was wrong in both directions. With
    the genuine error EARLIER, ``SAFE000`` reports that line while the message
    said there was nothing to fix - pointing at a real mistake and reassuring
    the reader about it. With the macro first, the message is right about its
    own location but still tells someone a broken file is fine.

    So every error in the file has to be the macro shape, including a MISSING
    token, which carries no text and is how an unbalanced delimiter surfaces.
    """
    assert _cause(source) is None, f"{label}: a file with a real error was excused"


def test_the_mixed_file_message_is_the_generic_one_end_to_end(tmp_path: Path) -> None:
    """The user-visible half: such a file keeps "check syntax"."""
    source = "fn broken( {\n    let x = 1;\n}\nfn t() {\n    let s = str![1];\n}\n"

    message = _message(tmp_path, source, name="mixed.rs")

    assert _GENERIC in message
    assert _CAUSE not in message
