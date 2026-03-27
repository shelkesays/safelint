"""Convenience runner that wires together config loading and engine execution."""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import SafeLintConfig
from safelint.core.engine import LintResult, SafeLintEngine


def run(target: str | Path, config_path: str | Path | None = None) -> list[LintResult]:
    """Load config from *config_path* (or defaults) and lint *target*."""
    config = SafeLintConfig.from_file(config_path) if config_path else SafeLintConfig()
    engine = SafeLintEngine(config=config)
    return engine.lint_path(target)
