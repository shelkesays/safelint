"""Targeted tests for :mod:`safelint.analysis.dataflow_java`.

The Java taint tracker is exercised end-to-end through SAFE801 in
``tests/integration/test_spring_boot_e2e.py`` and through SAFE803 in
``tests/rules/test_spring_rules.py``; this module fills the remaining
coverage gaps with direct unit tests against the tracker's public
``visit`` / ``sink_hits`` surface.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

from safelint.analysis.dataflow_java import JavaTaintTracker
from safelint.languages._node_utils import node_text
from safelint.languages.java import JAVA


if TYPE_CHECKING:
    import tree_sitter


def _parse(src: str) -> tree_sitter.Tree:
    """Parse *src* as Java and return the tree."""
    return JAVA.create_parser().parse(textwrap.dedent(src).encode("utf-8"))


def _find_method(tree: tree_sitter.Tree, name: str) -> tree_sitter.Node:
    """Return the first ``method_declaration`` whose name matches *name*."""
    from safelint.languages._node_utils import walk  # noqa: PLC0415

    for node in walk(tree.root_node):
        if node.type != "method_declaration":
            continue
        name_node = node.child_by_field_name("name")
        if name_node is not None and node_text(name_node) == name:
            return node
    msg = f"method {name!r} not found in tree"
    raise LookupError(msg)


def _make_tracker(*, assume_taint_preserving: bool = True) -> JavaTaintTracker:
    """Build a tracker with one canonical taint source / sink / sanitiser each."""
    return JavaTaintTracker(
        params={"input"},
        sinks=frozenset({"exec"}),
        sanitizers=frozenset({"escape"}),
        sources=frozenset({"readLine"}),
        assume_taint_preserving=assume_taint_preserving,
    )


# ---------------------------------------------------------------------------
# Taint propagation through assignment / declaration
# ---------------------------------------------------------------------------


def test_variable_declaration_without_initialiser_starts_untainted() -> None:
    """``Type x;`` (no value) leaves ``x`` out of the tainted set.

    Exercises the early-return path in ``_visit_var_declarator`` when
    the ``value`` field is None. The variable name appears in the
    source but the tracker doesn't add it to the tainted set, so a
    later ``exec(x)`` call doesn't fire.
    """
    tree = _parse(
        """
        class C {
            void m(String input) {
                String x;
                exec(x);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    # ``input`` (the parameter) is tainted by construction, but the
    # local ``x`` was never initialised so the sink call uses an
    # untainted name. No hit.
    sinks = [hit[1] for hit in tracker.sink_hits]
    assert "x" not in sinks


def test_assume_taint_preserving_false_drops_unknown_calls() -> None:
    """With ``assume_taint_preserving=False``, unknown calls return untainted.

    Exercises the ``if not self.assume_taint_preserving: return False``
    branch in ``_call_tainted``. Setting the knob to False is the
    less-noisy posture: only explicit sources inject taint, and
    pass-through wrappers stop propagating.
    """
    tree = _parse(
        """
        class C {
            void m(String input) {
                String wrapped = unknownTransform(input);
                exec(wrapped);
            }
        }
        """
    )
    tracker = _make_tracker(assume_taint_preserving=False)
    tracker.visit(_find_method(tree, "m"))
    # ``unknownTransform`` isn't in sources/sanitizers; under
    # assume_taint_preserving=False, the wrapper drops the taint.
    # No hit on the subsequent exec.
    assert tracker.sink_hits == []


def test_assume_taint_preserving_true_propagates_through_unknown_calls() -> None:
    """Default (True) propagates taint through unknown calls."""
    tree = _parse(
        """
        class C {
            void m(String input) {
                String wrapped = unknownTransform(input);
                exec(wrapped);
            }
        }
        """
    )
    tracker = _make_tracker(assume_taint_preserving=True)
    tracker.visit(_find_method(tree, "m"))
    # ``unknownTransform`` preserves taint by default; the exec sees
    # tainted ``wrapped`` and fires.
    assert len(tracker.sink_hits) == 1
    assert tracker.sink_hits[0][2] == "exec"


def test_sanitiser_call_clears_taint() -> None:
    """``escape(input)`` returns untainted regardless of arg taint state.

    Exercises the ``if name in self.sanitizers: return False`` branch
    in ``_call_tainted``.
    """
    tree = _parse(
        """
        class C {
            void m(String input) {
                String clean = escape(input);
                exec(clean);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    # ``escape`` is a sanitiser - clears taint. The subsequent exec
    # sees ``clean`` as untainted. No hit.
    assert tracker.sink_hits == []


def test_source_call_injects_taint() -> None:
    """``readLine()`` returns tainted even when arguments are untainted.

    Exercises the ``if name in self.sources: return True`` branch.
    """
    tree = _parse(
        """
        class C {
            void m() {
                String dirty = readLine();
                exec(dirty);
            }
        }
        """
    )
    tracker = JavaTaintTracker(
        params=set(),  # no tainted entry params - source call is the only seed
        sinks=frozenset({"exec"}),
        sanitizers=frozenset(),
        sources=frozenset({"readLine"}),
    )
    tracker.visit(_find_method(tree, "m"))
    # ``readLine`` is a source - injects taint into ``dirty``. The
    # subsequent exec sees ``dirty`` as tainted and fires.
    assert len(tracker.sink_hits) == 1


def test_assignment_with_non_identifier_lhs_is_ignored() -> None:
    """``obj.field = tainted`` doesn't update the tracker (we don't track fields).

    Exercises the ``if left.type != "identifier": return`` branch in
    ``_visit_assignment``. Field writes don't add or remove names
    from the tainted set - safelint deliberately does not model
    field-level taint.
    """
    tree = _parse(
        """
        class C {
            Object f;
            void m(String input) {
                this.f = input;
                exec(this.f);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    # ``this.f = input`` is a field write the tracker doesn't model.
    # The subsequent ``exec(this.f)`` reads from a field_access node
    # whose receiver is ``this`` (not an identifier we track), so
    # the rule doesn't fire on this specific path.
    # Pre-existing behaviour: the tracker treats field reads as
    # taint-propagating from the receiver; ``this`` is untainted by
    # default, so no hit.
    assert tracker.sink_hits == []


# ---------------------------------------------------------------------------
# Member / container expression taint propagation
# ---------------------------------------------------------------------------


def test_array_access_propagates_taint_from_receiver() -> None:
    """``arr[0]`` is tainted when ``arr`` is in the tainted set."""
    tree = _parse(
        """
        class C {
            void m(String[] input) {
                exec(input[0]);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    # ``input[0]`` is array_access on the tainted ``input`` receiver;
    # taint flows through to the exec arg.
    assert len(tracker.sink_hits) == 1


def test_field_access_propagates_taint_from_receiver() -> None:
    """``obj.field`` is tainted when ``obj`` is in the tainted set."""
    tree = _parse(
        """
        class C {
            void m(Request input) {
                exec(input.body);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    assert len(tracker.sink_hits) == 1


def test_string_concatenation_propagates_taint() -> None:
    """``"prefix " + tainted`` keeps the result tainted (binary_expression on String)."""
    tree = _parse(
        """
        class C {
            void m(String input) {
                String s = "hello " + input;
                exec(s);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    assert len(tracker.sink_hits) == 1


def test_cast_expression_passes_through_taint() -> None:
    """``(String) tainted`` is a zero-cost cast - taint flows through."""
    tree = _parse(
        """
        class C {
            void m(Object input) {
                exec((String) input);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    assert len(tracker.sink_hits) == 1
