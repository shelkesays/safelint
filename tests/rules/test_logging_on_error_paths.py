"""SAFE203: which handlers actually swallow an error, and where the leak is.

The rule asked whether the handler body was *exactly* one bare re-raise, which is
far narrower than the message's claim that the error is "swallowed". Three shapes
propagate the failure and were reported anyway (#159, #199), and a handler that
branches was reported at the ``except`` line even when only one arm fell through.

Containment is deliberately not the test. This body really does swallow::

    if never_true:
        raise
    return None

so the question is whether every *exit path* propagates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe203(sample: Path) -> list[int]:
    """Return the lines SAFE203 fires on in *sample*."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"logging_on_error": {"enabled": True}}}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == "SAFE203"]


_PROPAGATING_HANDLERS = [
    # #159: the idiomatic add-context re-raise. Logging here yields two reports
    # of one failure, which is worse than not logging.
    ["python raise ... from err", "a.py", 'try:\n    f()\nexcept ValueError as err:\n    raise RuntimeError("bad") from err\n'],
    # Python chains the active exception automatically inside an except block, so
    # a plain `raise X` keeps the original reachable via __context__.
    ["python raise X", "b.py", 'try:\n    f()\nexcept ValueError:\n    raise RuntimeError("bad")\n'],
    # #199: report then propagate - the body is two statements, so the
    # exactly-one test rejected it.
    ["python print then raise", "c.py", 'try:\n    f()\nexcept ValueError as exc:\n    print(f"failed: {exc}")\n    raise\n'],
    # Every arm raises, so nothing is swallowed on any path.
    ["python if/else both raise", "d.py", 'try:\n    f()\nexcept ValueError as e:\n    if a:\n        raise\n    else:\n        raise RuntimeError("x") from e\n'],
    ["python if/elif/else all raise", "e.py", "try:\n    f()\nexcept ValueError:\n    if a:\n        raise\n    elif b:\n        raise\n    else:\n        raise\n"],
    ["javascript if/else both throw", "f.js", "try { f(); } catch (e) { if (a) { throw e; } else { throw e; } }"],
    ["javascript else-if chain", "g.js", "try { f(); } catch (e) { if (a) { throw e; } else if (b) { throw e; } else { throw e; } }"],
    ["java else-if chain", "H.java", "class C { void f() throws Exception { try { g(); } catch (Exception e) { if (a) { throw e; } else if (b) { throw e; } else { throw e; } } } }"],
    ["php elseif chain", "i.php", "<?php\ntry { f(); } catch (Exception $e) { if ($a) { throw $e; } elseif ($b) { throw $e; } else { throw $e; } }"],
    ["cpp if/else both throw", "j.cpp", "void f() { try { g(); } catch (...) { if (a) { throw; } else { throw; } } }"],
]


