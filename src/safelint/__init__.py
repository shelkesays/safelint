"""safelint — Holzmann-inspired safety lint rules and pre-commit integration for Python."""

from safelint.core.config import DEFAULTS, load_config
from safelint.core.engine import LintResult, SafetyEngine
from safelint.core.runner import run
from safelint.rules.base import BaseRule, Violation

__all__ = [
    "DEFAULTS",
    "LintResult",
    "SafetyEngine",
    "BaseRule",
    "Violation",
    "load_config",
    "run",
]

__version__ = "0.1.0"
