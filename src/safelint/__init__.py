"""safelint — safety-oriented lint rules and pre-commit integration for Python."""

from safelint.core.config import SafeLintConfig
from safelint.core.engine import SafeLintEngine

__all__ = ["SafeLintConfig", "SafeLintEngine"]

__version__ = "0.1.0"
