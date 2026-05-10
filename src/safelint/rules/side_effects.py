"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
from safelint.languages.javascript import FUNCTION_TYPES as _JS_FUNCTION_TYPES
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule
from safelint.rules.resource_lifecycle import _validated_string_list


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({FUNCTION_DEF, ASYNC_FUNCTION_DEF}),
    "javascript": _JS_FUNCTION_TYPES,
}


def _io_funcs_for_lang(rule_config: dict, lang_name: str, fallback: list[str]) -> frozenset[str]:
    """Resolve the active I/O-primitive set for *lang_name* against the rule's config.

    Per-language config is keyed by ``io_functions`` (Python, the default)
    and ``io_functions_<lang>`` for non-Python languages. Adding a new
    language is additive — drop a new ``io_functions_<lang>`` list into
    ``DEFAULTS["rules"]`` and the lookup picks it up.

    Validates that the value is a list/tuple of strings before building
    the frozenset. A bare-string typo (``io_functions_javascript = "log"``)
    would otherwise be silently coerced to a set of single characters
    and effectively disable detection — fail loud instead.
    """
    key = "io_functions" if lang_name == "python" else f"io_functions_{lang_name}"
    raw = rule_config.get(key, fallback if lang_name == "python" else [])
    return frozenset(_validated_string_list(raw, key))


def _first_io_call(func_node: tree_sitter.Node, io_funcs: frozenset[str], function_types: frozenset[str]) -> tree_sitter.Node | None:
    """Return the first I/O call inside *func_node* (skipping nested defs), or None."""
    for child in walk(func_node, skip_types=tuple(function_types)):
        if child.type not in CALL_TYPES:
            continue
        name = call_name(child)
        if name and name in io_funcs:
            return child
    return None


def _func_display_name(func_node: tree_sitter.Node) -> str:
    """Return the function's effective name for display / prefix matching.

    Direct ``name`` field wins (Python ``def foo``, JS named function
    declarations). Anonymous JS forms (``arrow_function``,
    ``function_expression`` without a name) have no ``name`` field but
    are usually bound through a surrounding ``const x = () => ...`` /
    ``let x = function() {}``; in that shape Tree-sitter makes the
    function expression a child of a ``variable_declarator`` whose
    ``name`` field carries the binding identifier — surface that
    identifier as the effective name. Without this fallback,
    ``const fetchUser = () => ...`` renders as ``<anonymous>`` *and*
    the SAFE303 ``pure_prefixes`` check (which matches against the
    name's lowercase prefix) silently drops every named arrow binding
    that's exactly the case the rule is designed to catch.
    """
    name_node = func_node.child_by_field_name("name")
    if name_node is not None:
        return node_text(name_node)
    parent = func_node.parent
    if parent is not None and parent.type == "variable_declarator":
        binding = parent.child_by_field_name("name")
        if binding is not None:
            return node_text(binding)
    return "<anonymous>"


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O."""

    name = "side_effects_hidden"
    code = "SAFE303"
    language = ("python", "javascript")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag pure-named functions that contain I/O calls."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        io_funcs = _io_funcs_for_lang(self.config, lang_name, ["open", "print", "input"])
        # Normalise both sides of the comparison so user-supplied prefixes
        # like ``["Get", "Calculate"]`` still match ``get_data`` / ``calculate_x``.
        pure_prefixes: tuple[str, ...] = tuple(p.lower() for p in self.config.get("pure_prefixes", []))

        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            func_name = _func_display_name(node)
            name_lower = func_name.lower()
            if not any(name_lower.startswith(p) or name_lower == p.rstrip("_") for p in pure_prefixes):
                continue
            io_call = _first_io_call(node, io_funcs, function_types)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        io_call,
                        f'Function "{func_name}" looks pure but calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations


class SideEffectsRule(BaseRule):
    """Flag I/O primitives called inside any function not explicitly named for I/O."""

    name = "side_effects"
    code = "SAFE304"
    language = ("python", "javascript")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        io_funcs = _io_funcs_for_lang(self.config, lang_name, ["open", "print", "input"])
        # Lowercase BOTH sides so the substring check is genuinely
        # case-insensitive — mixed-case keywords in config (e.g. ``"Write"``)
        # still match camelCase function names like ``writeLog``.
        io_keywords: list[str] = [kw.lower() for kw in self.config.get("io_name_keywords", [])]

        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            func_name = _func_display_name(node)
            name_lower = func_name.lower()
            if any(kw in name_lower for kw in io_keywords):
                continue
            io_call = _first_io_call(node, io_funcs, function_types)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        io_call,
                        f'Function "{func_name}" calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations
