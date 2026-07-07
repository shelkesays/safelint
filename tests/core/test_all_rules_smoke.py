"""Per-language "enable EVERY rule" engine smoke test.

For each registered language, enable every rule in ``DEFAULTS["rules"]`` (flip
``enabled: true`` across the board) and run the engine end-to-end on a small
valid sample file. The assertion is simply that the run completes and returns a
result: a rule that claims a language in its ``language`` tuple but crashes when
actually dispatched on that language's AST (an opt-in / disabled-by-default rule
that the standard suites never exercise) would raise here.

Parametrised over the language registry so the next language addition gets its
row for free - add a ``(name, extension, sample)`` entry when registering a
language.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import supported_extensions


if TYPE_CHECKING:
    from pathlib import Path


# One tiny, valid sample per registered language. Kept deliberately minimal:
# the point is to dispatch every enabled rule, not to trip any particular one.
_SAMPLES: dict[str, tuple[str, str]] = {
    "python": (".py", "def f():\n    return 1\n"),
    "javascript": (".js", "function f() {\n    return 1;\n}\n"),
    "typescript": (".ts", "function f(): number {\n    return 1;\n}\n"),
    "java": (".java", "class A {\n    int f() {\n        return 1;\n    }\n}\n"),
    "rust": (".rs", "fn f() -> i32 {\n    1\n}\n"),
    "go": (".go", "package main\n\nfunc f() int {\n    return 1\n}\n"),
    "php": (".php", "<?php\nfunction f() {\n    return 1;\n}\n"),
    "c": (".c", "int f(void) {\n    return 0;\n}\n"),
    "cpp": (".cpp", "int f() {\n    return 0;\n}\n"),
}


def _all_rules_enabled_engine() -> SafetyEngine:
    """SafetyEngine with every rule in DEFAULTS flipped on."""
    overrides = {"rules": {name: {"enabled": True} for name in DEFAULTS["rules"]}}
    return SafetyEngine(deep_merge(DEFAULTS, overrides))


def test_every_registered_language_has_a_smoke_sample() -> None:
    """Every registered language has a smoke sample here.

    Guards against a new language being registered without a row in ``_SAMPLES``
    (which would otherwise silently skip the all-rules dispatch for it). The
    check runs in both directions: every sample extension must be registered,
    and every registered language must have a sample.
    """
    from safelint.languages import get_language_for_file  # noqa: PLC0415

    sample_exts = {ext for ext, _ in _SAMPLES.values()}
    # Every sample extension must actually be registered/installed.
    assert sample_exts.issubset(supported_extensions())
    # Every registered language (resolved from its extensions) must have a
    # sample row - a new language addition without one fails here.
    registered_langs = {get_language_for_file(f"x{ext}").name for ext in supported_extensions()}
    missing = registered_langs - set(_SAMPLES)
    assert not missing, f"registered languages without an all-rules smoke sample: {sorted(missing)}"


@pytest.mark.parametrize(["lang_name", "spec"], list(_SAMPLES.items()))
def test_all_rules_enabled_run_completes(lang_name: str, spec: tuple[str, str], tmp_path: Path) -> None:
    """Enabling every rule and running the engine on a valid sample never crashes."""
    extension, source = spec
    sample = tmp_path / f"sample{extension}"
    sample.write_text(source, encoding="utf-8")
    result = _all_rules_enabled_engine().check_file(str(sample))
    # A clean, tiny sample should not raise and should not spuriously error out
    # with a parse failure (SAFE000).
    codes = {v.code for v in result.violations}
    assert "SAFE000" not in codes, f"{lang_name} sample failed to parse under all-rules config"
