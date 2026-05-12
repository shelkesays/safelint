"""Shared configuration-value validators used across core and rules.

Lives in ``core/`` so any layer — engine plumbing, rule modules,
diagnostics — can import without creating cross-rule import cycles
(``rules/foo.py`` previously had to ``from safelint.rules.resource_lifecycle
import _validated_string_list`` which is architecturally backwards;
core helpers belong in core).

Private to the package (leading-underscore module name signals that),
but importable from any sibling module that needs the validation.
"""

from __future__ import annotations

from typing import Any


def _validated_string_list(value: object, key_name: str) -> list[str]:
    """Validate that *value* is a list/tuple of strings, return it as a list.

    Raises :class:`TypeError` if *value* is anything else — including a bare
    ``str``, which Python would otherwise silently coerce into a list of
    individual characters via ``list(...)``. The early raise turns a typo
    like ``tracked_functions = "open"`` (note the missing brackets) into a
    clear error rather than a tracker that mysteriously matches single
    letters.

    Used by:

    * ``core/engine.py`` for ``exclude_paths`` / ``extend_exclude_paths``
    * ``rules/resource_lifecycle.py`` for ``tracked_functions`` /
      ``extend_tracked_functions`` / ``cleanup_patterns`` /
      ``tracked_functions_javascript``
    * ``rules/side_effects.py`` for ``io_functions_<lang>``
    * ``rules/state_purity.py`` for ``global_namespaces_javascript``
    * ``rules/documentation.py`` for ``assertion_calls_javascript``

    Every site shares the same TypeError shape so users see consistent
    error messages regardless of which config key tripped the validator.
    """
    if not isinstance(value, (list, tuple)):
        msg = f"{key_name} must be a list of strings, got {type(value).__name__}"
        raise TypeError(msg)
    non_strings = [item for item in value if not isinstance(item, str)]
    if non_strings:
        bad = ", ".join(f"{type(item).__name__}({item!r})" for item in non_strings)
        msg = f"{key_name} must contain only strings — got: {bad}"
        raise TypeError(msg)
    # Both checks above guarantee every element is a str; the list
    # comprehension is a typing-only re-narrowing for ty/mypy.
    return [item for item in value if isinstance(item, str)]


def resolve_lang_config_key(base_key: str, lang_name: str) -> str:
    """Compute the config key name for a per-language rule option.

    Python uses bare keys (``io_functions``, ``sinks``, etc.) for
    historical reasons — Python was the only language for safelint's
    first year. JavaScript / TypeScript / future JS-family languages
    use suffixed keys (``io_functions_javascript``,
    ``io_functions_typescript``, etc.) so each language can have its
    own defaults / overrides.

    >>> resolve_lang_config_key("io_functions", "python")
    'io_functions'
    >>> resolve_lang_config_key("io_functions", "javascript")
    'io_functions_javascript'
    >>> resolve_lang_config_key("io_functions", "typescript")
    'io_functions_typescript'
    """
    if lang_name == "python":
        return base_key
    return f"{base_key}_{lang_name}"


def get_per_language_config(
    rule_config: dict[str, Any],
    base_key: str,
    lang_name: str,
    default: Any = None,  # noqa: ANN401 — config values are intentionally dynamic (lists, strings, bools, etc.)
) -> Any:  # noqa: ANN401 — see above
    """Get a per-language rule-config value with TypeScript → JavaScript fallback.

    Lookup order:

    1. ``rule_config[resolve_lang_config_key(base_key, lang_name)]`` — the
       language-native key (e.g. ``sinks_typescript`` for a TS file).
    2. **TypeScript-only fallback:** if *lang_name* is ``"typescript"``
       and the TS-specific key is unset, ``rule_config[f"{base_key}_javascript"]``.
       This means TS projects inherit the JavaScript defaults / overrides
       automatically — TS is syntactic sugar over JS, and the same sink
       lists / global namespaces / I/O primitives apply at runtime.
       Users who genuinely want different behaviour for ``.ts`` files
       can set the ``_typescript`` key explicitly.
    3. *default* (caller-supplied).

    Why TS → JS but not the reverse?

    * **Runtime is the same.** TS compiles to JS; at runtime there's no
      "TypeScript runtime" distinct from the JS engine. Sink lists,
      taint sources, global namespaces, etc. are properties of the
      runtime, not the source language.
    * **Avoids config-key proliferation.** Most projects don't need
      separate TS configs. Sharing keys by default keeps the config
      surface small.
    * **Preserves the override door.** Projects that DO want different
      rules per language can still set ``_typescript`` keys
      explicitly; the fallback only fires when the user hasn't.

    Returns the raw value as found in config — callers are responsible
    for validating type (e.g. via :func:`_validated_string_list` for
    string-list keys) before use. Callers that need the *source key*
    of the resolved value (for example, to surface a precise error
    message naming the key the user actually set) should use
    :func:`resolve_lang_config_lookup` instead.
    """
    value, _ = resolve_lang_config_lookup(rule_config, base_key, lang_name, default)
    return value


def resolve_lang_config_lookup(
    rule_config: dict[str, Any],
    base_key: str,
    lang_name: str,
    default: Any = None,  # noqa: ANN401 — config values are intentionally dynamic
) -> tuple[Any, str]:
    """Resolve a per-language rule-config value and return it alongside its source key.

    Same lookup semantics as :func:`get_per_language_config`.
    Returns ``(value, source_key)`` — ``source_key`` is the actual TOML
    key the value came from. Useful for error reporting: when a TS file
    inherits a bad ``foo_javascript = "not-a-list"`` value via the
    TS → JS fallback, raising a ``TypeError`` that names
    ``foo_typescript`` (the lookup *primary* key) would direct the user
    to fix a key they never set. Using ``source_key`` instead points
    them at the offending key directly.

    When the lookup falls through to *default*, ``source_key`` is the
    *primary* key (e.g. ``foo_typescript`` for a TS file) — that's the
    key the user would set to override the default.
    """
    primary_key = resolve_lang_config_key(base_key, lang_name)
    if primary_key in rule_config:
        return rule_config[primary_key], primary_key
    if lang_name == "typescript":
        fallback_key = f"{base_key}_javascript"
        if fallback_key in rule_config:
            return rule_config[fallback_key], fallback_key
    return default, primary_key
