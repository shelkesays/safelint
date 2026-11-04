"""SAFE801 scopes a binding's taint to the block that declares it (#250).

Every tracker kept one flat ``name -> status`` map per function, so a nested
block that rebound a name overwrote the function-wide entry and the outer
binding came back without its taint. The issue reported the false negative; a
probe showed the flat map was wrong in **both** directions, and in three more
languages than the two it named:

====================  ==================  ==================
language              shadow clears taint  shadow adds taint
====================  ==================  ==================
Rust                  false negative       false positive
JavaScript / TS       false negative       false positive
C / C++               false negative       false positive
Go                    false negative       false positive
====================  ==================  ==================

The false negative is the worse direction for a security rule, so it is what
the issue is about; the false positive wastes a reader's time on a finding about
a binding that is clean. One mechanism fixes both, because both come from the
same missing idea: a block-scoped declaration's effect on the map has to end
where the block does.

Two languages deliberately get nothing. Python has no block scope, and PHP's
locals are function-scoped, so an inner ``{ $c = "safe"; }`` genuinely
overwrites the outer ``$c`` and the flat map is already right there. Java is
also untouched: shadowing a local in a nested block is a compile error.

JavaScript ``var`` is the one form that must NOT be scoped. It is
function-scoped and hoisted, so an inner-block ``var`` really does rebind the
function-wide name - scoping it would turn a true positive into a false
negative, which is the hazard SAFE305 exists to explain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

import pytest

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine
from safelint.languages import get_language_for_file
from safelint.languages._node_utils import walk


def _safe801(sample: Path) -> list[str]:
    """Return every SAFE801 message for *sample* with the rule enabled."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE801"]


# Each case is (label, filename, source). The outer binding is TAINTED and an
# inner block shadows it with a clean value; the sink after the block reads the
# outer binding, so it must report.
_SHADOW_CLEARS_TAINT: list[tuple[str, str, str]] = [
    (
        "rust let in a nested block",
        "a.rs",
        "fn main() {\n"
        '    let input = std::env::var("CMD").unwrap();\n'
        "    {\n"
        '        let input = "safe";\n'
        '        println!("{}", input);\n'
        "    }\n"
        '    let mut cmd = std::process::Command::new("sh");\n'
        "    cmd.arg(input);\n"
        "}\n",
    ),
    (
        "rust same-scope shadowing inside a block",
        "b.rs",
        "fn main() {\n"
        '    let input = std::env::var("CMD").unwrap();\n'
        "    {\n"
        '        let input = "safe";\n'
        "        let input = input;\n"
        '        println!("{}", input);\n'
        "    }\n"
        '    let mut cmd = std::process::Command::new("sh");\n'
        "    cmd.arg(input);\n"
        "}\n",
    ),
    (
        "javascript let in a nested block",
        "a.js",
        'function f() {\n  let code = prompt("code?");\n  { let code = "safe"; console.log(code); }\n  eval(code);\n}\n',
    ),
    (
        "javascript const in a nested block",
        "b.js",
        'function f() {\n  let code = prompt("code?");\n  { const code = "safe"; console.log(code); }\n  eval(code);\n}\n',
    ),
    (
        "typescript let in a nested block",
        "a.ts",
        'function f(): void {\n  let code = prompt("code?");\n  { let code: string = "safe"; console.log(code); }\n  eval(code);\n}\n',
    ),
    (
        "c declaration in a nested block",
        "a.c",
        '#include <stdlib.h>\nvoid f(void) {\n  char *p = getenv("CMD");\n  { char *p = "safe"; puts(p); }\n  system(p);\n}\n',
    ),
    (
        "cpp declaration in a nested block",
        "a.cpp",
        '#include <cstdlib>\nvoid f() {\n  char *p = getenv("CMD");\n  { char *p = "safe"; puts(p); }\n  system(p);\n}\n',
    ),
    (
        "go short var declaration in a nested block",
        "a.go",
        'package main\nimport ("os"; "os/exec")\nfunc main() {\n  cmd := os.Getenv("CMD")\n  {\n    cmd := "safe"\n    _ = cmd\n  }\n  exec.Command(cmd)\n}\n',
    ),
    (
        "go var declaration in a nested block",
        "b.go",
        'package main\nimport ("os"; "os/exec")\nfunc main() {\n  cmd := os.Getenv("CMD")\n  {\n    var cmd = "safe"\n    _ = cmd\n  }\n  exec.Command(cmd)\n}\n',
    ),
]


