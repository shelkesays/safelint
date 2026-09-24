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


#: ``(extension, config suffix, tainted write, non-sink write, sanitised write)``.
#: Property-assignment sinks per language; the JS row is covered in depth by
#: ``tests/rules/test_dataflow_javascript.py``.
_ASSIGNMENT_SINKS = [
    ("py", "", "def f(u):\n    o.danger = u\n", "def f(u):\n    o.safe = u\n", "def f(u):\n    o.danger = escape(u)\n"),
    ("js", "_javascript", "function f(u){ o.danger = u; }\n", "function f(u){ o.safe = u; }\n", "function f(u){ o.danger = escape(u); }\n"),
    ("java", "_java", "class A { void f(String u){ o.danger = u; } }\n", "class A { void f(String u){ o.safe = u; } }\n", "class A { void f(String u){ o.danger = escape(u); } }\n"),
    ("rs", "_rust", "fn f(u: &str) { o.danger = u; }\n", "fn f(u: &str) { o.safe = u; }\n", "fn f(u: &str) { o.danger = escape(u); }\n"),
    ("go", "_go", "package m\nfunc f(u string) { o.danger = u }\n", "package m\nfunc f(u string) { o.safe = u }\n", "package m\nfunc f(u string) { o.danger = escape(u) }\n"),
    ("php", "_php", "<?php function f($u){ $o->danger = $u; }\n", "<?php function f($u){ $o->safe = $u; }\n", "<?php function f($u){ $o->danger = escape($u); }\n"),
    ("c", "_c", "void f(char* u){ o.danger = u; }\n", "void f(char* u){ o.safe = u; }\n", "void f(char* u){ o.danger = escape(u); }\n"),
    ("cpp", "_cpp", "void f(char* u){ o.danger = u; }\n", "void f(char* u){ o.safe = u; }\n", "void f(char* u){ o.danger = escape(u); }\n"),
]


def _assignment_fires(ext: str, suffix: str, src: str, tmp_path: Path) -> bool:
    """Return True if SAFE801 fires for *src* with ``danger`` an assignment sink.

    Declared via ``assignment_sinks*``, NOT the flat ``sinks*`` list: outside
    JavaScript those hold function names, so treating them as write-sinks
    reported every field named ``query`` / ``args`` / ``load`` as an injection.
    """
    sample = tmp_path / f"assign.{ext}"
    sample.write_text(src, encoding="utf-8")
    rule_cfg = {"enabled": True, f"assignment_sinks{suffix}": ["danger"], f"sanitizers{suffix}": ["escape"]}
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    return any(v.code == "SAFE801" for v in engine.check_file(str(sample)).violations)


@pytest.mark.parametrize(
    ["ext", "suffix", "tainted", "non_sink", "sanitised"],
    _ASSIGNMENT_SINKS,
    ids=[case[0] for case in _ASSIGNMENT_SINKS],
)
def test_assignment_side_sinks_in_every_language(ext: str, suffix: str, tainted: str, non_sink: str, sanitised: str, tmp_path: Path) -> None:
    """Writing a tainted value to a sink-named property fires, in every language.

    `innerHTML` shipped as a JavaScript default for years without ever firing on
    the assignment that actually causes the injection. The capability is now
    uniform, so pin all three halves per language: the write fires, a write to a
    non-sink property does not, and a sanitised write clears."""
    assert _assignment_fires(ext, suffix, tainted, tmp_path), f"{ext}: tainted write to a sink did not fire"
    assert not _assignment_fires(ext, suffix, non_sink, tmp_path), f"{ext}: write to a non-sink property fired"
    assert not _assignment_fires(ext, suffix, sanitised, tmp_path), f"{ext}: sanitised write was not cleared"


@pytest.mark.parametrize(
    ["ext", "suffix", "tainted", "non_sink", "sanitised"],
    _ASSIGNMENT_SINKS,
    ids=[case[0] for case in _ASSIGNMENT_SINKS],
)
def test_call_sink_list_does_not_make_field_writes_fire(ext: str, suffix: str, tainted: str, non_sink: str, sanitised: str, tmp_path: Path) -> None:
    """A name in the CALL sink list is not treated as a write-sink.

    Outside JavaScript the `sinks_*` lists hold function names, so reusing them
    for assignment targets reported ordinary field writes - `c.args = u` in
    Rust, `p.Query = q` in Go, `$this->query = ...` in PHP - as injections with
    the shipped defaults. A write-sink must be declared in `assignment_sinks_*`.
    """
    del non_sink, sanitised
    sample = tmp_path / f"call_only.{ext}"
    sample.write_text(tainted, encoding="utf-8")
    rule_cfg = {"enabled": True, f"sinks{suffix}": ["danger"]}
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": rule_cfg}}))
    assert not [v for v in engine.check_file(str(sample)).violations if v.code == "SAFE801"], f"{ext}: a call-sink name fired on a field write"
