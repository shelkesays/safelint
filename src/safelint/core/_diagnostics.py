"""Diagnostic output helpers — short messages to stderr.

Used for things the user needs to see but that aren't lint violations
(e.g. typos in their ignore list, malformed config files). Output goes
to stderr so it stays out of the violation/summary stream on stdout
and is captured separately by pre-commit, CI, and editor integrations.
"""

from __future__ import annotations

import sys


def print_warning(message: str) -> None:
    """Emit ``safelint: warning: <message>`` to stderr."""
    print(f"safelint: warning: {message}", file=sys.stderr)


def print_error(message: str) -> None:
    """Emit ``safelint: error: <message>`` to stderr."""
    print(f"safelint: error: {message}", file=sys.stderr)