@pytest.mark.parametrize(["label", "filename", "source"], _SHADOW_CLEARS_TAINT, ids=[case[0] for case in _SHADOW_CLEARS_TAINT])
def test_a_shadow_no_longer_clears_the_outer_bindings_taint(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """The reported false negative. The sink reads the tainted outer binding."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert len(_safe801(sample)) == 1, label


# The mirror image: the OUTER binding is clean and the inner block's shadow is
# tainted. The sink after the block reads the clean outer binding, so reporting
# it is a false positive.
_SHADOW_ADDS_TAINT: list[tuple[str, str, str]] = [
    (
        "rust",
        "c.rs",
        "fn main() {\n"
        '    let input = "safe";\n'
        "    {\n"
        '        let input = std::env::var("CMD").unwrap();\n'
        '        println!("{}", input);\n'
        "    }\n"
        '    let mut cmd = std::process::Command::new("sh");\n'
        "    cmd.arg(input);\n"
        "}\n",
    ),
    (
        "javascript",
        "c.js",
        'function f() {\n  let code = "safe";\n  { let code = prompt("code?"); console.log(code); }\n  eval(code);\n}\n',
    ),
    (
        "c",
        "c.c",
        '#include <stdlib.h>\nvoid f(void) {\n  char *p = "safe";\n  { char *p = getenv("CMD"); puts(p); }\n  system(p);\n}\n',
    ),
    (
        "go",
        "c.go",
        'package main\nimport ("os"; "os/exec")\nfunc main() {\n  cmd := "safe"\n  {\n    cmd := os.Getenv("CMD")\n    _ = cmd\n  }\n  exec.Command(cmd)\n}\n',
    ),
]


@pytest.mark.parametrize(["label", "filename", "source"], _SHADOW_ADDS_TAINT, ids=[case[0] for case in _SHADOW_ADDS_TAINT])
def test_a_shadow_no_longer_taints_the_outer_binding(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """The other direction, which #250 did not report and the same fix closes."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert _safe801(sample) == [], label


_STILL_REPORTED: list[tuple[str, str, str]] = [
    (
        "rust, no intervening block",
        "d.rs",
        'fn main() {\n    let input = std::env::var("CMD").unwrap();\n    let mut cmd = std::process::Command::new("sh");\n    cmd.arg(input);\n}\n',
    ),
    (
        "javascript, no intervening block",
        "d.js",
        'function f() {\n  let code = prompt("code?");\n  eval(code);\n}\n',
    ),
    (
        "javascript, the shadow is also tainted",
        "e.js",
        'function f() {\n  let code = prompt("code?");\n  { let code = prompt("again?"); console.log(code); }\n  eval(code);\n}\n',
    ),
    (
        "javascript, the sink is inside the block",
        "f.js",
        'function f() {\n  let code = prompt("code?");\n  { console.log(code); eval(code); }\n}\n',
    ),
    (
        "c, no intervening block",
        "d.c",
        '#include <stdlib.h>\nvoid f(void) {\n  char *p = getenv("CMD");\n  system(p);\n}\n',
    ),
    (
        "go, no intervening block",
        "d.go",
        'package main\nimport ("os"; "os/exec")\nfunc main() {\n  cmd := os.Getenv("CMD")\n  exec.Command(cmd)\n}\n',
    ),
]


@pytest.mark.parametrize(["label", "filename", "source"], _STILL_REPORTED, ids=[case[0] for case in _STILL_REPORTED])
def test_the_shapes_that_already_reported_are_unchanged(tmp_path: Path, label: str, filename: str, source: str) -> None:
    """The controls. A scoping change must not cost the findings the rule already had."""
    sample = tmp_path / filename
    sample.write_text(source, encoding="utf-8")
    assert len(_safe801(sample)) >= 1, label


def test_javascript_var_is_not_block_scoped(tmp_path: Path) -> None:
    """``var`` must stay function-scoped, or the fix becomes a false negative.

    An inner-block ``var`` really does rebind the function-wide name - that is
    the hoisting SAFE305 reports - so the flat map is already correct for it and
    the taint the inner one records has to survive the block.
    """
    sample = tmp_path / "v.js"
    sample.write_text(
        'function f() {\n  var code = "safe";\n  { var code = prompt("code?"); console.log(code); }\n  eval(code);\n}\n',
        encoding="utf-8",
    )
    assert len(_safe801(sample)) == 1


def test_a_plain_assignment_inside_a_block_is_not_scoped(tmp_path: Path) -> None:
    """Assigning through to an outer binding is not a new binding, so it must persist.

    ``{ code = prompt(...) }`` writes to the ``code`` already in scope. Undoing
    it at the end of the block would discard a genuine taint flow, which is the
    false negative the fix exists to remove - so only DECLARING forms are
    scoped.
    """
    sample = tmp_path / "w.js"
    sample.write_text(
        'function f() {\n  let code = "safe";\n  { code = prompt("code?"); }\n  eval(code);\n}\n',
        encoding="utf-8",
    )
    assert len(_safe801(sample)) == 1


def test_an_uninitialised_c_declaration_shadows_for_its_block(tmp_path: Path) -> None:
    """``char *p;`` with no initialiser is still a distinct, clean binding.

    Without scoping the declaration itself, a read of the inner ``p`` resolved
    to the outer tainted entry, so the rule reported a finding about the wrong
    variable. The C handler therefore clears on the declaration and takes the
    value's taint on the initialiser, in that order, which the pre-order walk
    guarantees.
    """
    inner = tmp_path / "u.c"
    inner.write_text(
        '#include <stdlib.h>\nvoid f(void) {\n  char *p = getenv("CMD");\n  { char *p; system(p); }\n}\n',
        encoding="utf-8",
    )
    assert _safe801(inner) == []
    # ...and the outer binding is still answerable after the block.
    outer = tmp_path / "u2.c"
    outer.write_text(
        '#include <stdlib.h>\nvoid f(void) {\n  char *p = getenv("CMD");\n  { char *p; puts(p); }\n  system(p);\n}\n',
        encoding="utf-8",
    )
    assert len(_safe801(outer)) == 1


def test_php_locals_are_function_scoped_so_nothing_changes(tmp_path: Path) -> None:
    """PHP has no block scope, so an inner assignment genuinely overwrites.

    Pinned because it is the one language where the flat map is the CORRECT
    model, and a well-meaning extension of this fix to PHP would introduce a
    false negative rather than remove one.
    """
    sample = tmp_path / "a.php"
    sample.write_text(
        '<?php\nfunction f() {\n  $c = $_GET["c"];\n  if (true) { $c = "safe"; }\n  system($c);\n}\n',
        encoding="utf-8",
    )
    assert _safe801(sample) == []


def test_nested_blocks_restore_innermost_first(tmp_path: Path) -> None:
    """Three levels, so the restore order is actually exercised.

    The pending shadows are a chain of nested spans whose ends decrease towards
    the top of the stack, which is what lets the tracker pop while the top has
    expired. A single level would pass with any order.
    """
    sample = tmp_path / "n.js"
    sample.write_text(
        "function f() {\n"
        '  let code = prompt("code?");\n'
        "  {\n"
        '    let code = "safe";\n'
        "    {\n"
        '      let code = "safer";\n'
        "      console.log(code);\n"
        "    }\n"
        "    console.log(code);\n"
        "  }\n"
        "  eval(code);\n"
        "}\n",
        encoding="utf-8",
    )
    assert len(_safe801(sample)) == 1


def test_sibling_blocks_do_not_leak_into_each_other(tmp_path: Path) -> None:
    """A shadow in one block must not still be pending when the next one opens."""
    sample = tmp_path / "s.js"
    sample.write_text(
        'function f() {\n  let code = prompt("code?");\n  { let code = "safe"; console.log(code); }\n  { let other = "safe"; console.log(other); }\n  eval(code);\n}\n',
        encoding="utf-8",
    )
    assert len(_safe801(sample)) == 1


@pytest.mark.parametrize(
    ["filename", "source"],
    (
        ["w.js", "function f(){ let a=1; { let b=2; g(b); } h(a); }\n"],
        ["w.rs", "fn f() { let a = 1; { let b = 2; g(b); } h(a); }\n"],
        ["w.c", "void f(void) { int a = 1; { int b = 2; g(b); } h(a); }\n"],
        ["w.go", "package main\nfunc f() {\n  a := 1\n  {\n    b := 2\n    g(b)\n  }\n  h(a)\n}\n"],
    ),
    ids=["javascript", "rust", "c", "go"],
)
def test_walk_yields_nodes_in_non_decreasing_start_byte_order(filename: str, source: str) -> None:
    """The invariant the whole design rests on, asserted rather than assumed.

    ``BlockScopes`` restores a shadowed binding on the first node at or past the
    block's end, which is only sound because ``walk`` is a pre-order traversal
    and so never goes backwards through the source. If that ever changed, every
    scoped tracker would silently restore at the wrong point, and the symptom
    would be a missing security finding rather than a crash.
    """
    definition = get_language_for_file(filename)
    assert definition is not None
    tree = definition.create_parser().parse(source.encode())
    starts = [node.start_byte for node in walk(tree.root_node)]
    assert starts == sorted(starts)
