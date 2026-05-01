"""Output formatters for safelint.

The default ``pretty`` format (ruff/ty-style multi-line coloured output) lives
in :mod:`safelint.cli` and is unchanged. This package provides additional
machine-readable formats used by editor integrations, CI systems, and the
upcoming Claude Code skill / VSCode plugin:

* :func:`format_json` — compact JSON with violations, suppressed entries,
  and a top-level summary.
* :func:`format_sarif` — SARIF 2.1.0 conformant document for tools that
  speak the OASIS standard (GitHub code scanning, Azure DevOps, etc.).

Both formats are pure functions — they take the lint results and return a
string. The CLI picks one via ``--format`` and prints the result to stdout.
"""

from __future__ import annotations

from safelint.formatters._json import format_json
from safelint.formatters._sarif import format_sarif


__all__ = ["format_json", "format_sarif"]
