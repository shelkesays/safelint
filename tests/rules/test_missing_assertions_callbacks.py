"""SAFE601: a test's callbacks assert on the test's behalf (#252).

The assertion counters walk a body with ``skip_types=function_types``, so they
stop at any nested function. For a callback-style test that is wrong: the
assertions live inside a callback the test hands to something else, and the test
read as assertion-free. On Express, 10 of 89 findings were this shape.

The skip itself is load-bearing and is kept for every function that is NOT a
test, which is the false negative it was added for: an outer function must not
be credited for the asserts inside an inner definition. Inside a test there is
nothing to protect against, because whatever a test's callbacks assert, the test
asserts. Both directions are pinned here.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe601(sample: Path, overrides: dict | None = None) -> list[str]:
    """Return the SAFE601 messages for *sample*, scoped to tests by default."""
    rule: dict[str, object] = {"enabled": True}
    if overrides:
        rule.update(overrides)
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"missing_assertions": rule}}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE601"]


def _write(tmp_path: Path, name: str, source: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(source), encoding="utf-8")
    return sample


# (label, filename, source): one test per language whose only assertion sits
# inside a callback it registers with something that is not a test runner.
_ASSERTION_IN_A_CALLBACK: list[tuple[str, str, str]] = [
    (
        "javascript route handler",
        "router.test.js",
        """\
        it('should not mix requests', function (done) {
          var cb = after(2, done);
          router.param('ms', function (req, res, next, ms) {
            assert.equal(ms, 50);
            next();
          });
          router.handle({ url: '/foo/50/bar', method: 'get' }, {}, cb);
        });
        """,
    ),
    (
        "javascript promise continuation",
        "fetch.test.js",
        """\
        it('resolves to the payload', function () {
          return fetchThing().then(function (payload) {
            expect(payload.id).toBe(7);
          });
        });
        """,
    ),
    (
        "python callback passed by reference",
        "test_client.py",
        """\
        def test_retries_until_it_succeeds(client):
            def on_response(response):
                assert response.status == 200

            client.subscribe(on_response)
            client.drain()
        """,
    ),
    (
        "java lambda",
        "ThingTest.java",
        """\
        class ThingTest {
            @Test
            void everyEntryIsPositive() {
                values.forEach(value -> assertTrue(value > 0));
            }
        }
        """,
    ),
    (
        "go closure",
        "server_test.go",
        """\
        func TestServesTheBody(t *testing.T) {
        \tsrv.Handler = func(w http.ResponseWriter, r *http.Request) {
        \t\tif r.URL.Path != "/ok" {
        \t\t\tt.Errorf("got %s", r.URL.Path)
        \t\t}
        \t}
        \tsrv.Serve()
        }
        """,
    ),
    (
        "rust closure",
        "thing_test.rs",
        """\
        #[test]
        fn every_entry_is_positive() {
            values.iter().for_each(|value| assert!(*value > 0));
        }
        """,
    ),
]


@pytest.mark.parametrize(["label", "filename", "source"], _ASSERTION_IN_A_CALLBACK, ids=[case[0] for case in _ASSERTION_IN_A_CALLBACK])
def test_an_assertion_in_a_callback_counts_for_the_test(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """The test asserts, so it does not report."""
    assert _safe601(_write(tmp_path, filename, source)) == [], label


def test_a_callback_style_test_that_asserts_nothing_still_reports(tmp_path: Path) -> None:
    """Express's other 79 findings: a test that only calls ``done()``.

    The control for the whole change. Counting inside callbacks can only ever
    suppress findings, so without this the parametrised cases above would pass
    just as well on a rule that had stopped firing altogether.
    """
    sample = _write(
        tmp_path,
        "router.test.js",
        """\
        it('should not mix requests', function (done) {
          router.param('ms', function (req, res, next, ms) {
            next();
          });
          router.handle({ url: '/foo/50/bar', method: 'get' }, {}, done);
        });
        """,
    )
    assert _safe601(sample) == ['Test "should not mix requests" has no assertions']


def test_a_non_test_function_is_not_credited_for_a_nested_definition(tmp_path: Path) -> None:
    """The original false negative, preserved: the skip still applies outside a test.

    This is why the skip exists. With ``test_functions_only = false`` the rule
    checks every function, and ``handle`` asserts nothing of its own - the
    assertion belongs to a helper it happens to define. Dropping the skip
    everywhere instead of only inside tests would have made this read clean.
    """
    sample = _write(
        tmp_path,
        "service.py",
        """\
        def handle(payload):
            def check(value):
                assert value is not None

            return [check(v) for v in payload]
        """,
    )
    assert _safe601(sample, {"test_functions_only": False}) == ['Function "handle" has no assertions']


def test_a_registering_function_is_still_skipped_rather_than_credited(tmp_path: Path) -> None:
    """A ``describe`` block does not become a passing test by containing one.

    The delegation guard returns before any counting, so the change here cannot
    turn a registering function into a satisfied one; each ``it`` it registers
    is still answerable on its own. Without this, counting into nested
    functions would have made every ``describe`` clean and hidden its tests.
    """
    sample = _write(
        tmp_path,
        "suite.test.js",
        """\
        describe('the parser', function () {
          it('accepts a valid document', function () {
            expect(parse('{}')).toEqual({});
          });

          it('rejects a truncated document', function () {
            parse('{');
          });
        });
        """,
    )
    assert _safe601(sample) == ['Test "rejects a truncated document" has no assertions']


def test_a_nested_definition_inside_a_test_counts_and_that_is_the_trade(tmp_path: Path) -> None:
    """The one shape given up, recorded rather than left to be discovered.

    An inner definition inside a test credits the test even when nothing calls
    it, because "handed to someone else" and "defined and never used" are the
    same tree shape: the callback cases above pass the function by reference
    too, so no rule distinguishes them without following the value. A test
    carrying a dead assertion helper is a rare and minor thing to miss next to
    the callback tests it unblocks, and the finding would be about dead code
    rather than about assertions anyway.
    """
    sample = _write(
        tmp_path,
        "test_thing.py",
        """\
        def test_does_nothing_at_all():
            def unused(value):
                assert value is not None

            pass
        """,
    )
    assert _safe601(sample) == []
