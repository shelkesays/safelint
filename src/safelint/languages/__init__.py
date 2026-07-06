"""Language registry - maps file extensions to LanguageDefinition instances.

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

from safelint.languages import c as _c_mod
from safelint.languages import cpp as _cpp_mod
from safelint.languages import go as _go_mod
from safelint.languages import java as _java_mod
from safelint.languages import javascript as _javascript_mod
from safelint.languages import php as _php_mod
from safelint.languages import python as _python_mod
from safelint.languages import rust as _rust_mod
from safelint.languages import typescript as _typescript_mod
from safelint.languages._types import LanguageDefinition
from safelint.languages.c import C
from safelint.languages.cpp import CPP
from safelint.languages.go import GO
from safelint.languages.java import JAVA
from safelint.languages.javascript import JAVASCRIPT
from safelint.languages.php import PHP
from safelint.languages.python import PYTHON
from safelint.languages.rust import RUST
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


# Python - only register if ``tree-sitter-python`` is installed (i.e.
# the ``[python]`` or ``[all]`` extra was selected). Otherwise, record
# both the install hint and the extra name so the CLI can suggest
# single- or multi-language install commands. Same shape as the JS /
# TS blocks below - keep them parallel so future drift is grep-able.
if _python_mod._GRAMMAR_AVAILABLE:
    for _ext in PYTHON.file_extensions:
        _REGISTRY[_ext] = PYTHON
else:
    for _ext in PYTHON.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _python_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _python_mod.EXTRA_NAME

# JavaScript - only register if ``tree-sitter-javascript`` is installed.
# Note: ``TYPESCRIPT`` and ``TSX`` share the same ``name="typescript"`` but
# use different Tree-sitter grammars - ``TYPESCRIPT`` handles ``.ts`` and
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

# Java - only register if ``tree-sitter-java`` is installed (i.e. the
# ``[java]`` or ``[all]`` extra was selected). Spring Boot support is
# *not* a separate registration; it's a framework preset on top of the
# Java language definition, configured via ``[tool.safelint.java] framework``.
if _java_mod._GRAMMAR_AVAILABLE:
    for _ext in JAVA.file_extensions:
        _REGISTRY[_ext] = JAVA
else:
    for _ext in JAVA.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _java_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _java_mod.EXTRA_NAME

# Rust - only register if ``tree-sitter-rust`` is installed (i.e. the
# ``[rust]`` or ``[all]`` extra was selected). Memory safety is enforced
# by rustc, so safelint's rule set on Rust is narrower than other
# languages (function shape, error-handling discipline, loop safety,
# dataflow); SAFE401 ``resource_lifecycle`` is intentionally NOT registered
# for Rust because RAII / Drop already guarantees cleanup.
if _rust_mod._GRAMMAR_AVAILABLE:
    for _ext in RUST.file_extensions:
        _REGISTRY[_ext] = RUST
else:
    for _ext in RUST.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _rust_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _rust_mod.EXTRA_NAME

# Go - only register if ``tree-sitter-go`` is installed (i.e. the
# ``[go]`` or ``[all]`` extra was selected). Go's runtime and ``go vet``
# already catch a class of issues; safelint's Go rule scope focuses on
# function shape, ignored ``error`` returns, empty error-check bodies,
# ``panic`` placement, bare ``for {}`` loops, package-level shared
# state, and dataflow sinks. Same shape as the blocks above - keep them
# parallel so future drift is grep-able.
if _go_mod._GRAMMAR_AVAILABLE:
    for _ext in GO.file_extensions:
        _REGISTRY[_ext] = GO
else:
    for _ext in GO.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _go_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _go_mod.EXTRA_NAME

# PHP - only register if ``tree-sitter-php`` is installed (i.e. the
# ``[php]`` or ``[all]`` extra was selected). PHP ports the widest slice
# of the cross-language rule set; the ``@`` error-suppression operator
# (SAFE603) and superglobal taint sources (SAFE801) are its headline
# additions. Uses the mixed HTML+PHP grammar so templated files parse.
# Same shape as the blocks above - keep them parallel so future drift is
# grep-able.
if _php_mod._GRAMMAR_AVAILABLE:
    for _ext in PHP.file_extensions:
        _REGISTRY[_ext] = PHP
else:
    for _ext in PHP.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _php_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _php_mod.EXTRA_NAME

# C - only register if ``tree-sitter-c`` is installed (i.e. the ``[c]`` or
# ``[all]`` extra was selected). C is Holzmann's original language: it ports
# the 16 cross-language rules and adds five C-only rules (SAFE106 / SAFE310-313)
# that express the Power-of-Ten clauses every other language adapts away. ``.h``
# headers register to C (a C++ project's ``.h`` files lint as C; documented).
# Same shape as the blocks above - keep them parallel so future drift is
# grep-able.
if _c_mod._GRAMMAR_AVAILABLE:
    for _ext in C.file_extensions:
        _REGISTRY[_ext] = C
else:
    for _ext in C.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _c_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _c_mod.EXTRA_NAME

# C++ - only register if ``tree-sitter-cpp`` is installed (i.e. the ``[cpp]`` or
# ``[all]`` extra was selected). C++ builds on C: it widens the five C-only
# rules to ``("c", "cpp")``, gives SAFE201 its first non-Python home, and adds
# SAFE315 / SAFE316. C++-only header extensions (``.hpp`` / ``.hxx`` / ``.hh``)
# register here; plain ``.h`` stays with C (documented). Same shape as the
# blocks above - keep them parallel so future drift is grep-able.
if _cpp_mod._GRAMMAR_AVAILABLE:
    for _ext in CPP.file_extensions:
        _REGISTRY[_ext] = CPP
else:
    for _ext in CPP.file_extensions:
        _UNAVAILABLE_EXTENSIONS[_ext] = _cpp_mod.GRAMMAR_INSTALL_HINT
        _UNAVAILABLE_EXTRA_NAMES[_ext] = _cpp_mod.EXTRA_NAME


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
    extensions whose grammar package isn't installed - those appear in
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
    ...     print(f"safelint: warning: skipping .ts files - {hint}")
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
    "CPP",
    "GO",
    "JAVA",
    "JAVASCRIPT",
    "PHP",
    "PYTHON",
    "TSX",
    "TYPESCRIPT",
    "C",
    "LanguageDefinition",
    "extra_name_for",
    "get_language_for_file",
    "install_hint_for",
    "supported_extensions",
    "unavailable_extensions",
]
