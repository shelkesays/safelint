"""Core safelint package: config, engine, and runner."""

from safelint.core.config import SafeLintConfig
from safelint.core.engine import LintResult, SafeLintEngine
from safelint.core.runner import run

__all__ = ["LintResult", "SafeLintConfig", "SafeLintEngine", "run"]
