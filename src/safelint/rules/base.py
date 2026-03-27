"""Base types shared by all safelint rules."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Violation:
    """A single rule violation produced during static analysis."""

    rule: str
    code: str
    filepath: str
    lineno: int
    message: str
    severity: str  # "error" | "warning"


class BaseRule(ABC):
    """Pluggable safety rule that analyses a parsed AST and returns violations.

    Subclasses declare a ``name`` class variable matching the key used in the
    config file and a ``code`` class variable (e.g. ``SAFE101``) for display
    and inline suppression, then implement ``check_file``.
    """

    name: str = ""
    code: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        """Bind rule-specific config and resolve severity."""
        self.config = config
        self.severity: str = config.get("severity", "error")

    @abstractmethod
    def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:
        """Analyse *tree* (parsed from *filepath*) and return every violation found."""

    def _v(self, filepath: str, lineno: int, message: str) -> Violation:
        """Shorthand for constructing a Violation tagged with this rule."""
        return Violation(
            rule=self.name,
            code=self.code,
            filepath=filepath,
            lineno=lineno,
            message=message,
            severity=self.severity,
        )

    @staticmethod
    def _call_name(func: ast.expr) -> str | None:
        """Return the bare name of a Call's function node, or None if not resolvable."""
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None
