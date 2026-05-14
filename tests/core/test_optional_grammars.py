"""Tests for the optional-grammar / extras packaging model.

v2.0.0 split **every** tree-sitter grammar package out of the base
install into per-language extras - ``[python]`` / ``[javascript]`` /
``[typescript]`` / ``[all]``. The base ``pip install safelint`` ships
the engine only (``tree-sitter>=0.23.0``) and zero grammars; users opt
in to whichever languages their project contains. Python is treated
*symmetrically* with the other languages - there is no always-installed
"core" grammar.

The registry must therefore:

1. Skip every language whose grammar package isn't importable -
   including Python, when ``tree-sitter-python`` isn't installed.
2. Keep those extensions reachable via :func:`unavailable_extensions`
   so the CLI can surface a clear install hint for each one (Python
   shows up here just like JS / TS would).
3. Raise a clear :class:`ImportError` from the parser factory when
   something bypasses the registry filter and tries to construct a
   parser for an unavailable language.

These tests monkeypatch the ``_GRAMMAR_AVAILABLE`` flags + the cached
``tree_sitter.Language`` objects to simulate an install without the
extras, since the dev environment has every grammar installed.
"""

from __future__ import annotations

import importlib
from importlib.metadata import metadata

import pytest

from safelint import languages
from safelint.languages import (
    install_hint_for,
    unavailable_extensions,
)
from safelint.languages import (
    javascript as _javascript_mod,
)
from safelint.languages import (
    python as _python_mod,
)
from safelint.languages import (
    typescript as _typescript_mod,
)


def test_python_parser_factory_raises_when_grammar_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_create_python_parser`` errors clearly when the grammar isn't installed."""
    monkeypatch.setattr(_python_mod, "_PYTHON_TS_LANGUAGE", None)
    with pytest.raises(ImportError, match=r"tree-sitter-python is not installed.*safelint\[python\]"):
        _python_mod._create_python_parser()


def test_python_install_hint_names_the_right_extra() -> None:
    """The hint string matches what users actually need to type."""
    assert _python_mod.GRAMMAR_INSTALL_HINT == "pip install 'safelint[python]'"


def test_registry_skips_python_when_grammar_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the Python grammar isn't installed, ``.py`` / ``.pyw`` are unavailable; other languages stay available.

    Verifies that v2.0.0's fully-symmetric model treats Python like
    any other optional language: a Go-only or JS-only project that
    runs ``pip install 'safelint[javascript]'`` doesn't pay for
    ``tree-sitter-python`` and the registry correctly skips Python
    file discovery.
    """
    monkeypatch.setattr(_python_mod, "_GRAMMAR_AVAILABLE", False)
    reloaded = importlib.reload(languages)
    try:
        assert ".py" not in reloaded.supported_extensions()
        assert ".pyw" not in reloaded.supported_extensions()
        assert reloaded.unavailable_extensions()[".py"] == _python_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.unavailable_extensions()[".pyw"] == _python_mod.GRAMMAR_INSTALL_HINT
        # JavaScript stays available since its grammar is independent.
        assert ".js" in reloaded.supported_extensions()
    finally:
        monkeypatch.setattr(_python_mod, "_GRAMMAR_AVAILABLE", True)
        importlib.reload(languages)


def test_javascript_parser_factory_raises_when_grammar_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_create_javascript_parser`` errors clearly when the grammar isn't installed."""
    monkeypatch.setattr(_javascript_mod, "_JAVASCRIPT_TS_LANGUAGE", None)
    with pytest.raises(ImportError, match=r"tree-sitter-javascript is not installed.*safelint\[javascript\]"):
        _javascript_mod._create_javascript_parser()


def test_typescript_parser_factory_raises_when_grammar_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_create_typescript_parser`` errors clearly when the grammar isn't installed."""
    monkeypatch.setattr(_typescript_mod, "_TYPESCRIPT_TS_LANGUAGE", None)
    with pytest.raises(ImportError, match=r"tree-sitter-typescript is not installed.*safelint\[typescript\]"):
        _typescript_mod._create_typescript_parser()


def test_tsx_parser_factory_raises_when_grammar_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_create_tsx_parser`` errors clearly when the grammar isn't installed."""
    monkeypatch.setattr(_typescript_mod, "_TSX_TS_LANGUAGE", None)
    with pytest.raises(ImportError, match=r"tree-sitter-typescript is not installed.*safelint\[typescript\]"):
        _typescript_mod._create_tsx_parser()


def test_javascript_install_hint_names_the_right_extra() -> None:
    """The hint string matches what users actually need to type."""
    assert _javascript_mod.GRAMMAR_INSTALL_HINT == "pip install 'safelint[javascript]'"


def test_typescript_install_hint_names_the_right_extra() -> None:
    """TS hint covers both ``.ts`` / ``.tsx`` / ``.as`` since they share a grammar package."""
    assert _typescript_mod.GRAMMAR_INSTALL_HINT == "pip install 'safelint[typescript]'"


