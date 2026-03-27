"""Convenience runner that wires together config loading and engine execution."""

from __future__ import annotations

from pathlib import Path

from safelint.core.config import load_config
from safelint.core.engine import LintResult, SafetyEngine


def run(
    target: str | Path,
    config_path: str | Path | None = None,
    changed_files: list[str] | None = None,
) -> list[LintResult]:
    """Load config and lint *target* (file or directory).

    Parameters
    ----------
    target:
        A single ``.py`` file or a directory to scan recursively.
    config_path:
        Explicit path to a ``.ai-safety.yaml`` file. When omitted, the
        loader walks up from *target* to find one automatically.
    changed_files:
        List of files being checked (injected into test-coupling rules).
        Defaults to the files discovered from *target*.
    """
    search_from = Path(config_path).parent if config_path else Path(target)
    config = load_config(search_from if search_from.is_dir() else search_from.parent)
    engine = SafetyEngine(config, changed_files=changed_files)
    return engine.check_path(target)
