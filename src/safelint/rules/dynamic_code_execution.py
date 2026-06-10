"""dynamic_code_execution rule (SAFE309): flag runtime code generation / reflection.

Holzmann's Power-of-Ten rule 8 restricts the preprocessor because textual code
generation defeats static analysis: a tool cannot reason about code that does
not exist until runtime. The modern-language equivalent is ``eval`` /
``exec``-style dynamic execution and reflection (``Class.forName`` /
``Method.invoke``). SAFE309 is **structural** - it flags the construct wherever
it appears, with no dataflow. That is the difference from SAFE801
(``tainted_sink``), which fires only when user input demonstrably reaches one
of these sinks. The two are complementary and may both fire on the same line;
an untainted ``eval(config_string)`` still destroys analysability, which is
what rule 8 cares about.

Disabled by default: reflection-heavy frameworks (Java) and legitimate plugin
loaders would otherwise be noisy.

Rust is excluded: its rule-8 analogue is the macro system, whose bodies parse
as opaque token trees (a documented limitation), and ``panic``-family macros
already have SAFE204.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages._node_utils import call_name, node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Callable

    import tree_sitter

    from safelint.rules.base import Violation


#: Default dynamic-execution call names per language.
#:
#: * Python: ``eval`` / ``exec`` / ``compile`` / ``__import__``. ``getattr`` /
#:   ``setattr`` are NOT included - far too common, and they do not generate
#:   code.
#: * JavaScript / TypeScript: ``eval`` / ``Function`` (the ``new Function(...)``
#:   constructor and the bare ``Function(...)`` call) / ``execScript``.
#: * Java: ``forName`` (``Class.forName``), ``invoke`` (``Method.invoke``),
#:   ``eval`` (JSR-223 ``ScriptEngine``), ``defineClass`` / ``loadClass``
#:   (custom class loaders).
_DEFAULT_CALLS_PYTHON = ["eval", "exec", "compile", "__import__"]
_DEFAULT_CALLS_JAVASCRIPT = ["eval", "Function", "execScript"]
_DEFAULT_CALLS_JAVA = ["forName", "invoke", "eval", "defineClass", "loadClass"]

_DEFAULTS_BY_LANG: dict[str, list[str]] = {
    "python": _DEFAULT_CALLS_PYTHON,
    "javascript": _DEFAULT_CALLS_JAVASCRIPT,
    "typescript": _DEFAULT_CALLS_JAVASCRIPT,
    "java": _DEFAULT_CALLS_JAVA,
}

#: Call-expression node types to inspect per language. Python ``call``;
#: JS / TS ``call_expression`` plus ``new_expression`` (for ``new Function``);
#: Java ``method_invocation``.
_CALL_TYPES_BY_LANG: dict[str, frozenset[str]] = {
    "python": frozenset({"call"}),
    "javascript": frozenset({"call_expression", "new_expression"}),
    "typescript": frozenset({"call_expression", "new_expression"}),
    "java": frozenset({"method_invocation"}),
}


def _python_match(call_node: tree_sitter.Node, names: frozenset[str]) -> str | None:
    """Match a bare ``eval(...)`` or ``builtins.eval(...)`` call; skip ``obj.eval()``.

    Restricting to bare-identifier and ``builtins.``-qualified calls keeps
    ``model.eval()`` (PyTorch) and similar method calls from firing.
    """
    func = call_node.child_by_field_name("function")
    if func is None:
        return None
    if func.type == "identifier":
        name = node_text(func)
        return name if name in names else None
    if func.type == "attribute":
        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if obj is not None and attr is not None and obj.type == "identifier" and node_text(obj) == "builtins":
            name = node_text(attr)
            return name if name in names else None
    return None


def _javascript_match(call_node: tree_sitter.Node, names: frozenset[str]) -> str | None:
    """Match a bare ``eval(...)`` / ``Function(...)`` call or ``new Function(...)``.

    Requires a bare-identifier callee (or constructor), so a method call such
    as ``obj.eval()`` is not flagged.
    """
    callee = call_node.child_by_field_name("function") or call_node.child_by_field_name("constructor")
    if callee is None or callee.type != "identifier":
        return None
    name = node_text(callee)
    return name if name in names else None


def _java_match(call_node: tree_sitter.Node, names: frozenset[str]) -> str | None:
    """Match a Java reflection call by bare method name (``Class.forName``, etc.).

    Java reflection is always a method call on a receiver, so unlike the
    Python / JS matchers this does not require a bare callee. ``call_name``
    returns the bare method name; a user-defined ``forName`` would also match
    (acceptable for an off-by-default rule).
    """
    name = call_name(call_node)
    return name if name is not None and name in names else None


_MATCHERS: dict[str, Callable[[tree_sitter.Node, frozenset[str]], str | None]] = {
    "python": _python_match,
    "javascript": _javascript_match,
    "typescript": _javascript_match,
    "java": _java_match,
}


class DynamicCodeExecutionRule(BaseRule):
    """Flag dynamic code execution / reflection constructs (Power of Ten rule 8)."""

    name = "dynamic_code_execution"
    code = "SAFE309"
    language = ("python", "javascript", "typescript", "java")

    _BASE_KEY: ClassVar[str] = "dynamic_exec_calls"

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every dynamic-execution / reflection call in *filepath*."""
        lang = resolve_lang_name(filepath)
        raw, source_key = resolve_lang_config_lookup(self.config, self._BASE_KEY, lang, default=_DEFAULTS_BY_LANG[lang])
        names = frozenset(_validated_string_list(raw, source_key))
        call_types = _CALL_TYPES_BY_LANG[lang]
        matcher = _MATCHERS[lang]
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in call_types:
                continue
            name = matcher(node, names)
            if name is not None:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f'"{name}" performs dynamic code execution / reflection - this defeats static analysis (Power of Ten rule 8); prefer a static dispatch where possible',
                    )
                )
        return violations
