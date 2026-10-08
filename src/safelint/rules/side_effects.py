"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages import c as _c
from safelint.languages import cpp as _cpp
from safelint.languages import go as _go
from safelint.languages import java as _java
from safelint.languages import javascript as _js
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages import rust as _rust
from safelint.languages import typescript as _ts
from safelint.languages._node_utils import CALL_TYPES, call_name, function_name_node, node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_FUNCTION_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF}),
    "javascript": _js.FUNCTION_TYPES,
    "typescript": _js.FUNCTION_TYPES,
    "java": _java.FUNCTION_TYPES,
    "rust": _rust.FUNCTION_TYPES,
    "go": _go.FUNCTION_TYPES,
    "php": _php.FUNCTION_TYPES,
    "c": _c.FUNCTION_TYPES,
    "cpp": _cpp.FUNCTION_TYPES,
}


def _io_funcs_for_lang(rule_config: dict, lang_name: str, fallback: list[str]) -> frozenset[str]:
    """Resolve the active I/O-primitive set for *lang_name* against the rule's config.

    Per-language config is keyed by ``io_functions`` (Python, the default)
    and ``io_functions_<lang>`` for non-Python languages. TypeScript
    inherits the JavaScript list by default - runtime semantics are
    identical (TS compiles to JS), so the same I/O primitives apply.
    Users can override per-language by setting
    ``io_functions_typescript`` explicitly.

    Validates the resolved value is a list/tuple of strings before
    building the frozenset. A bare-string typo
    (``io_functions_javascript = "log"``) would otherwise be silently
    coerced to a set of single characters and effectively disable
    detection - fail loud instead.
    """
    py_default = fallback if lang_name == _py.EXTRA_NAME else []
    raw, error_key = resolve_lang_config_lookup(rule_config, "io_functions", lang_name, default=py_default)
    return frozenset(_validated_string_list(raw, error_key))


#: Rust macros whose target decides whether they perform I/O at all. ``write!``
#: is sugar for ``.write_fmt(..)`` on its first argument, which may implement
#: ``std::io::Write`` (I/O) or ``std::fmt::Write`` (a string buffer, no I/O).
_RUST_FMT_MACROS = frozenset({"write", "writeln"})

#: Parameter / initialiser spellings that prove a ``write!`` target is a formatter
#: or an in-memory string rather than a stream.
_RUST_NON_IO_TARGET_TYPES = ("Formatter", "String")
_RUST_STRING_INITIALISERS = ("String::new", "String::with_capacity", "String::from", "format!")


def _rust_write_target_is_not_io(macro_node: tree_sitter.Node, func_node: tree_sitter.Node) -> bool:
    """Return True if a Rust ``write!`` / ``writeln!`` writes somewhere that is not I/O.

    ``write!`` is not an I/O function in Rust. It expands to ``write_fmt`` on its
    first argument, so whether it touches the outside world depends entirely on
    that argument's type::

        impl fmt::Display for X {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(f, "hello")          // no I/O - the only way to impl Display
            }
        }

        let mut s = String::new();
        write!(&mut s, "x").unwrap();        // no I/O - string building

        writeln!(std::io::stdout(), "x");    // genuine I/O

    Tree-sitter gives no types, but it does give the first argument, and where that
    argument is a plain binding its own declaration carries the answer: a parameter
    typed ``Formatter`` or ``String``, or a local initialised from ``String::new``.
    Anything else - a path expression, a call, an unknown binding - keeps reporting,
    so the unresolved case stays a finding rather than being silently dropped.

    On ripgrep ``write!`` / ``writeln!`` were 34 of 83 SAFE304 findings, 16 of them
    inside ``fn fmt``. See #171.
    """
    if _rust_macro_name_text(macro_node) not in _RUST_FMT_MACROS:
        return False
    target = _rust_macro_first_argument_name(macro_node)
    if target is None:
        return False
    return _rust_binding_is_non_io_target(func_node, target)


