"""safelint - Holzmann-inspired safety lint rules and pre-commit integration for Python."""

from importlib.metadata import PackageNotFoundError, version

from safelint.core.config import DEFAULTS, load_config
from safelint.core.engine import LintResult, SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import BaseRule, Violation


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
# Source checkouts have no install metadata; "unknown" is the documented fallback.
except PackageNotFoundError:  # nosafe: SAFE203
    __version__ = "unknown"
