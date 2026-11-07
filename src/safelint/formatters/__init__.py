"""Output formatters for safelint.

The default ``pretty`` format (ruff/ty-style multi-line coloured output) lives
in :mod:`safelint.cli` and is unchanged. This package provides additional
machine-readable formats used by editor integrations, CI systems, and the
upcoming Claude Code skill / VSCode plugin:

* :func:`format_json` - compact JSON with violations, suppressed entries,
  and a top-level summary.
* :func:`format_sarif` - SARIF 2.1.0 conformant document for tools that
  speak the OASIS standard (GitHub code scanning, Azure DevOps, etc.).
* :class:`RunCoverage` - the optional ``coverage=`` argument both formatters
  accept, carrying the skipped-file count and the per-language breakdown.
  JSON emits both; SARIF ignores them by decision (it has no natural home for
  run-level counts, and the parse failures are present as ``SAFE000`` results
  regardless).

Both formats are pure functions - they take the lint results and return a
string. The CLI picks one via ``--format`` and prints the result to stdout.
"""

from __future__ import annotations

from safelint.formatters._counts import RunCoverage
from safelint.formatters._json import format_json
from safelint.formatters._sarif import format_sarif


__all__ = ["RunCoverage", "format_json", "format_sarif"]
