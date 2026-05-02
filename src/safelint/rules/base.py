"""Base types shared by all safelint rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from safelint.languages._node_utils import call_name


if TYPE_CHECKING:
    import tree_sitter


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
    """Pluggable safety rule that analyses a parsed Tree-sitter tree and returns violations."""

    name: str = ""
    code: str = ""

    def __init__(self, config: dict[str, Any]) -> None:
        """Bind rule-specific config and resolve severity."""
        self.config = config
        self.severity: str = config.get("severity", "error")

    @abstractmethod
    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Analyse *tree* (parsed from *filepath*) and return every violation found."""

    def _make_violation(self, filepath: str, lineno: int, message: str) -> Violation:
        """Construct a Violation tagged with this rule's name, code, and severity."""
        return Violation(
            rule=self.name,
            code=self.code,
            filepath=filepath,
            lineno=lineno,
            message=message,
            severity=self.severity,
        )

    @staticmethod
    def _call_name(call_node: tree_sitter.Node) -> str | None:  # pragma: no cover
        """Return the bare callable name from a ``call`` node, or None if unresolvable.

        Pass the call node itself (not the function sub-node).
        Handles ``foo(...)`` → ``"foo"`` and ``obj.method(...)`` → ``"method"``.

        Legacy alias retained for backward-compat with rules that called
        ``self._call_name(...)`` directly. New code uses the module-level
        ``call_name`` from ``safelint.languages._node_utils``.
        """
        return call_name(call_node)
