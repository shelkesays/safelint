"""Diagnostic output helpers - short messages to stderr.

Used for things the user needs to see but that aren't lint violations
(e.g. typos in their ignore list, malformed config files). Output goes
to stderr so it stays out of the violation/summary stream on stdout
and is captured separately by pre-commit, CI, and editor integrations.
"""

from __future__ import annotations

import sys


# Control characters (C0 except tab, DEL, and C1) are visualised before any
# message reaches stderr. A repo-controlled string echoed here - a symlinked
# file's name, a config value copied into a warning - could otherwise carry raw
# ANSI / OSC escapes that clear or redraw the terminal, set its title, or drive
# OSC 52 clipboard writes. Tab (0x09) is preserved. The same table backs the
# CLI pretty renderer via ``visible`` (imported there as ``_visible``), so the
# stdout gutter and the stderr diagnostics share one sanitiser.
_CONTROL_ORDS = (*range(0x09), *range(0x0A, 0x20), 0x7F, *range(0x80, 0xA0))
_CONTROL_TRANSLATION = {c: f"\\x{c:02x}" for c in _CONTROL_ORDS}


def visible(text: str) -> str:
    r"""Replace control characters (except tab) with visible ``\xNN`` escapes."""
    return text.translate(_CONTROL_TRANSLATION)


def print_warning(message: str) -> None:
    """Emit ``safelint: warning: <message>`` to stderr (control chars visualised)."""
    print(f"safelint: warning: {visible(message)}", file=sys.stderr)


def print_error(message: str) -> None:
    """Emit ``safelint: error: <message>`` to stderr (control chars visualised)."""
    print(f"safelint: error: {visible(message)}", file=sys.stderr)
