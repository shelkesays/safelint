from __future__ import annotations

from pathlib import Path

from safelint.core.config import SafeLintConfig


def test_config_loads_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / ".ai-safety.yaml"
    config_path.write_text(
        """
max_function_lines: 12
max_nesting_depth: 2
allow_top_level_side_effects: true
enabled_rules:
  - side-effects
""".strip(),
        encoding="utf-8",
    )

    config = SafeLintConfig.from_file(config_path)

    assert config.max_function_lines == 12
    assert config.max_nesting_depth == 2
    assert config.allow_top_level_side_effects is True
    assert config.enabled_rules == ["side-effects"]