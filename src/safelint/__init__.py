"""safelint - Holzmann-inspired safety lint rules and pre-commit integration for Python."""

from importlib.metadata import PackageNotFoundError, version
import logging

from safelint.core.config import DEFAULTS, load_config
from safelint.core.engine import LintResult, SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import BaseRule, Violation


_log = logging.getLogger(__name__)


__all__ = [
    "DEFAULTS",
    "BaseRule",
    "LintResult",
    "SafetyEngine",
    "Violation",
    "load_config",
    "run",
]

try:
    __version__ = version("safelint")
except PackageNotFoundError:  # pragma: no cover
    _log.debug("safelint package metadata not found; version set to 'unknown'")
    __version__ = "unknown"