def _rust_macro_first_argument_name(macro_node: tree_sitter.Node) -> str | None:
    """Return the first macro argument when it is a plain binding, else None.

    Strips a leading ``&`` / ``&mut`` so ``write!(&mut s, ..)`` resolves to ``s``.
    Returns None whenever the argument is anything other than a single identifier,
    which is what keeps ``writeln!(std::io::stdout(), ..)`` reporting.
    """
    tokens = next((child for child in macro_node.children if child.type == _rust.TOKEN_TREE), None)
    if tokens is None:
        return None  # pragma: no cover - defensive: a macro invocation always has a token tree
    first: list[tree_sitter.Node] = []
    for token in tokens.children[1:]:  # skip the opening delimiter
        if token.type in (",", ")", "]", "}"):
            break
        if token.type not in ("&", _rust.MUTABLE_SPECIFIER):
            first.append(token)
    if len(first) != 1 or first[0].type != _rust.IDENTIFIER:
        return None
    return node_text(first[0])


def _rust_binding_is_non_io_target(func_node: tree_sitter.Node, name: str) -> bool:
    """Return True if *name* is declared in *func_node* as a formatter or a string."""
    params = func_node.child_by_field_name("parameters")
    if params is not None and _rust_parameter_declares_non_io(params, name):
        return True
    return _rust_local_is_string_buffer(func_node, name)


def _rust_parameter_declares_non_io(params: tree_sitter.Node, name: str) -> bool:
    """Return True if a parameter named *name* is typed as a ``Formatter`` or ``String``."""
    for param in params.named_children:
        if param.type != _rust.PARAMETER:
            continue
        pattern = param.child_by_field_name("pattern")
        type_node = param.child_by_field_name("type")
        if pattern is None or type_node is None or node_text(pattern) != name:
            continue
        return any(spelling in node_text(type_node) for spelling in _RUST_NON_IO_TARGET_TYPES)
    return False


def _rust_local_is_string_buffer(func_node: tree_sitter.Node, name: str) -> bool:
    """Return True if *name* is a local initialised from a ``String`` constructor."""
    for node in walk(func_node, skip_types=(_rust.FUNCTION_ITEM,)):
        if node.type != _rust.LET_DECLARATION:
            continue
        pattern = node.child_by_field_name("pattern")
        value = node.child_by_field_name("value")
        if pattern is None or value is None or node_text(pattern) != name:
            continue
        initialiser = node_text(value)
        return any(initialiser.startswith(prefix) for prefix in _RUST_STRING_INITIALISERS)
    return False


def _first_io_call(func_node: tree_sitter.Node, io_funcs: frozenset[str], function_types: frozenset[str]) -> tree_sitter.Node | None:
    """Return the first I/O call (or Rust I/O macro) inside *func_node*, or None.

    Rust's most common I/O entry points are macros (``println!``,
    ``eprintln!``, ``write!``, ``writeln!``) rather than function
    calls. The walk additionally inspects ``macro_invocation`` nodes
    and resolves the macro name via ``_rust_macro_name_text``. The
    same configured ``io_funcs`` set is consulted for both - a user
    listing ``"println"`` covers ``println!(...)``.

    Skips nested function / closure definitions so inner functions
    are analysed separately.
    """
    return next(
        (child for child in walk(func_node, skip_types=tuple(function_types)) if _io_call_name(child) in io_funcs and not _rust_write_target_is_not_io(child, func_node)),
        None,
    )


def _io_call_name(node: tree_sitter.Node) -> str | None:
    """Return the bareword name if *node* is a call or Rust macro; ``None`` otherwise.

    Helper for :func:`_first_io_call` so the loop body stays under
    SafeLint's nesting cap.
    """
    if node.type in CALL_TYPES:
        return call_name(node)
    if node.type == _rust.MACRO_INVOCATION:
        return _rust_macro_name_text(node)
    return None


