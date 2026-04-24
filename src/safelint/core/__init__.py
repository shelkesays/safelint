"""Core safelint package: config, engine, and runner."""

from safelint.core.config import DEFAULTS, SEVERITY_ORDER, load_config
from safelint.core.engine import LintResult, SafetyEngine
from safelint.core.runner import run


__all__ = ["DEFAULTS", "SEVERITY_ORDER", "LintResult", "SafetyEngine", "load_config", "run"]
