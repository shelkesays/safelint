"""Targeted tests for :mod:`safelint.analysis.dataflow_java`.

The Java taint tracker is exercised end-to-end through SAFE801 in
``tests/integration/test_spring_boot_e2e.py`` and through SAFE803 in
``tests/rules/test_spring_rules.py``; this module fills the remaining
coverage gaps with direct unit tests against the tracker's public
``visit`` / ``sink_hits`` surface.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
from typing import TYPE_CHECKING

from safelint.analysis.dataflow_java import JavaTaintTracker
from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
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


# ---------------------------------------------------------------------------
# Method-invocation receiver as a taint input
# ---------------------------------------------------------------------------


def test_method_invocation_receiver_propagates_taint_through_unknown_call() -> None:
    """``tainted.trim()`` returns a tainted value via ``assume_taint_preserving``.

    Without the receiver-as-input check, ``input.trim()`` would have
    zero args and silently drop taint, producing false negatives on
    common Java string transformations.
    """
    tree = _parse(
        """
        class C {
            void m(String input) {
                String s = input.trim();
                exec(s);
            }
        }
        """
    )
    tracker = _make_tracker()
    tracker.visit(_find_method(tree, "m"))
    # ``input.trim()`` propagates taint via the receiver; ``s`` is
    # tainted; the subsequent exec fires.
    assert len(tracker.sink_hits) == 1


def test_sink_fires_on_tainted_receiver_with_no_arguments() -> None:
    """``url.openStream()`` on a tainted ``url`` fires the sink with zero args.

    Canonical Java SSRF pattern: ``URL url = new URL(userInput);
    url.openStream();``. ``openStream`` has no arguments, so a
    args-only sink check would miss the hit entirely. The
    receiver-as-input check fires correctly.
    """
    tree = _parse(
        """
        class C {
            void m(Url url) {
                url.openStream();
            }
        }
        """
    )
    tracker = JavaTaintTracker(
        params={"url"},
        sinks=frozenset({"openStream"}),
        sanitizers=frozenset(),
        sources=frozenset(),
    )
    tracker.visit(_find_method(tree, "m"))
    assert len(tracker.sink_hits) == 1
    # The recorded "tainted variable" is the receiver identifier.
    assert tracker.sink_hits[0][1] == "url"


def test_single_arg_lambda_seeds_parameter() -> None:
    """Untyped single-arg lambda ``u -> ...`` seeds ``u`` as tainted.

    tree-sitter-java emits this shape with ``parameters`` field
    pointing at the bare ``identifier`` itself - no wrapping
    ``inferred_parameters`` / ``formal_parameters`` container.
    Common in Java stream chains:
    ``list.stream().filter(u -> dangerous(u))``. Without the
    identifier-shape branch in ``_java_param_names``, ``u`` would
    silently not seed and SAFE801 would miss sinks reachable
    through the lambda body.
    """
    # Mirror the rule's param-extraction path via the helper used
    # by SAFE801 directly so the test exercises the dispatch.
    from safelint.rules.dataflow import _java_param_names  # noqa: PLC0415

    tree = _parse(
        """
        class C {
            void m() {
                things.forEach(u -> dangerous(u));
            }
        }
        """
    )
    # Walk to the lambda_expression and confirm _java_param_names
    # returns the bound identifier.
    from safelint.languages._node_utils import walk  # noqa: PLC0415

    lambda_node = next(n for n in walk(tree.root_node) if n.type == "lambda_expression")
    assert _java_param_names(lambda_node) == {"u"}


def test_passthrough_unwrap_exercised_by_cast_in_sink_receiver() -> None:
    """A cast expression on the sink receiver exercises ``_peel_java_passthrough``.

    The receiver-as-input check for ``method_invocation`` runs the
    receiver through ``_peel_java_passthrough`` to strip
    ``cast_expression`` / ``parenthesized_expression`` wrappers before
    looking up the identifier. Without a test that actually presents
    a cast wrapping a tainted receiver, that helper's loop body never
    executes.

    ``((String) input).trim()`` casts the parameter then invokes a
    method; the trim() result feeds into ``exec``. Taint propagates
    from the cast receiver through the unwrap.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(String input) {
                exec(((String) input).trim());
            }
            void exec(String s) {}
        }
        """
    )
    overrides = {
        "rules": {
            "tainted_sink": {
                "enabled": True,
                "sinks_java": ["exec"],
                "sanitizers_java": [],
                "sources_java": [],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE801" for v in result.violations), "Tainted receiver wrapped in cast should still reach the sink"


def test_safe803_unwraps_cast_around_nullable_receiver() -> None:
    """``((Foo) map.get(k)).bar`` exercises ``_peel_java_passthrough`` in SAFE803.

    The Java SAFE803 path peels ``parenthesized_expression`` and
    ``cast_expression`` wrappers off the dereference receiver before
    matching it against ``nullable_methods_java``. Without this test the
    helper's loop body never executes from any other path.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(java.util.Map<String, Foo> map, String k) {
                String s = ((Foo) map.get(k)).toString();
            }
        }
        """
    )
    overrides = {
        "rules": {
            "null_dereference": {
                "enabled": True,
                "nullable_methods_java": ["get"],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE803" for v in result.violations), "Cast wrapping a nullable .get() result should still trigger SAFE803"


def test_scoped_object_creation_name_resolves_trailing_identifier() -> None:
    """``new java.io.FileInputStream(input)`` resolves to ``"FileInputStream"``.

    Exercises ``_java_object_creation_name`` /  ``_last_type_identifier``
    in :mod:`safelint.languages._node_utils`. The qualified form is
    legal Java (used to disambiguate when the class isn't imported)
    and tree-sitter-java emits ``scoped_type_identifier`` as the type
    field of the ``object_creation_expression``. The helper walks the
    scoped identifier's named children and returns the trailing
    ``type_identifier``.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(String input) {
                Object stream = new java.io.FileInputStream(input);
            }
        }
        """
    )
    overrides = {
        "rules": {
            "tainted_sink": {
                "enabled": True,
                "sinks_java": ["FileInputStream"],
                "sanitizers_java": [],
                "sources_java": [],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE801" for v in result.violations), "Scoped-type ``new java.io.FileInputStream(input)`` should match the FileInputStream sink"


def test_lambda_captures_enclosing_method_param_for_taint() -> None:
    """A lambda inside ``m(String input)`` that uses ``input`` reaches SAFE801.

    Without seeding the lambda's tracker with the enclosing method's
    params as captures, the analyser would see the lambda as
    parameter-less and miss the fact that ``input`` (tainted via the
    enclosing method's entry seed) reaches the sink ``exec``. This is
    the over-approximation strategy: treat all enclosing method params
    as potentially-captured-and-tainted in any nested lambda.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(String input) {
                java.util.List.of("a").forEach(s -> exec(input));
            }
            void exec(String s) {}
        }
        """
    )
    overrides = {
        "rules": {
            "tainted_sink": {
                "enabled": True,
                "sinks_java": ["exec"],
                "sanitizers_java": [],
                "sources_java": [],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE801" for v in result.violations), "Lambda capturing enclosing method param ``input`` should reach SAFE801"


def test_constructor_call_does_not_apply_receiver_check() -> None:
    """``new Foo(...)`` has no receiver; only arguments are inspected.

    Confirms the receiver-as-input check is gated on
    ``method_invocation``: ``object_creation_expression`` still
    follows the args-only path.
    """
    tree = _parse(
        """
        class C {
            void m(String input) {
                FileInputStream s = new FileInputStream(input);
            }
        }
        """
    )
    tracker = JavaTaintTracker(
        params={"input"},
        sinks=frozenset({"FileInputStream"}),
        sanitizers=frozenset(),
        sources=frozenset(),
    )
    tracker.visit(_find_method(tree, "m"))
    # The single tainted arg fires the sink.
    assert len(tracker.sink_hits) == 1
    assert tracker.sink_hits[0][1] == "input"


def test_generic_type_object_creation_resolves_to_trailing_identifier() -> None:
    """``new MyResource<Foo>(input)`` resolves to ``"MyResource"`` via generic_type unwrap.

    tree-sitter-java emits ``generic_type`` as a wrapper around the
    underlying type_identifier / scoped_type_identifier; without the
    unwrap branch, SAFE401 tracked-acquirers / SAFE801 constructor
    sinks / SAFE303-304 I/O constructors silently miss every generic
    instantiation.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(String input) {
                Object r = new MyResource<Foo>(input);
            }
        }
        """
    )
    overrides = {
        "rules": {
            "tainted_sink": {
                "enabled": True,
                "sinks_java": ["MyResource"],
                "sanitizers_java": [],
                "sources_java": [],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE801" for v in result.violations), "Generic-type object creation should match the configured sink name"


def test_safe202_multi_comment_java_catch_is_empty() -> None:
    """tree-sitter-java emits each comment as a named child; multi-comment catch is no-op.

    Previously ``_is_noop_body`` required exactly one child so
    ``catch (Exception e) { // a\\n  // b\\n }`` (two comments)
    fell through with False. The all-children-no-op variant
    correctly classifies multi-comment bodies as empty.
    """
    src = textwrap.dedent(
        """
        class C {
            void m() {
                try {
                    work();
                } catch (Exception e) {
                    // todo 1
                    // todo 2
                }
            }
            void work() {}
        }
        """
    )
    overrides = {
        "rules": {"empty_except": {"enabled": True}},
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE202" for v in result.violations), "Multi-comment catch body should still trigger SAFE202 as empty"


def test_lambda_captures_enclosing_method_local_for_taint() -> None:
    """``String dirty = input; run(() -> exec(dirty));`` reaches SAFE801.

    The reviewer's deeper finding: seeding only enclosing-method params
    misses tainted LOCALS (``dirty`` is a local, not a param).
    The two-pass _java_check analyses the enclosing method first, caches
    its final tainted set (which includes ``dirty`` after the assignment
    from ``input``), then seeds the lambda's tracker with that set so
    ``exec(dirty)`` fires.
    """
    src = textwrap.dedent(
        """
        class C {
            void m(String input) {
                String dirty = input;
                java.util.List.of("a").forEach(s -> exec(dirty));
            }
            void exec(String s) {}
            void run(Runnable r) {}
        }
        """
    )
    overrides = {
        "rules": {
            "tainted_sink": {
                "enabled": True,
                "sinks_java": ["exec"],
                "sanitizers_java": [],
                "sources_java": [],
            }
        }
    }
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "C.java"
        path.write_text(src)
        engine = SafetyEngine(deep_merge(DEFAULTS, overrides))
        result = engine.check_file(str(path))
    assert any(v.code == "SAFE801" for v in result.violations), "Lambda capturing enclosing method LOCAL ``dirty`` should reach SAFE801"