@pytest.mark.parametrize(["label", "filename", "source"], tuple(_PROPAGATING_HANDLERS), ids=[case[0] for case in _PROPAGATING_HANDLERS])
def test_a_handler_that_propagates_on_every_path_is_clean(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """Nothing is swallowed when every exit path leaves by raising."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe203(sample) == [], label


_LEAKING_HANDLERS = [
    # The violation anchors at the arm that falls through, not at the `except`.
    ["else arm leaks", "a.py", "try:\n    f()\nexcept ValueError:\n    if a:\n        raise\n    elif b:\n        raise\n    else:\n        cleanup()\n", 9],
    ["elif arm leaks", "b.py", "try:\n    f()\nexcept ValueError:\n    if a:\n        raise\n    elif b:\n        cleanup()\n    else:\n        raise\n", 7],
    # No else at all: the no-match path falls straight through the conditional.
    ["no else arm", "c.py", "try:\n    f()\nexcept ValueError:\n    if a:\n        raise\n", 4],
    ["javascript chain with no final else", "e.js", "try { f(); } catch (e) { if (a) { throw e; } else if (b) { throw e; } }", 1],
]


@pytest.mark.parametrize(["label", "filename", "source", "expected_line"], tuple(_LEAKING_HANDLERS), ids=[case[0] for case in _LEAKING_HANDLERS])
def test_a_partially_propagating_handler_reports_at_the_leaking_arm(tmp_path: Path, label: str, filename: str, source: str, expected_line: int) -> None:
    """Point at the branch that falls through, not at the handler as a whole.

    On a handler with several arms, "something in here leaks" leaves the reader to
    work out which; naming the arm is the difference between a finding that is
    acted on and one that is scrolled past.
    """
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe203(sample) == [expected_line], label


def test_a_raise_off_the_exit_path_does_not_exempt_the_handler(tmp_path: Path) -> None:
    """Containment is not propagation.

    ``if never_true: raise`` followed by ``return None`` contains a ``raise`` but
    reaches ``return`` unconditionally, so the error really is swallowed. A
    "does the body mention a raise" test would wrongly clear it. The anchor is
    the clause rather than an arm, because the handler falls through as a whole -
    the conditional is not its last statement.
    """
    sample = tmp_path / "unreachable.py"
    sample.write_text("try:\n    f()\nexcept ValueError:\n    if never_true:\n        raise\n    return None\n", encoding="utf-8")
    assert _safe203(sample) == [3]


def test_a_wholly_swallowing_handler_still_reports_at_the_clause(tmp_path: Path) -> None:
    """When the whole handler falls through, the clause is the right anchor.

    Only the branching case gains from a narrower anchor; here the handler as a
    unit is the problem.
    """
    sample = tmp_path / "whole.py"
    sample.write_text("try:\n    f()\nexcept ValueError:\n    cleanup()\n", encoding="utf-8")
    found = _safe203(sample)
    assert found == [3]


def test_python_print_counts_as_surfacing_the_failure(tmp_path: Path) -> None:
    """``print`` / ``print_exception`` make the failure visible (#199).

    Rust's SAFE207, the documented analogue, has always accepted ``println`` /
    ``eprintln`` / ``print``; the same act was judged two ways across the two
    languages.
    """
    sample = tmp_path / "rich.py"
    sample.write_text("try:\n    f()\nexcept Exception:\n    console.print_exception(show_locals=True)\n", encoding="utf-8")
    assert _safe203(sample) == []


def test_java_println_does_not_count_as_logging(tmp_path: Path) -> None:
    """The print exemption is Python-only, and deliberately so.

    Java has a strong logging convention, and ``System.out.println`` inside a
    catch block is the anti-pattern the rule exists to find - not a fix for it. A
    flat cross-language print exemption would have silenced exactly that.
    """
    sample = tmp_path / "P.java"
    sample.write_text(
        'class C { void f() { try { g(); } catch (Exception e) { System.out.println("caught"); } } }\n',
        encoding="utf-8",
    )
    assert _safe203(sample) == [1]


def test_a_fresh_throw_still_requires_logging(tmp_path: Path) -> None:
    """Throwing a *fresh* error discards the original, so logging is still wanted.

    The distinction Python does not need - it chains the active exception
    automatically - but JavaScript, Java, PHP and C++ do.
    """
    sample = tmp_path / "fresh.js"
    sample.write_text('try { f(); } catch (e) { throw new Error("different"); }\n', encoding="utf-8")
    assert _safe203(sample) == [1]


def test_log_methods_is_configurable(tmp_path: Path) -> None:
    """The name list had no config key at all, so a user who disagreed had no recourse."""
    sample = tmp_path / "cfg.py"
    sample.write_text("try:\n    f()\nexcept ValueError:\n    notify_ops('boom')\n", encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"logging_on_error": {"enabled": True, "log_methods": ["notify_ops"]}}}))
    assert [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE203"] == []


_WRAPPING_THROWS = [
    ("javascript cause option", "w.js", 'try { f(); } catch (e) { throw new Error("ctx", { cause: e }); }\n'),
    ("java cause argument", "W.java", 'class W { void f() { try { g(); } catch (Exception e) { throw new RuntimeException("ctx", e); } } }\n'),
    ("php previous argument", "w.php", "<?php try { f(); } catch (Throwable $e) { throw new RuntimeException('ctx', 0, $e); }\n"),
    ("cpp thrown value", "w.cpp", "void f() {\n    try { g(); } catch (const std::exception& e) { throw std::runtime_error(e.what()); }\n}\n"),
]


@pytest.mark.parametrize(["label", "name", "src"], _WRAPPING_THROWS, ids=[case[0] for case in _WRAPPING_THROWS])
def test_a_fresh_throw_that_wraps_the_caught_value_is_clean(tmp_path: Path, label: str, name: str, src: str) -> None:
    """``throw new RuntimeException("ctx", e)`` is the C-family add-context re-raise.

    The caller sees the new error, but the original is attached to it and stays
    reachable, so nothing is swallowed. Exempting Python's
    ``raise RuntimeError(msg) from err`` while reporting this would be the same act
    judged two ways across languages that #199 is about.
    """
    sample = tmp_path / name
    sample.write_text(src, encoding="utf-8")
    assert _safe203(sample) == [], label


def test_a_javascript_factory_throw_is_not_treated_as_wrapping(tmp_path: Path) -> None:
    """``throw makeError(e)`` throws whatever that returns, which need not carry *e*.

    Only C++ constructs the thrown value with a plain call; in the other four
    languages the construction form is ``new``, so a bare call is not credited.
    """
    sample = tmp_path / "factory.js"
    sample.write_text("try { f(); } catch (e) { throw makeError(e); }\n", encoding="utf-8")
    assert _safe203(sample) == [1]


def test_a_branching_handler_where_no_arm_raises_is_reported_at_the_clause(tmp_path: Path) -> None:
    """The per-path message claims the other paths re-raise, so it must not be used here.

    Both arms fall through, so there is no "other path that does re-raise"; saying
    otherwise would state a fact about the code that is not true. The clause is
    the honest anchor, and the handler as a unit really is the problem.
    """
    sample = tmp_path / "noarm.py"
    sample.write_text("try:\n    f()\nexcept ValueError:\n    if a:\n        cleanup()\n    else:\n        other()\n", encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"logging_on_error": {"enabled": True}}}))
    found = [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE203"]
    assert [v.lineno for v in found] == [3]
    assert "other paths here do re-raise" not in found[0].message
