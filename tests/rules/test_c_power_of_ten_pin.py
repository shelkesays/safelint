"""Power-of-Ten behavioural pin for C - representative cases, not exhaustive.

Written by the v2.7.0 post-release audit as a compact cross-rule regression
lock: if a future refactor (notably the C++ widening) changes one of these
audited C behaviours, the matching named case flips. It is NOT one-per-rule
and NOT complete - the per-rule ``tests/rules/test_*_c.py`` files are the
exhaustive coverage; this pin just trips fast on the behaviours most at risk.
Each case is the audit's minimal reproducer, using only built-in types
(``void *``, never library typedefs like ``FILE`` / ``jmp_buf``) so it matches
the shipped C test style and a parse quirk can never masquerade as a
behaviour regression.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path

_OPT_IN = {
    "rules": {
        n: {"enabled": True}
        for n in (
            "dynamic_allocation",
            "complex_macro",
            "conditional_compilation",
            "restricted_pointers",
            "missing_assertions",
            "dynamic_code_execution",
            "blanket_suppression",
            "tainted_sink",
            "return_value_ignored",
        )
    }
}

# (case id, source, code, fires?)
_CASES = [
    ("goto fires SAFE106", "void f(int x){ if(x) goto out; out: return; }", "SAFE106", True),
    ("setjmp fires SAFE106", "void f(void *b){ setjmp(b); }", "SAFE106", True),
    ("plain flow clean SAFE106", "int f(int x){ return x + 1; }", "SAFE106", False),
    ("direct recursion fires SAFE105", "int fact(int n){ return n < 2 ? 1 : n * fact(n - 1); }", "SAFE105", True),
    ("while(1) bare fires SAFE501", "void f(void){ while(1) { } }", "SAFE501", True),
    ("goto OUT of loop is an exit SAFE501", "void f(int x){ while(1){ if(x) goto done; } done: return; }", "SAFE501", False),
    ("goto WITHIN loop still unbounded SAFE501", "void f(int x){ while(1){ again: if(x) goto again; } }", "SAFE501", True),
    ("malloc fires SAFE310", "void *f(void){ return malloc(8); }", "SAFE310", True),
    ("no allocation clean SAFE310", "int f(int a){ return a; }", "SAFE310", False),
    ("assert satisfies SAFE601", "int f(int x){ assert(x); return 1 / x; }", "SAFE601", False),
    ("file-scope var fires SAFE302", "int counter;\nint f(void){ return counter; }", "SAFE302", True),
    ("const file-scope clean SAFE302", "const int MAX = 5;\nint f(void){ return MAX; }", "SAFE302", False),
    ("extern fwd-ref clean SAFE302", "extern int g;\nint f(void){ return g; }", "SAFE302", False),
    ("initialised extern fires SAFE302", "extern int g = 1;\nint f(void){ return g; }", "SAFE302", True),
    ("pointer-returning prototype clean SAFE302", "char *foo(void);\nchar *g(void){ return foo(); }", "SAFE302", False),
    ("ignored fclose fires SAFE802", "void f(void *fp){ fclose(fp); }", "SAFE802", True),
    ("(void) cast discard clean SAFE802", "void f(void *fp){ (void)fclose(fp); }", "SAFE802", False),
    ("token paste fires SAFE311", "#define CAT(a, b) a##b\n", "SAFE311", True),
    ("bracket in string literal clean SAFE311", '#define OPEN "["\n', "SAFE311", False),
    ("misordered brackets fire SAFE311", "#define BAD )(\n", "SAFE311", True),
    ("#ifdef fires SAFE312", "#ifdef DEBUG\nint d;\n#endif\n", "SAFE312", True),
    ("include guard exempt SAFE312", "#ifndef H_H\n#define H_H\nint x;\n#endif\n", "SAFE312", False),
    ("double pointer fires SAFE313", "void f(int **pp){ }", "SAFE313", True),
    ("single pointer clean SAFE313", "void f(int *p){ }", "SAFE313", False),
    ("argv->system taint fires SAFE801", "void f(char **argv){ system(argv[1]); }", "SAFE801", True),
    ("literal argument clean SAFE801", 'void f(void){ system("ls"); }', "SAFE801", False),
    ("printf in pure-named fn fires SAFE303", 'int compute_total(int x){ printf("%d", x); return x; }', "SAFE303", True),
    ("dlopen fires SAFE309", 'void load(void){ void *h = dlopen("lib.so", 1); }', "SAFE309", True),
    ("bare NOLINT fires SAFE603", "int f(void){ return bad(); } // NOLINT\n", "SAFE603", True),
    ("scoped NOLINT clean SAFE603", "int f(void){ return bad(); } // NOLINT(bugprone-foo)\n", "SAFE603", False),
]


@pytest.mark.parametrize(["label", "src", "code", "fires"], _CASES, ids=[c[0] for c in _CASES])
def test_c_power_of_ten_pin(label: str, src: str, code: str, fires: bool, tmp_path: Path) -> None:  # noqa: FBT001 - `fires` is parametrized test data, not a flag argument
    """Each audited C behaviour holds exactly as shipped in v2.7.0."""
    sample = tmp_path / "pin.c"
    sample.write_text(src, encoding="utf-8")
    engine = SafetyEngine(deep_merge(DEFAULTS, _OPT_IN))
    codes = {v.code for v in engine.check_file(str(sample)).violations}
    assert (code in codes) is fires
