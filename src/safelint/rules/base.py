"""Base types shared by all safelint rules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from safelint.core.config import SafeLintConfig


@dataclass(slots=True, frozen=True)
class Violation:
    """A single policy violation found at a specific source location."""

    code: str
    message: str
    line: int
    column: int = 0


class Rule:
    """Abstract base class for all safelint rules."""

    name = "rule"
    code = "SAFE000"
    description = "Base rule"

    def __init__(self, config: SafeLintConfig) -> None:
        """Store the shared *config* for use in :meth:`check`."""
        self.config = config

    def check(self, path: Path, tree: ast.AST, source: str) -> list[Violation]:
        """Analyse *tree* and return any violations found."""
        raise NotImplementedError

    def violation(self, message: str, line: int, column: int = 0) -> Violation:
        """Construct a :class:`Violation` using this rule's code."""
        return Violation(code=self.code, message=message, line=line, column=column)
