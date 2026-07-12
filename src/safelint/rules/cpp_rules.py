"""C++-only rules - modern-C++ idiom discipline layered on the C-family checks.

These two rules capture C++ ownership / type-safety idioms that have no analogue
in the other languages, slotted into the existing 3xx band. Both are opt-in
(disabled by default):

* **SAFE315** ``raw_new_delete`` (3xx) - every ``new`` / ``delete`` expression.
  The modern-C++ ownership rule: prefer ``std::make_unique`` /
  ``std::make_shared`` and RAII. ``make_unique`` / ``make_shared`` contain no
  ``new_expression`` so they never fire; a raw ``new`` inside a
  ``unique_ptr<T>(new T)`` argument still fires (prefer ``make_unique``). It
  overlaps with the widened SAFE310 by design - 310 is the Holzmann
  no-allocation posture, 315 the ownership posture; enabling both double-reports
  (like SAFE205 / SAFE208).
* **SAFE316** ``dangerous_casts`` (3xx, precedent SAFE306) - ``reinterpret_cast``
  and ``const_cast``. These parse as a ``call_expression`` whose ``function`` is
  a ``template_function`` (``reinterpret_cast<T>(x)``), NOT a dedicated cast
  node, so detection is by the template callee name. ``static_cast`` /
  ``dynamic_cast`` are type-checked and never fire. The flagged list is
  configurable via ``dangerous_casts_cpp``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.languages.cpp import (
    CALL_EXPRESSION,
    DELETE_EXPRESSION,
    NEW_EXPRESSION,
    TEMPLATE_FUNCTION,
)
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class RawNewDeleteRule(BaseRule):
    """Flag raw ``new`` / ``delete`` - prefer smart pointers and RAII (opt-in)."""

    name = "raw_new_delete"
    code = "SAFE315"
    language = ("cpp",)

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every ``new`` / ``delete`` expression in *tree*."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type == NEW_EXPRESSION:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        "`new` takes raw ownership of heap memory - prefer `std::make_unique` / `std::make_shared` so a scoped owner releases it (RAII)",
                    )
                )
            elif node.type == DELETE_EXPRESSION:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        "`delete` frees memory manually - a smart pointer / RAII owner releases automatically and cannot be forgotten on an early return or exception",
                    )
                )
        return violations


class DangerousCastsRule(BaseRule):
    """Flag ``reinterpret_cast`` / ``const_cast`` - type-unsafe casts (opt-in)."""

    name = "dangerous_casts"
    code = "SAFE316"
    language = ("cpp",)

    _DEFAULT_DANGEROUS_CASTS: ClassVar[list[str]] = ["reinterpret_cast", "const_cast"]

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every configured named-cast expression.

        The named casts parse as a ``call_expression`` whose ``function`` is a
        ``template_function`` (``reinterpret_cast<T>(x)``); the cast keyword is
        that template's ``name`` identifier. ``static_cast`` / ``dynamic_cast``
        are omitted from the default list because the compiler type-checks them.
        """
        raw, error_key = resolve_lang_config_lookup(self.config, "dangerous_casts", resolve_lang_name(filepath), default=self._DEFAULT_DANGEROUS_CASTS)
        flagged = frozenset(_validated_string_list(raw, error_key))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != CALL_EXPRESSION:
                continue
            func = node.child_by_field_name("function")
            if func is None or func.type != TEMPLATE_FUNCTION:
                continue
            name_node = func.child_by_field_name("name")
            if name_node is None:  # pragma: no cover - defensive: a template_function always has a name field
                continue
            cast = node_text(name_node)
            if cast in flagged:
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        f"`{cast}` is an unchecked cast that can silently break type / const safety - use `static_cast` / `dynamic_cast`, or redesign to remove the cast",
                    )
                )
        return violations
