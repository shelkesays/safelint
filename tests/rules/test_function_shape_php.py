"""Tests for the function-shape rules (SAFE101-105) on PHP files.

PHP-specific behaviour exercised here:

* ``function_definition`` / ``method_declaration`` / ``anonymous_function`` /
  ``arrow_function`` are the PHP function shapes; anonymous and arrow
  functions render as ``<anonymous>``.
* A bodyless interface method has no body, so SAFE101 must not fire on it.
* SAFE103 counts variadic (``...$rest``) and promoted constructor params
  (``private int $x``) as ordinary parameters.
* SAFE105 recognises ``$this->m()`` / ``self::m()`` / ``static::m()``
  self-recursion in addition to a bare same-named call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


# ---------------------------------------------------------------------------
# function_length (SAFE101)
# ---------------------------------------------------------------------------


def test_php_long_function_fires_safe101(tmp_path: Path) -> None:
    """A function body over the default 60-line cap fires SAFE101."""
    sample = tmp_path / "long.php"
    body = "\n".join(f"    $x = {i};" for i in range(70))
    sample.write_text(f"<?php\nfunction f() {{\n{body}\n}}\n", encoding="utf-8")
    safe101 = [v for v in _engine({"rules": {"function_length": {"enabled": True}}}).check_file(str(sample)).violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "f" in safe101[0].message


def test_php_short_function_is_clean(tmp_path: Path) -> None:
    """A short function does not fire SAFE101."""
    sample = tmp_path / "short.php"
    sample.write_text("<?php\nfunction small() {\n    return 1;\n}\n", encoding="utf-8")
    violations = _engine({"rules": {"function_length": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE101" for v in violations)


def test_php_bodyless_interface_method_does_not_fire_safe101(tmp_path: Path) -> None:
    """An abstract interface method has no body, so SAFE101 has nothing to measure."""
    sample = tmp_path / "iface.php"
    sample.write_text("<?php\ninterface I {\n    public function big(): void;\n}\n", encoding="utf-8")
    violations = _engine({"rules": {"function_length": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE101" for v in violations)


# ---------------------------------------------------------------------------
# nesting_depth (SAFE102), default max_depth=2
# ---------------------------------------------------------------------------


def test_php_deep_nesting_fires_safe102(tmp_path: Path) -> None:
    """Control flow nested beyond max_depth=2 fires SAFE102."""
    sample = tmp_path / "deep.php"
    sample.write_text(
        "<?php\nfunction h() {\n    if ($a) {\n        while ($b) {\n            foreach ($c as $x) {\n                echo $x;\n            }\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"nesting_depth": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE102" for v in violations)


def test_php_shallow_nesting_is_clean(tmp_path: Path) -> None:
    """Nesting within the cap is clean."""
    sample = tmp_path / "shallow.php"
    sample.write_text("<?php\nfunction f() {\n    if ($a) {\n        g();\n    }\n}\n", encoding="utf-8")
    violations = _engine({"rules": {"nesting_depth": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE102" for v in violations)


def test_php_match_counts_as_one_nesting_step(tmp_path: Path) -> None:
    """``match`` counts as a single nesting step, like ``switch``."""
    sample = tmp_path / "match.php"
    sample.write_text(
        "<?php\nfunction h() {\n    if ($a) {\n        while ($b) {\n            $r = match ($c) {\n                1 => 'a',\n                default => 'b',\n            };\n        }\n    }\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"nesting_depth": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE102" for v in violations)


# ---------------------------------------------------------------------------
# max_arguments (SAFE103), default max_args=7
# ---------------------------------------------------------------------------


def test_php_too_many_arguments_fires_safe103(tmp_path: Path) -> None:
    """Eight parameters over the default 7 fires SAFE103."""
    sample = tmp_path / "args.php"
    sample.write_text("<?php\nfunction many($a, $b, $c, $d, $e, $f, $g, $h) {}\n", encoding="utf-8")
    safe103 = [v for v in _engine({"rules": {"max_arguments": {"enabled": True}}}).check_file(str(sample)).violations if v.code == "SAFE103"]
    assert len(safe103) == 1
    assert "8 arguments" in safe103[0].message


def test_php_variadic_parameter_counts_toward_safe103(tmp_path: Path) -> None:
    """A ``...$rest`` variadic parameter counts as one ordinary parameter."""
    sample = tmp_path / "variadic.php"
    sample.write_text("<?php\nfunction many($a, $b, $c, $d, $e, $f, $g, ...$rest) {}\n", encoding="utf-8")
    violations = _engine({"rules": {"max_arguments": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE103" for v in violations)


def test_php_promoted_constructor_params_count_toward_safe103(tmp_path: Path) -> None:
    """Promoted constructor properties (``private int $x``) count as parameters."""
    sample = tmp_path / "promoted.php"
    sample.write_text(
        "<?php\nclass C {\n    public function __construct(private int $a, $b, $c, $d, $e, $f, $g, $h) {}\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"max_arguments": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE103" for v in violations)


def test_php_few_arguments_is_clean(tmp_path: Path) -> None:
    """A function under the argument cap does not fire SAFE103."""
    sample = tmp_path / "few.php"
    sample.write_text("<?php\nfunction ok($a, $b, $c) {}\n", encoding="utf-8")
    violations = _engine({"rules": {"max_arguments": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE103" for v in violations)


# ---------------------------------------------------------------------------
# complexity (SAFE104), default max_complexity=10
# ---------------------------------------------------------------------------


def test_php_high_complexity_fires_safe104(tmp_path: Path) -> None:
    """Many branch points push cyclomatic complexity over the cap."""
    sample = tmp_path / "cx.php"
    sample.write_text(
        "<?php\nfunction cx($x) {\n"
        "    if ($x == 1) { return 1; }\n"
        "    elseif ($x == 2) { return 2; }\n"
        "    foreach ($x as $y) { echo $y; }\n"
        "    $z = $x ? 1 : 2;\n"
        "    switch ($x) {\n        case 3: break;\n        case 4: break;\n    }\n"
        "    $m = match ($x) {\n        5 => 'a',\n        6 => 'b',\n        default => 'c',\n    };\n"
        "    if ($x && $z || $m ?? false) { return 9; }\n"
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"complexity": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE104" for v in violations)


def test_php_simple_function_complexity_is_clean(tmp_path: Path) -> None:
    """A linear function is under the complexity cap."""
    sample = tmp_path / "lin.php"
    sample.write_text("<?php\nfunction lin() {\n    return 1;\n}\n", encoding="utf-8")
    violations = _engine({"rules": {"complexity": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE104" for v in violations)


def test_php_anonymous_function_does_not_crash_and_renders_anonymous(tmp_path: Path) -> None:
    """An ``anonymous_function`` is handled gracefully and named ``<anonymous>`` if flagged."""
    sample = tmp_path / "anon.php"
    body = "\n".join(f"    $x = {i};" for i in range(70))
    sample.write_text(f"<?php\n$f = function($a) {{\n{body}\n}};\n", encoding="utf-8")
    safe101 = [v for v in _engine({"rules": {"function_length": {"enabled": True}}}).check_file(str(sample)).violations if v.code == "SAFE101"]
    assert len(safe101) == 1
    assert "<anonymous>" in safe101[0].message


def test_php_arrow_function_does_not_crash(tmp_path: Path) -> None:
    """An ``arrow_function`` (``fn($x) => $x``) parses and produces no false positive."""
    sample = tmp_path / "arrow.php"
    sample.write_text("<?php\n$f = fn($x) => $x;\n", encoding="utf-8")
    overrides = {
        "rules": {
            "function_length": {"enabled": True},
            "complexity": {"enabled": True},
            "max_arguments": {"enabled": True},
            "nesting_depth": {"enabled": True},
        }
    }
    # Should not raise and should not flag a trivial arrow function.
    violations = _engine(overrides).check_file(str(sample)).violations
    assert not any(v.code in {"SAFE101", "SAFE102", "SAFE103", "SAFE104"} for v in violations)


# ---------------------------------------------------------------------------
# no_recursion (SAFE105)
# ---------------------------------------------------------------------------


def test_php_plain_recursion_fires_safe105(tmp_path: Path) -> None:
    """A free function calling itself by name fires SAFE105."""
    sample = tmp_path / "rec.php"
    sample.write_text("<?php\nfunction foo() {\n    return foo();\n}\n", encoding="utf-8")
    safe105 = [v for v in _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations if v.code == "SAFE105"]
    assert len(safe105) == 1
    assert "foo" in safe105[0].message


def test_php_this_method_recursion_fires_safe105(tmp_path: Path) -> None:
    """``$this->walk()`` inside method ``walk`` is self-recursion."""
    sample = tmp_path / "this.php"
    sample.write_text(
        "<?php\nclass C {\n    function walk() {\n        return $this->walk();\n    }\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations
    assert any(v.code == "SAFE105" for v in violations)


def test_php_self_static_method_recursion_fires_safe105(tmp_path: Path) -> None:
    """``self::w()`` and ``static::w()`` inside a static method ``w`` are self-recursion."""
    for qualifier in ("self", "static"):
        sample = tmp_path / f"{qualifier}.php"
        sample.write_text(
            f"<?php\nclass C {{\n    static function w() {{\n        return {qualifier}::w();\n    }}\n}}\n",
            encoding="utf-8",
        )
        violations = _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations
        assert any(v.code == "SAFE105" for v in violations), f"{qualifier}::w() should fire SAFE105"


def test_php_other_object_call_is_not_recursion(tmp_path: Path) -> None:
    """``$other->walk()`` (different receiver) inside ``walk`` is not self-recursion."""
    sample = tmp_path / "other_obj.php"
    sample.write_text(
        "<?php\nclass C {\n    function walk() {\n        return $other->walk();\n    }\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE105" for v in violations)


def test_php_other_class_static_call_is_not_recursion(tmp_path: Path) -> None:
    """``Other::w()`` (different class) inside ``w`` is not self-recursion."""
    sample = tmp_path / "other_static.php"
    sample.write_text(
        "<?php\nclass C {\n    static function w() {\n        return Other::w();\n    }\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE105" for v in violations)


def test_php_mutual_recursion_is_clean(tmp_path: Path) -> None:
    """Mutual recursion (``a`` calls ``b``) is not direct self-recursion."""
    sample = tmp_path / "mutual.php"
    sample.write_text(
        "<?php\nfunction a() {\n    return b();\n}\nfunction b() {\n    return a();\n}\n",
        encoding="utf-8",
    )
    violations = _engine({"rules": {"no_recursion": {"enabled": True}}}).check_file(str(sample)).violations
    assert not any(v.code == "SAFE105" for v in violations)
