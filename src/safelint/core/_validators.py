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
