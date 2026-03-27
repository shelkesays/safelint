from __future__ import annotations

from pathlib import Path

from safelint.core.config import SafeLintConfig
from safelint.core.engine import SafeLintEngine


def test_engine_reports_multiple_rule_types(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        """
def risky(value):
    try:
        if value:
            for item in value:
                while item:
                    if item > 3:
                        return item
    except:
        pass

file_handle = open('data.txt')
print('boom')
""".strip(),
        encoding="utf-8",
    )

    config = SafeLintConfig(max_nesting_depth=3, max_function_lines=6)
    engine = SafeLintEngine(config=config)
    result = engine.lint_file(sample)

    codes = {violation.code for violation in result.violations}
    assert {"SAFE101", "SAFE102", "SAFE201", "SAFE301", "SAFE401"}.issubset(codes)


def test_engine_honors_configured_rule_subset(tmp_path: Path) -> None:
    sample = tmp_path / "side_effects.py"
    sample.write_text("print('hello')\n", encoding="utf-8")

    config = SafeLintConfig(enabled_rules=["side-effects"])
    engine = SafeLintEngine(config=config)
    result = engine.lint_file(sample)

    assert [violation.code for violation in result.violations] == ["SAFE301"]


def test_main_guard_is_not_reported_as_side_effect(tmp_path: Path) -> None:
    sample = tmp_path / "cli_like.py"
    sample.write_text(
        """
def main():
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""".strip(),
        encoding="utf-8",
    )

    config = SafeLintConfig(enabled_rules=["side-effects"])
    engine = SafeLintEngine(config=config)
    result = engine.lint_file(sample)

    assert result.violations == []