def test_registry_skips_javascript_when_grammar_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``_GRAMMAR_AVAILABLE`` is False, ``.js`` is in ``unavailable_extensions``, not ``supported_extensions``.

    Reimports the registry module fresh so the module-level for-loops
    re-run against the patched flag.
    """
    monkeypatch.setattr(_javascript_mod, "_GRAMMAR_AVAILABLE", False)
    reloaded = importlib.reload(languages)
    try:
        assert ".js" not in reloaded.supported_extensions()
        assert ".mjs" not in reloaded.supported_extensions()
        assert ".cjs" not in reloaded.supported_extensions()
        assert reloaded.unavailable_extensions()[".js"] == _javascript_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.unavailable_extensions()[".mjs"] == _javascript_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.unavailable_extensions()[".cjs"] == _javascript_mod.GRAMMAR_INSTALL_HINT
        # Python stays available.
        assert ".py" in reloaded.supported_extensions()
    finally:
        # Restore the registry so subsequent tests see the dev install state.
        monkeypatch.setattr(_javascript_mod, "_GRAMMAR_AVAILABLE", True)
        importlib.reload(languages)


def test_registry_skips_typescript_when_grammar_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TS grammar isn't installed, ``.ts`` / ``.tsx`` / ``.as`` are unavailable, JS stays available."""
    monkeypatch.setattr(_typescript_mod, "_GRAMMAR_AVAILABLE", False)
    reloaded = importlib.reload(languages)
    try:
        assert ".ts" not in reloaded.supported_extensions()
        assert ".tsx" not in reloaded.supported_extensions()
        assert ".as" not in reloaded.supported_extensions()
        assert reloaded.unavailable_extensions()[".ts"] == _typescript_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.unavailable_extensions()[".tsx"] == _typescript_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.unavailable_extensions()[".as"] == _typescript_mod.GRAMMAR_INSTALL_HINT
        # JS still works since its grammar is independent.
        assert ".js" in reloaded.supported_extensions()
    finally:
        monkeypatch.setattr(_typescript_mod, "_GRAMMAR_AVAILABLE", True)
        importlib.reload(languages)


def test_install_hint_for_returns_none_for_supported_extension() -> None:
    """``install_hint_for(".py")`` returns None when the Python grammar is installed.

    In v2.0.0+ Python is *not* in core deps - it's an opt-in extra
    like every other language. This test returns None because the
    dev / test environment has the ``[python]`` extra installed (via
    the ``dev`` extra that self-references ``[all]``); when the
    grammar is absent, ``.py`` will appear in
    :func:`unavailable_extensions` and ``install_hint_for`` returns
    the install hint. See
    :func:`test_install_hint_for_returns_hint_when_grammar_unavailable`
    for the unavailable-state version.
    """
    assert install_hint_for(".py") is None


def test_install_hint_for_returns_hint_when_grammar_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """``install_hint_for(".ts")`` returns the TS hint when the grammar isn't installed."""
    monkeypatch.setattr(_typescript_mod, "_GRAMMAR_AVAILABLE", False)
    reloaded = importlib.reload(languages)
    try:
        assert reloaded.install_hint_for(".ts") == _typescript_mod.GRAMMAR_INSTALL_HINT
        assert reloaded.install_hint_for(".py") is None
    finally:
        monkeypatch.setattr(_typescript_mod, "_GRAMMAR_AVAILABLE", True)
        importlib.reload(languages)


def test_every_language_has_its_own_extra() -> None:
    """v2.0.0's fully-symmetric model: every supported language ships as an opt-in extra.

    None of the per-language grammars are in the base install. Each
    has a matching extra (``[python]``, ``[javascript]``,
    ``[typescript]``) so users opt in to only the languages their
    project actually contains. ``[all]`` is a convenience alias for
    everything.

    Verified by reading ``project.optional-dependencies`` straight
    from the wheel's metadata via :mod:`importlib.metadata`.
    """
    md = metadata("safelint")
    provides_extras = set(md.get_all("Provides-Extra") or [])
    expected = {"python", "javascript", "typescript", "all"}
    missing = expected - provides_extras
    assert not missing, f"v2.0.0 contract: every supported language must have its own opt-in extra. Missing from wheel metadata: {sorted(missing)}. Provides-Extra: {sorted(provides_extras)}"


def test_dev_install_has_every_grammar() -> None:
    """Sanity: the dev environment must have every grammar so the test suite covers every code path.

    If this test fails, ``uv sync --extra dev`` is missing one of the
    grammar deps - fix ``pyproject.toml`` rather than the test.
    """
    assert unavailable_extensions() == {}, f"Dev install should have every grammar. Missing: {set(unavailable_extensions())}. Run `uv sync --extra dev`."
