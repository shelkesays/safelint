"""resource_lifecycle rule - tracked resource functions must use context managers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, walk
from safelint.languages.python import CALL, WITH_ITEM
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    from collections.abc import Iterator

    import tree_sitter

    from safelint.rules.base import Violation


def _validated_string_list(value: object, key_name: str) -> list[str]:
    """Validate that *value* is a list/tuple of strings, return it as a list.

    Raises :class:`TypeError` if *value* is anything else — including a bare
    ``str``, which Python would otherwise silently coerce into a list of
    individual characters via ``list(...)``. The early raise turns a typo
    like ``tracked_functions = "open"`` (note the missing brackets) into a
    clear error rather than a tracker that mysteriously matches single
    letters.
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


def _with_item_call(item: tree_sitter.Node) -> tree_sitter.Node | None:
    """Return the call node opened by *item*, unwrapping ``as_pattern`` if present."""
    value = item.child_by_field_name("value")
    # ``with_item`` always has a ``value`` field in valid Python; this is
    # a defensive guard against malformed AST.
    if value is None:  # pragma: no cover
        return None
    if value.type == "as_pattern" and value.named_children:
        value = value.named_children[0]
    return value if value.type == CALL else None


def _iter_with_items(tree: tree_sitter.Tree) -> Iterator[tree_sitter.Node]:
    """Yield every ``with_item`` node in *tree*.

    ``with_item`` only appears inside ``with_statement`` in tree-sitter-python,
    so a flat walk is sufficient.
    """
    for node in walk(tree.root_node):
        if node.type == WITH_ITEM:
            yield node


class ResourceLifecycleRule(BaseRule):
    """Require tracked resource-acquisition calls to be wrapped in a with statement."""

    name = "resource_lifecycle"
    code = "SAFE401"

    @staticmethod
    def _collect_guarded(tree: tree_sitter.Tree, tracked: frozenset[str]) -> set[int]:
        """Return the set of start_byte values for tracked calls already inside a with block."""
        guarded: set[int] = set()
        for item in _iter_with_items(tree):
            call_node = _with_item_call(item)
            if call_node is None:
                continue
            name = call_name(call_node)
            if name and name in tracked:
                guarded.add(call_node.start_byte)
        return guarded

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag unguarded calls to tracked resource-acquisition functions.

        ``tracked_functions`` defines the base set; ``extend_tracked_functions``
        appends to it without forcing the user to redeclare the defaults
        (mirrors ruff's ``extend-select`` ergonomics).
        """
        base_tracked = _validated_string_list(self.config.get("tracked_functions", ["open"]), "tracked_functions")
        extra_tracked = _validated_string_list(self.config.get("extend_tracked_functions", []), "extend_tracked_functions")
        tracked: frozenset[str] = frozenset(base_tracked + extra_tracked)
        cleanup: frozenset[str] = frozenset(self.config.get("cleanup_patterns", ["close"]))
        guarded = self._collect_guarded(tree, tracked)
        cleanup_str = " / ".join(sorted(cleanup))

        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != CALL:
                continue
            name = call_name(node)
            if not name or name not in tracked or node.start_byte in guarded:
                continue
            violations.append(
                self._make_violation_for_node(
                    filepath,
                    node,
                    f'"{name}()" called outside a with block - use a context manager or ensure {cleanup_str} is called on all exit paths',
                )
            )
        return violations
