"""Convenience runner that wires together config loading and engine execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from safelint.core.config import load_config
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from safelint.core.engine import LintResult


def run(
    target: str | Path,
    config_path: str | Path | None = None,
    changed_files: list[str] | None = None,
    files: list[str] | None = None,
    ignore: list[str] | None = None,
) -> list[LintResult]:
    """Load config and lint *target* (file or directory).

    Parameters
    ----------
    target:
        A single ``.py`` file or a directory to scan recursively.
    config_path:
        Optional path that overrides the directory used for config discovery.
        If it is a directory, it is used directly as the search root. If it is
        a file path, its parent directory is used. When omitted, the loader
        walks up from *target* to find a supported config file automatically.
    changed_files:
        Optional list of files being checked (injected into test-coupling rules).
        When omitted, the value of *files* (if provided) is reused; otherwise
        left unset and the engine receives no changed-files context.
    files:
        Explicit list of ``.py`` files to lint. When provided, skips directory
        discovery and checks exactly these files. Also used as *changed_files*
        for test-coupling rules when *changed_files* is not set separately.
    ignore:
        Extra rule codes or names to suppress on top of whatever is listed in
        the config file's ``ignore`` key.

    """
    if config_path:
        config_p = Path(config_path)
        search_from = config_p if config_p.is_dir() else config_p.parent
    else:
        search_from = Path(target)
    config = load_config(search_from if search_from.is_dir() else search_from.parent)
    if ignore:
        config["ignore"] = list(set(config.get("ignore", [])) | set(ignore))
    engine = SafetyEngine(
        config,
        changed_files=changed_files if changed_files is not None else files,
    )
    if files is not None:
        return [engine.check_file(f) for f in files]
    return engine.check_path(target)
