"""Configuration dataclass and loaders for safelint."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES = [
    "function-length",
    "nesting-depth",
    "error-handling",
    "side-effects",
    "resource-lifecycle",
]


@dataclass(slots=True)
class SafeLintConfig:
    """Holds all tunable settings that control safelint rule behaviour."""

    max_function_lines: int = 40
    max_nesting_depth: int = 3
    allow_top_level_side_effects: bool = False
    enabled_rules: list[str] = field(default_factory=lambda: list(DEFAULT_RULES))
    include: list[str] = field(default_factory=lambda: ["**/*.py"])
    exclude: list[str] = field(default_factory=lambda: ["**/tests/**", "**/.venv/**"])

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> SafeLintConfig:
        """Construct a :class:`SafeLintConfig` from a plain dictionary."""
        enabled_rules = payload.get("enabled_rules", DEFAULT_RULES)
        include = payload.get("include", ["**/*.py"])
        exclude = payload.get("exclude", ["**/tests/**", "**/.venv/**"])
        return cls(
            max_function_lines=int(payload.get("max_function_lines", 40)),
            max_nesting_depth=int(payload.get("max_nesting_depth", 3)),
            allow_top_level_side_effects=bool(payload.get("allow_top_level_side_effects", False)),
            enabled_rules=[str(name) for name in enabled_rules],
            include=[str(pattern) for pattern in include],
            exclude=[str(pattern) for pattern in exclude],
        )

    @classmethod
    def from_file(cls, path: str | Path) -> SafeLintConfig:
        """Load config from a YAML or JSON file at *path*."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        suffix = config_path.suffix.lower()
        raw_text = config_path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(raw_text) or {}
        elif suffix == ".json":
            payload = json.loads(raw_text)
        else:
            raise ValueError(f"Unsupported config format: {config_path.suffix}")

        if not isinstance(payload, dict):
            raise ValueError("Configuration payload must be a mapping")
        return cls.from_mapping(payload)
