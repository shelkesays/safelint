"""SAFE000 message wording: the C / C++ preprocessor hint (#206).

``Parse error (syntax error) at line N - check syntax near this location`` is a
false accusation on C and C++. Tree-sitter reads the source as written, before
any build step, so ordinary preprocessor use that a compiler accepts after
``cpp`` has run is not standalone-valid to the parser. Measured on four real
projects this is 25-54% of their files, so the generic advice sends the user
hunting for a syntax error that does not exist.

These tests pin the four shapes #206 collected from curl (they are the evidence
the wording rests on), the per-language routing, and the fact that no other
language's message changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import CPP, C, get_language_for_file, supported_extensions


if TYPE_CHECKING:
    from pathlib import Path

    from safelint.languages import LanguageDefinition


_GENERIC_ADVICE = "check syntax near this location"
_C_HINT = "safelint parses C without running the preprocessor"
_CPP_HINT = "safelint parses C++ without running the preprocessor"

# The four causes #206 traced on curl, each valid C that a compiler accepts.
# Kept verbatim in spirit (trimmed to the construct) so a future grammar bump
# that starts parsing one of them shows up here as a failure to investigate
# rather than as a silently weaker claim in the docs.
_CURL_SHAPES: tuple[list[str], ...] = (
    [
        "conditional compilation inside an expression",
        "int check(struct ip *ip)\n{\n  if(ip->maskbits <= 0 ||\n#ifdef AF_INET6\n     (ip->family == AF_INET6) ||\n#endif\n     ip->maskbits > 32)\n    return 1;\n  return 0;\n}\n",
    ],
    [
        "a function-like macro standing in for parameters",
        "static void timer_cb(EV_P_ struct ev_timer *w, int revents)\n{\n  return;\n}\n",
    ],
    [
        "a guarded attribute before a declaration",
        "#if defined(__GNUC__)\n__attribute__((format(printf, 2, 3)))\n#endif\nstatic int mem_addf(struct mem *mem, const char *format, ...)\n{\n  return 0;\n}\n",
    ],
    [
        "a clang builtin with non-C argument syntax",
        "int probe(void)\n{\n  if(__builtin_available(macOS 10.12, iOS 5, *)) {}\n  return 0;\n}\n",
    ],
)


def _engine() -> SafetyEngine:
    """SafetyEngine on stock defaults (the configuration #206 measured)."""
    return SafetyEngine(deep_merge(DEFAULTS, {}))


def _definition_for(extension: str) -> LanguageDefinition:
    """Resolve *extension* through the public lookup, asserting it is registered."""
    lang = get_language_for_file(f"probe{extension}")
    assert lang is not None, f"{extension} is in supported_extensions() but resolved to None"
    return lang


def _parse_error_message(tmp_path: Path, name: str, source: str) -> str:
    """Lint *source* as *name* and return its single SAFE000 message."""
    sample = tmp_path / name
    sample.write_text(source, encoding="utf-8")
    parse_errors = [v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE000"]
    assert len(parse_errors) == 1, f"expected exactly one SAFE000 on {name}, got {len(parse_errors)}"
    return parse_errors[0].message


@pytest.mark.parametrize(["description", "source"], _CURL_SHAPES)
def test_curl_shapes_get_the_preprocessor_hint_not_check_syntax(tmp_path: Path, description: str, source: str) -> None:
    """Each cause #206 traced is valid C, so the message must not blame the user."""
    message = _parse_error_message(tmp_path, "shape.c", source)

    assert _C_HINT in message, f"{description}: expected the preprocessor hint, got {message!r}"
    assert _GENERIC_ADVICE not in message, f"{description}: still telling the user to check syntax"


def test_cpp_source_names_cpp_in_the_hint(tmp_path: Path) -> None:
    """The hint carries the language's own display name, not a shared 'C/C++'."""
    message = _parse_error_message(tmp_path, "shape.cc", "static void timer_cb(EV_P_ int revents)\n{\n}\n")

    assert _CPP_HINT in message
    assert _C_HINT not in message  # "C++" must not be reported as plain C


def test_h_header_gets_the_c_hint(tmp_path: Path) -> None:
    """``.h`` routes to C (the documented header-ownership limitation), hint included.

    Headers are where the share is highest - #206's corrected figures put fmt
    at 24 failing ``.h`` against 19 ``.cc`` - so this is the path that matters
    most, not an edge case.
    """
    message = _parse_error_message(tmp_path, "shape.h", "static void cb(EV_P_ int revents)\n{\n}\n")

    assert _C_HINT in message


def test_other_languages_keep_the_generic_advice(tmp_path: Path) -> None:
    """Python has no preprocessor; its parse errors really are syntax errors."""
    message = _parse_error_message(tmp_path, "broken.py", "def foo(\n")

    assert _GENERIC_ADVICE in message
    assert "preprocessor" not in message


def test_the_kind_hint_and_location_survive_the_new_wording(tmp_path: Path) -> None:
    """Only the trailing advice changed: kind, line and column are still reported."""
    sample = tmp_path / "shape.c"
    sample.write_text("static void timer_cb(EV_P_ int revents)\n{\n}\n", encoding="utf-8")

    violation = next(v for v in _engine().check_file(str(sample)).violations if v.code == "SAFE000")

    assert violation.message.startswith("Parse error (syntax error) at line 1, column ")
    assert violation.lineno == 1
    assert violation.column_start == violation.column_end  # zero-width caret, unchanged


def test_a_genuine_c_syntax_error_also_gets_the_hint(tmp_path: Path) -> None:
    """Known limitation, recorded deliberately rather than papered over.

    The hint is per-language, not per-cause: safelint cannot tell "valid code
    the preprocessor would fix" from "actually broken code", because both
    arrive as the same ERROR node. Naming the likelier cause is still the
    better default at a 25-54% rate, but a real typo now reads as a possible
    preprocessor issue. Item 4 of #206 (a preprocessor-tolerant pass) is what
    would let the two be distinguished.
    """
    message = _parse_error_message(tmp_path, "typo.c", "int broken( {\n")

    assert _C_HINT in message


def test_only_c_and_cpp_carry_a_parse_error_hint() -> None:
    """Drift guard: a new language must decide explicitly, not inherit the hint.

    ``parse_error_hint`` defaults to None, so a language added later keeps the
    generic wording unless its author opts in. This asserts the current opt-in
    set so widening it is a visible change.
    """
    hinted = {ext for ext in supported_extensions() if _definition_for(ext).parse_error_hint is not None}

    assert hinted == {".c", ".h", ".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"}
    assert C.parse_error_hint is not None
    assert CPP.parse_error_hint is not None
    assert _definition_for(".py").parse_error_hint is None
