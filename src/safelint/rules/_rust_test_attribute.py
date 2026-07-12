"""Shared Rust test-attribute detection.

Two rules need to ask "is this Rust attribute a test marker?":

* SAFE701 / SAFE702 (``test_coverage.py``) - walks the whole tree for
  any test marker to decide if the file *contains* tests (the inline
  ``#[cfg(test)] mod tests`` convention bypass).
* SAFE204 / SAFE208 (``rust_rules.py``) - walks the ancestor chain
  from a specific node to decide if it's *in* test context (so
  ``panic!`` / ``.unwrap()`` inside a test function are exempt).

Both rules use the **same marker definition**; only the walk semantics
differ. This module owns the definition and the inner-attribute
classifier so the two call sites stay in sync.

Recognised markers:

* Bare ``#[test]`` / ``#[rstest]`` - first named child is an
  ``identifier`` in :data:`RUST_TEST_ATTRIBUTE_NAMES`.
* Scoped ``#[tokio::test]`` / ``#[actix_web::test]`` /
  ``#[async_std::test]`` / ``#[smol_potat::test]`` /
  ``#[rstest::rstest]`` etc. - first named child is a
  ``scoped_identifier`` whose trailing identifier is in the set.
* ``#[cfg(test)]`` - first child is ``identifier "cfg"`` and the
  ``token_tree`` argument contains ``identifier "test"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text
from safelint.languages.rust import ATTRIBUTE as _RUST_ATTRIBUTE
from safelint.languages.rust import IDENTIFIER as _RUST_IDENTIFIER
from safelint.languages.rust import SCOPED_IDENTIFIER as _RUST_SCOPED_IDENTIFIER


if TYPE_CHECKING:
    import tree_sitter


#: Attribute names that count as test markers, matched against both
#: bare attribute identifiers (``#[test]`` / ``#[rstest]``) and the
#: trailing identifier of scoped paths (``#[tokio::test]`` /
#: ``#[rstest::rstest]``).
#:
#: * ``"test"`` covers the stdlib ``#[test]`` plus every async-test
#:   framework that suffixes ``::test`` (tokio, actix_web, async_std,
#:   smol_potat, smol, futures, test_log).
#: * ``"rstest"`` covers the parametric-test framework's bare
#:   ``#[rstest]`` and scoped ``#[rstest::rstest]`` - its attribute
#:   doesn't end in ``test`` so trailing-name matching alone wouldn't
#:   catch it.
#:
#: Extend here when a future framework lands with a different attribute
#: pattern; both call sites pick the change up automatically.
RUST_TEST_ATTRIBUTE_NAMES: frozenset[str] = frozenset({"test", "rstest"})


def attribute_is_test_marker(attribute: tree_sitter.Node) -> bool:
    """Return True if *attribute* (inner ``attribute`` node) is a test marker.

    Caller's responsibility: pass an ``attribute`` node, not the
    wrapping ``attribute_item``. Use :func:`attribute_item_is_test_marker`
    if you have the wrapper.
    """
    children = attribute.named_children
    if not children:  # pragma: no cover - defensive: every attribute has at least a name child
        return False
    return _first_child_marks_test(children)


def attribute_item_is_test_marker(attr_item: tree_sitter.Node) -> bool:
    """Return True if *attr_item* (outer ``attribute_item`` wrapper) is a test marker.

    Convenience wrapper: extracts the inner ``attribute`` child and
    delegates to :func:`attribute_is_test_marker`.
    """
    attribute = next((c for c in attr_item.named_children if c.type == _RUST_ATTRIBUTE), None)
    if attribute is None:  # pragma: no cover - defensive: every attribute_item wraps an attribute
        return False
    return attribute_is_test_marker(attribute)


def _first_child_marks_test(children: list[tree_sitter.Node]) -> bool:
    """Dispatch the test-marker check on an attribute's first named child."""
    first = children[0]
    if first.type == _RUST_SCOPED_IDENTIFIER:
        trailing = first.child_by_field_name("name")
        return trailing is not None and node_text(trailing) in RUST_TEST_ATTRIBUTE_NAMES
    if first.type != _RUST_IDENTIFIER:  # pragma: no cover - defensive: rare attribute shapes (token_tree-first etc.)
        return False
    first_name = node_text(first)
    if first_name in RUST_TEST_ATTRIBUTE_NAMES:
        return True
    if first_name != "cfg":
        return False
    return _cfg_token_tree_mentions_test(children[1:])


def _cfg_token_tree_mentions_test(children: list[tree_sitter.Node]) -> bool:
    """Return True if any ``token_tree`` in *children* contains ``identifier "test"``.

    Used by the ``#[cfg(test)]`` branch of :func:`_first_child_marks_test`.
    """
    for child in children:
        if child.type != "token_tree":  # pragma: no cover - ``#[cfg = "value"]`` shape isn't a test marker
            continue
        if any(inner.type == _RUST_IDENTIFIER and node_text(inner) == "test" for inner in child.named_children):
            return True
    return False
