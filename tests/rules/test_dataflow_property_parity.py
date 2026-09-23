"""Cross-language parity for the property-typed sanitiser contract (SAFE801).

The seven taint trackers each implement the property contract independently, so
a semantic fixed in one can silently drift in the others. These tests pin the
two halves of the contract that matter most, in every language at once:

* a property-typed sanitiser CLEARS a sink requiring the property it establishes
  (``htmlsink(esc(u))`` is clean), and
* an intervening UNKNOWN call DROPS that property (``htmlsink(unesc(esc(u)))``
  still fires) - an unknown call may transform or decode its input, so it cannot
  be trusted to carry a safety property through.

The second case is the security-relevant direction: getting it wrong turns a
decoded value back into a "clean" one and loses the finding entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


#: ``(extension, config-key suffix, decoded-source, direct-source)`` per language.
#: The suffix is empty for Python (bare config keys) and ``_<lang>`` elsewhere.
#: C++ dispatches to the C tracker but resolves its own ``_cpp`` config keys, so
#: both are exercised.
_LANGUAGES = [
    ("py", "", "def f(u):\n    htmlsink(unesc(esc(u)))\n", "def f(u):\n    htmlsink(esc(u))\n"),
    ("js", "_javascript", "function f(u){ htmlsink(unesc(esc(u))); }\n", "function f(u){ htmlsink(esc(u)); }\n"),
    ("java", "_java", "class A { void f(String u){ htmlsink(unesc(esc(u))); } }\n", "class A { void f(String u){ htmlsink(esc(u)); } }\n"),
    ("rs", "_rust", "fn f(u: &str) { htmlsink(unesc(esc(u))); }\n", "fn f(u: &str) { htmlsink(esc(u)); }\n"),
    ("go", "_go", "package m\nfunc f(u string) { htmlsink(unesc(esc(u))) }\n", "package m\nfunc f(u string) { htmlsink(esc(u)) }\n"),
    ("php", "_php", "<?php function f($u){ htmlsink(unesc(esc($u))); }\n", "<?php function f($u){ htmlsink(esc($u)); }\n"),
    ("c", "_c", "void f(char* u){ htmlsink(unesc(esc(u))); }\n", "void f(char* u){ htmlsink(esc(u)); }\n"),
    ("cpp", "_cpp", "void f(char* u){ htmlsink(unesc(esc(u))); }\n", "void f(char* u){ htmlsink(esc(u)); }\n"),
]


def _fires(ext: str, suffix: str, src: str, tmp_path: Path) -> bool:
    """Return True if SAFE801 fires for *src* under a property-typed contract.

    ``esc`` establishes ``html`` and ``htmlsink`` requires it; the flat
    ``sanitizers`` list is emptied so only the property-typed behaviour is
    under test.
    """
    sample = tmp_path / f"sample.{ext}"
    sample.write_text(src, encoding="utf-8")
    rule_cfg = {
        "enabled": True,
        f"sinks{suffix}": ["htmlsink"],
        f"sanitizers{suffix}": [],
        f"sources{suffix}": [],
        f"sanitizer_properties{suffix}": {"esc": ["html"]},
        f"sink_properties{suffix}": {"htmlsink": "html"},
    }
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    return any(v.code == "SAFE801" for v in engine.check_file(str(sample)).violations)


@pytest.mark.parametrize(["ext", "suffix", "decoded", "direct"], _LANGUAGES, ids=[case[0] for case in _LANGUAGES])
def test_unknown_call_drops_property_in_every_language(ext: str, suffix: str, decoded: str, direct: str, tmp_path: Path) -> None:
    """An unknown call defeats a property clear; the direct clear still works."""
    assert _fires(ext, suffix, decoded, tmp_path), f"{ext}: unknown call preserved the cleared property"
    assert not _fires(ext, suffix, direct, tmp_path), f"{ext}: direct property clear did not clear the sink"
