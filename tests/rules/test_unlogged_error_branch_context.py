"""SAFE207: error branches that report through a helper, or enumerate a known case.

Two shapes were reported as unlogged that are not (#161). Together they were 6 of
9 and 1 of 9 findings on the project where they were found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe207(sample: Path) -> list[int]:
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"unlogged_error_branch": {"enabled": True}}}))
    return [v.lineno for v in engine.check_file(str(sample)).violations if v.code == "SAFE207"]


def test_reporting_through_a_same_file_helper_counts_as_logging(tmp_path: Path) -> None:
    """Factoring error reporting into a helper is good practice, and defeated the check.

    The error is logged *and* recorded, one call hop away; the intra-statement
    search saw neither.
    """
    sample = tmp_path / "restore.rs"
    sample.write_text(
        "use tracing::warn;\n\n"
        "fn fail(&mut self, object: &str, reason: String) {\n"
        '    warn!(object, %reason, "object failed; continuing");\n'
        "    self.outcome.failed.push((object.to_string(), reason));\n"
        "}\n\n"
        "fn restore(&mut self) {\n"
        "    match op() {\n"
        "        Ok(v) => v,\n"
        "        Err(e) => self.fail(&object.name, e.to_string()),\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    assert _safe207(sample) == []


def test_a_helper_that_does_not_log_is_not_credited(tmp_path: Path) -> None:
    """The control: delegating to a helper that only records is still silent.

    Without this, "the body calls something" would be mistaken for "the body
    logs".
    """
    sample = tmp_path / "record.rs"
    sample.write_text(
        "fn record(&mut self, reason: String) {\n"
        "    self.outcome.failed.push(reason);\n"
        "}\n\n"
        "fn restore(&mut self) {\n"
        "    match op() {\n"
        "        Ok(v) => v,\n"
        "        Err(e) => self.record(e.to_string()),\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    assert _safe207(sample) == [8]


_VARIANT_ARMS: list[tuple[str, str, list[int]]] = [
    # Enumerating a known case, with no error value in scope to log.
    ("braced variant, no binding", "Err(store::Error::NotFound { .. }) => Ok(false),", []),
    ("unit variant, no binding", "Err(Error::NotFound) => Ok(false),", []),
    # These bind part of the error, so the author has a value and could log it.
    ("tuple variant binds the error", "Err(store::Error::Io(e)) => Ok(false),", [4]),
    ("struct variant binds a field", "Err(store::Error::Io { source }) => Ok(false),", [4]),
    # Neither discriminates anything.
    ("plain binding", "Err(other) => Ok(false),", [4]),
    ("wildcard", "Err(_) => Ok(false),", [4]),
]


@pytest.mark.parametrize(["label", "arm", "expected"], _VARIANT_ARMS, ids=[case[0] for case in _VARIANT_ARMS])
def test_discriminating_a_specific_error_variant_is_not_swallowing(tmp_path: Path, label: str, arm: str, expected: list[int]) -> None:
    """An arm naming one variant and binding nothing enumerates a known case.

    ``Err(store::Error::NotFound { .. }) => Ok(false)`` implements a documented
    "treat not-found as false" contract while the next arm propagates everything
    else, and there is no error value in scope to log - the rule was asking for a
    message with nothing in it. Deliberately narrow: a pattern that binds part of
    the error still reports.
    """
    sample = tmp_path / "variant.rs"
    sample.write_text(
        f"fn f() -> Result<bool, E> {{\n    match op() {{\n        Ok(_) => Ok(true),\n        {arm}\n        Err(e) => Err(e),\n    }}\n}}\n",
        encoding="utf-8",
    )
    assert _safe207(sample) == expected, label


def test_a_direct_log_call_is_unaffected(tmp_path: Path) -> None:
    """The existing path still works: a log macro in the arm body."""
    sample = tmp_path / "direct.rs"
    sample.write_text(
        'fn f() {\n    match op() {\n        Ok(v) => v,\n        Err(e) => { warn!("{}", e); }\n    }\n}\n',
        encoding="utf-8",
    )
    assert _safe207(sample) == []
