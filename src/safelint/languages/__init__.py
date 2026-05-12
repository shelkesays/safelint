"""Language registry — maps file extensions to LanguageDefinition instances.

Every supported language's Tree-sitter grammar package ships as an
**optional extra**: ``[python]``, ``[javascript]``, ``[typescript]``,
``[all]``. None of them are in the base install. ``pip install
safelint`` alone gives you the engine but no language grammars; users
opt in to whichever languages their project actually contains by
installing the matching extra(s). Languages whose grammar isn't
present are kept out of :func:`supported_extensions` so file discovery
doesn't pick them up; their extensions are surfaced via
:func:`unavailable_extensions` so the CLI can hint the right
``pip install`` command when a user has, say, ``.ts`` files but only
``pip install safelint`` ran.
"""

from __future__ import annotations

from pathlib import Path

from safelint.languages import javascript as _javascript_mod
from safelint.languages import python as _python_mod
from safelint.languages import typescript as _typescript_mod
from safelint.languages._types import LanguageDefinition
from safelint.languages.javascript import JAVASCRIPT
from safelint.languages.python import PYTHON
from safelint.languages.typescript import TSX, TYPESCRIPT


_REGISTRY: dict[str, LanguageDefinition] = {}

# Extensions whose grammar package isn't installed. Values are the
# user-facing install hint (e.g. ``pip install 'safelint[javascript]'``).
# CLI uses this to nudge users when they have files safelint *could*
# lint but the optional extra hasn't been installed.
_UNAVAILABLE_EXTENSIONS: dict[str, str] = {}

# Mapping ``ext -> extra name`` for languages whose grammar isn't installed.
# Used to compose a multi-language ``pip install 'safelint[a,b]'`` command
# when more than one extra is missing (e.g. when ``safelint skill install``
# detects a Python + TypeScript monorepo with neither grammar installed).
_UNAVAILABLE_EXTRA_NAMES: dict[str, str] = {}


# Python — only register if ``tree-sitter-python`` is installed (i.e.
# the ``[python]`` or ``[all]`` extra was selected).
if _python_mod._GRAMMAR_AVAILABLE:
    for _ext in PYTHON.file_extensions:
        _REGISTRY[_ext] = PYTHON
else:
    for _ext in PYTHON.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _python_mod.GRAMMAR_INSTALL_HINT

# Python — only register if ``tree-sitter-python`` is installed (i.e.
# the ``[python]`` or ``[all]`` extra was selected). The first ``if``
# block above already wired this up; we additionally populate the
# extra-name map here so the CLI can compose multi-language install
# commands like ``pip install 'safelint[python,typescript]'``.
if not _python_mod._GRAMMAR_AVAILABLE:
    for _ext in PYTHON.file_extensions:
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _python_mod.EXTRA_NAME

# JavaScript — only register if ``tree-sitter-javascript`` is installed.
# Note: ``TYPESCRIPT`` and ``TSX`` share the same ``name="typescript"`` but
# use different Tree-sitter grammars — ``TYPESCRIPT`` handles ``.ts`` and
# ``.as`` (AssemblyScript, parsed by the standard TypeScript grammar),
# ``TSX`` handles ``.tsx``. Both gate on the same grammar package.
if _javascript_mod._GRAMMAR_AVAILABLE:
    for _ext in JAVASCRIPT.file_extensions:
        _REGISTRY[_ext] = JAVASCRIPT
else:
    for _ext in JAVASCRIPT.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _javascript_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _javascript_mod.EXTRA_NAME

if _typescript_mod._GRAMMAR_AVAILABLE:
    for _lang in (TYPESCRIPT, TSX):
        for _ext in _lang.file_extensions:
            _REGISTRY[_ext] = _lang
else:
    for _lang in (TYPESCRIPT, TSX):
        for _ext in _lang.file_extensions:
            _UNAVAILABLE_EXTENSIONS[_ext] = _typescript_mod.GRAMMAR_INSTALL_HINT
            _UNAVAILABLE_EXTRA_NAMES[_ext] = _typescript_mod.EXTRA_NAME


def get_language_for_file(filepath: str) -> LanguageDefinition | None:
    """Return the LanguageDefinition for *filepath* based on its extension, or None.

    Returns ``None`` for extensions whose grammar package isn't installed
    (call :func:`unavailable_extensions` to discover which ones, and
    :func:`install_hint_for` to get the right ``pip install`` command).
    """
    suffix = Path(filepath).suffix
    return _REGISTRY.get(suffix)


def supported_extensions() -> frozenset[str]:
    """Return the set of file extensions that have a registered, *installed* language.

    Each extension includes the leading dot, e.g. ``".py"``. Excludes
    extensions whose grammar package isn't installed — those appear in
    :func:`unavailable_extensions` instead. Use this when discovering
    source files in a directory; pair with :func:`get_language_for_file`
    to retrieve the matching definition.
    """
    return frozenset(_REGISTRY)


def unavailable_extensions() -> dict[str, str]:
    """Return ``{ext: install_hint}`` for extensions whose grammar isn't installed.

    Used by the CLI to surface a one-shot warning when a user has, say,
    ``.ts`` files in their tree but only ran ``pip install safelint``
    (no ``[typescript]`` extra). The hint string is the literal
    ``pip install ...`` command the user should run.

    Empty when every optional grammar is installed (e.g. when the user
    ran ``pip install 'safelint[all]'`` or installed the dev extras).
    """
    return dict(_UNAVAILABLE_EXTENSIONS)


def install_hint_for(extension: str) -> str | None:
    """Return the install hint for *extension*, or ``None`` if the extension is supported.

    Convenience wrapper for the common CLI lookup pattern:

    >>> hint = install_hint_for(".ts")
    >>> if hint is not None:
    ...     print(f"safelint: warning: skipping .ts files — {hint}")
    """
    return _UNAVAILABLE_EXTENSIONS.get(extension)


def extra_name_for(extension: str) -> str | None:
    """Return the PEP 621 extra name for *extension*, or ``None`` if the extension is supported.

    Lets the CLI compose multi-language install commands. For example,
    a project with ``.py`` and ``.ts`` files (neither grammar installed)
    yields ``{"python", "typescript"}`` from this lookup, which the CLI
    then composes into ``pip install 'safelint[python,typescript]'``.
    """
    return _UNAVAILABLE_EXTRA_NAMES.get(extension)


__all__ = [
    "JAVASCRIPT",
    "PYTHON",
    "TSX",
    "TYPESCRIPT",
    "LanguageDefinition",
    "extra_name_for",
    "get_language_for_file",
    "install_hint_for",
    "supported_extensions",
    "unavailable_extensions",
]