def _resolved_io_call_name(io_call: tree_sitter.Node) -> str:
    """Return the display name for an I/O call or macro, falling back to ``"<unknown>"``.

    Wraps ``call_name`` (call_expression / method_invocation / object_creation /
    new_expression / Python call) and ``_rust_macro_name_text``
    (macro_invocation) so the message formatter doesn't need to dispatch
    on node type. Rust macros render with the trailing ``!`` so
    ``println!`` is clearly distinguished from a hypothetical ``println``
    function in messages.
    """
    if io_call.type == _rust.MACRO_INVOCATION:
        name = _rust_macro_name_text(io_call)
        return f"{name}!" if name else "<unknown>"
    return call_name(io_call) or "<unknown>"


def _rust_macro_name_text(macro_invocation: tree_sitter.Node) -> str | None:
    """Resolve a Rust ``macro_invocation``'s bareword name, or None.

    Bare ``println!`` resolves to ``"println"``; scoped ``std::println!``
    also resolves to ``"println"`` (trailing identifier extracted).
    """
    macro_field = macro_invocation.child_by_field_name("macro")
    if macro_field is None:
        return None
    if macro_field.type == _rust.IDENTIFIER:
        return node_text(macro_field)
    if macro_field.type == _rust.SCOPED_IDENTIFIER:
        name_node = macro_field.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else None
    return None  # pragma: no cover - defensive: macro field is always identifier or scoped_identifier


def _func_display_name(func_node: tree_sitter.Node, lang_name: str) -> str:
    """Return the function's effective name for display / prefix matching.

    Direct ``name`` field wins (Python ``def foo``, JS named function
    declarations). Anonymous JS forms (``arrow_function``,
    ``function_expression`` without a name) have no ``name`` field but
    are usually bound through a surrounding ``const x = () => ...`` /
    ``let x = function() {}``; in that shape Tree-sitter makes the
    function expression a child of a ``variable_declarator`` whose
    ``name`` field carries the binding identifier - surface that
    identifier as the effective name. Without this fallback,
    ``const fetchUser = () => ...`` renders as ``<anonymous>`` *and*
    the SAFE303 ``pure_prefixes`` check (which matches against the
    name's lowercase prefix) silently drops every named arrow binding
    that's exactly the case the rule is designed to catch.
    """
    name_node = function_name_node(func_node, lang_name)
    if name_node is not None:
        return node_text(name_node)
    parent = func_node.parent
    if parent is not None and parent.type == _java.VARIABLE_DECLARATOR:
        binding = parent.child_by_field_name("name")
        if binding is not None:
            return node_text(binding)
    return "<anonymous>"


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O."""

    name = "side_effects_hidden"
    code = "SAFE303"
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

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
            func_name = _func_display_name(node, lang_name)
            name_lower = func_name.lower()
            if not any(name_lower.startswith(p) or name_lower == p.rstrip("_") for p in pure_prefixes):
                continue
            io_call = _first_io_call(node, io_funcs, function_types)
            if io_call:
                io_name = _resolved_io_call_name(io_call)
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
    language = (_py.EXTRA_NAME, _js.EXTRA_NAME, _ts.EXTRA_NAME, _java.EXTRA_NAME, _rust.EXTRA_NAME, _go.EXTRA_NAME, _php.EXTRA_NAME, _c.EXTRA_NAME, _cpp.EXTRA_NAME)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        lang_name = resolve_lang_name(filepath)
        function_types = _FUNCTION_TYPES_BY_LANG[lang_name]
        io_funcs = _io_funcs_for_lang(self.config, lang_name, ["open", "print", "input"])
        # Lowercase BOTH sides so the substring check is genuinely
        # case-insensitive - mixed-case keywords in config (e.g. ``"Write"``)
        # still match camelCase function names like ``writeLog``.
        io_keywords: list[str] = [kw.lower() for kw in self.config.get("io_name_keywords", [])]

        violations = []
        for node in walk(tree.root_node):
            if node.type not in function_types:
                continue
            func_name = _func_display_name(node, lang_name)
            name_lower = func_name.lower()
            if any(kw in name_lower for kw in io_keywords):
                continue
            io_call = _first_io_call(node, io_funcs, function_types)
            if io_call:
                io_name = _resolved_io_call_name(io_call)
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        io_call,
                        f'Function "{func_name}" calls I/O primitive "{io_name}" - rename to signal intent or use dependency injection',
                    )
                )
        return violations
