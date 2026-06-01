"""Rule catalogue listing for ``safelint list-rules``.

Inventory of every shipped rule with code, name, severity, languages,
default-enabled state, and a one-line description. Consumed by the
``safelint list-rules`` subcommand to produce text / JSON / Markdown /
SARIF representations of the catalogue so AI agents, CI dashboards, and
docs-generation pipelines can introspect what safelint will check.

The catalogue is *catalogue-only*: severities and enabled defaults come
from the bundled :data:`safelint.core.config.DEFAULTS`, not from the
user's resolved config. User overlays don't change the catalogue of
available rules; they only change which subset runs in their project.

Categories are derived from the leading digit of each ``SAFExxx`` code,
matching the rule-numbering policy documented in ``CLAUDE.md``:

* ``1xx`` function shape
* ``2xx`` error handling
* ``3xx`` side effects / state
* ``4xx`` resource lifecycle
* ``5xx`` loop safety
* ``6xx`` documentation
* ``7xx`` test coverage
* ``8xx`` dataflow
* ``9xx`` framework-specific
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Any

from safelint import __version__
from safelint.core.config import DEFAULTS
from safelint.rules import ALL_RULES


if TYPE_CHECKING:
    from safelint.rules.base import BaseRule


_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"
_SARIF_VERSION = "2.1.0"
_INFORMATION_URI = "https://github.com/shelkesays/safelint"


# Leading-digit → human-readable category band. Matches the numbering
# policy in CLAUDE.md. Unknown digits fall back to ``"other"`` defensively.
_CATEGORY_BY_DIGIT: dict[str, str] = {
    "1": "function shape",
    "2": "error handling",
    "3": "side effects / state",
    "4": "resource lifecycle",
    "5": "loop safety",
    "6": "documentation",
    "7": "test coverage",
    "8": "dataflow",
    "9": "framework-specific",
}


# Stable display order. Iteration order of dicts is insertion order in
# Python 3.7+, but listing it explicitly makes the category-sort
# deterministic even if ``_CATEGORY_BY_DIGIT`` is later edited.
_CATEGORY_ORDER: tuple[str, ...] = ("1", "2", "3", "4", "5", "6", "7", "8", "9")


# Short language abbreviations for the compact text table. JSON / Markdown
# / SARIF outputs use the full ``LanguageDefinition.name`` value instead.
_LANGUAGE_ABBREV: dict[str, str] = {
    "python": "py",
    "javascript": "js",
    "typescript": "ts",
    "java": "java",
    "rust": "rs",
}


@dataclass(frozen=True)
class RuleSpec:
    """Catalogue entry for a single safelint rule.

    Captures everything :func:`safelint.cli._run_list_rules` needs to
    render the four output formats without re-walking ``ALL_RULES``.
    Severity and ``default_enabled`` reflect the bundled DEFAULTS - the
    catalogue is intentionally independent of the user's resolved config.
    """

    code: str
    name: str
    severity: str
    languages: tuple[str, ...]
    default_enabled: bool
    category: str
    category_digit: str
    description: str


def _category_for(code: str) -> tuple[str, str]:
    """Return ``(digit, human-readable category)`` for *code*.

    Falls back to ``("?", "other")`` if the code doesn't start with a
    digit in :data:`_CATEGORY_BY_DIGIT`. The fallback exists so a
    hypothetical mis-numbered rule still gets listed somewhere instead
    of triggering a KeyError at catalogue time.
    """
    digit = code[4:5] if code.startswith("SAFE") and len(code) >= 5 else ""
    return digit or "?", _CATEGORY_BY_DIGIT.get(digit, "other")


def _description_for(rule_cls: type[BaseRule]) -> str:
    """Return a one-line description for *rule_cls*.

    Pulls the first line of the class docstring. Falls back to the rule
    name (humanised) when the class lacks a docstring - none of the
    shipped rules hit the fallback today, but it keeps the catalogue
    output non-empty if a contributor adds a rule without a docstring.
    """
    doc = (rule_cls.__doc__ or "").strip()
    if not doc:
        return rule_cls.name.replace("_", " ").capitalize()
    return doc.splitlines()[0].strip()


def iter_rule_specs() -> list[RuleSpec]:
    """Walk :data:`safelint.rules.ALL_RULES` and return one :class:`RuleSpec` per rule.

    Severity and default-enabled state come from the bundled
    :data:`safelint.core.config.DEFAULTS`. Every shipped rule has a
    DEFAULTS entry today; the lookup falls back to a defensive
    ``severity="error"`` / ``default_enabled=False`` pair if a contributor
    adds a rule class without wiring it into DEFAULTS, so the catalogue
    still renders rather than crashing. The fallback values match the
    safest defaults (most-blocking severity, opt-in enablement) and
    surface the misconfiguration visibly enough that it's easy to spot
    in catalogue output.
    """
    defaults = DEFAULTS.get("rules", {})
    specs: list[RuleSpec] = []
    for cls in ALL_RULES:
        rule_defaults = defaults.get(cls.name, {})
        severity = rule_defaults.get("severity", "error")
        enabled = bool(rule_defaults.get("enabled", False))
        digit, category = _category_for(cls.code)
        specs.append(
            RuleSpec(
                code=cls.code,
                name=cls.name,
                severity=severity,
                languages=tuple(cls.language),
                default_enabled=enabled,
                category=category,
                category_digit=digit,
                description=_description_for(cls),
            )
        )
    return specs


def filter_specs(
    specs: list[RuleSpec],
    *,
    language: str | None = None,
    enabled_only: bool = False,
) -> list[RuleSpec]:
    """Return *specs* narrowed to *language* and/or enabled-by-default rules.

    ``language=None`` keeps every spec. A non-None value filters to
    rules whose ``languages`` tuple includes the requested name (matched
    against the canonical ``LanguageDefinition.name`` values:
    ``python`` / ``javascript`` / ``typescript`` / ``java`` / ``rust``).
    ``enabled_only=True`` additionally drops every default-disabled rule.
    """
    out = specs
    if language is not None:
        out = [s for s in out if language in s.languages]
    if enabled_only:
        out = [s for s in out if s.default_enabled]
    return out


def _grouped_by_category(specs: list[RuleSpec]) -> list[tuple[str, str, list[RuleSpec]]]:
    """Group *specs* by category band, in canonical order.

    Returns ``[(digit, category_name, specs_in_category), ...]`` sorted
    by ``_CATEGORY_ORDER`` then by code within each group. Empty
    categories are omitted - the output skips the ``5xx loop safety``
    heading when no loop rules match the active filter.
    """
    by_digit: dict[str, list[RuleSpec]] = {}
    for s in specs:
        by_digit.setdefault(s.category_digit, []).append(s)
    grouped: list[tuple[str, str, list[RuleSpec]]] = []
    for digit in _CATEGORY_ORDER:
        bucket = by_digit.get(digit)
        if not bucket:
            continue
        bucket.sort(key=lambda s: s.code)
        grouped.append((digit, _CATEGORY_BY_DIGIT[digit], bucket))
    other = by_digit.get("?", [])
    if other:
        other.sort(key=lambda s: s.code)
        grouped.append(("?", "other", other))
    return grouped


def _abbreviate_languages(langs: tuple[str, ...]) -> str:
    """Render *langs* as a compact comma-joined list for the text table."""
    return ",".join(_LANGUAGE_ABBREV.get(lang, lang) for lang in langs)


def _severity_abbrev(sev: str) -> str:
    """Return the 4-char severity column value."""
    return "err " if sev == "error" else "warn"


def format_text(specs: list[RuleSpec]) -> str:
    """Render *specs* as an aligned text table grouped by category band.

    Layout (one line per rule):
        ``CODE     NAME                          SEV    LANGUAGES          DEFAULT``

    Empty input returns an empty string so callers can decide whether
    to print a "no rules match" diagnostic.
    """
    if not specs:
        return ""
    name_w = max(len(s.name) for s in specs)
    lang_strings = {s.code: _abbreviate_languages(s.languages) for s in specs}
    lang_w = max(len(v) for v in lang_strings.values())
    lines: list[str] = []
    for digit, category, bucket in _grouped_by_category(specs):
        lines.append(f"{digit}xx - {category}")
        lines.append("-" * 72)
        for s in bucket:
            default = "on " if s.default_enabled else "off"
            lines.append(f"{s.code}  {s.name.ljust(name_w)}  {_severity_abbrev(s.severity)}  {lang_strings[s.code].ljust(lang_w)}  {default}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_json_listing(specs: list[RuleSpec]) -> str:
    """Render *specs* as a JSON document.

    Shape::

        {
          "version": "<safelint version>",
          "rules": [
            {
              "code": "SAFE101",
              "name": "function_length",
              "severity": "error",
              "default_enabled": true,
              "languages": ["python", "javascript", "typescript", "java", "rust"],
              "category": "function shape",
              "description": "Reject functions whose body exceeds the configured size limit."
            },
            ...
          ]
        }
    """
    document = {
        "version": __version__,
        "rules": [
            {
                "code": s.code,
                "name": s.name,
                "severity": s.severity,
                "default_enabled": s.default_enabled,
                "languages": list(s.languages),
                "category": s.category,
                "description": s.description,
            }
            for s in sorted(specs, key=lambda x: x.code)
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


def format_markdown_listing(specs: list[RuleSpec]) -> str:
    """Render *specs* as one Markdown table per category band.

    Useful for piping into docs (``safelint list-rules --format markdown
    > docs/rules.md``) or for regenerating per-agent skill-file rule
    tables when the catalogue grows. Empty input returns an empty
    string.
    """
    if not specs:
        return ""
    lines: list[str] = []
    for digit, category, bucket in _grouped_by_category(specs):
        lines.append(f"## {digit}xx - {category}")
        lines.append("")
        lines.append("| Code | Name | Severity | Languages | Default | Description |")
        lines.append("|---|---|---|---|---|---|")
        for s in bucket:
            langs = ", ".join(s.languages)
            default = "on" if s.default_enabled else "off"
            lines.append(f"| `{s.code}` | `{s.name}` | {s.severity} | {langs} | {default} | {s.description} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _sarif_descriptor(spec: RuleSpec) -> dict[str, Any]:
    """Build one SARIF ``reportingDescriptor`` for *spec*."""
    return {
        "id": spec.code,
        "name": spec.name,
        "shortDescription": {"text": spec.description},
        "defaultConfiguration": {
            "level": spec.severity,
            "enabled": spec.default_enabled,
        },
        "properties": {
            "languages": list(spec.languages),
            "category": spec.category,
        },
    }


def format_sarif_listing(specs: list[RuleSpec]) -> str:
    """Render *specs* as a SARIF 2.1.0 catalogue document.

    Emits the catalogue under ``runs[0].tool.driver.rules`` with an empty
    ``runs[0].results`` array. This is the SARIF idiom for "tool
    capability description" (results-free run carrying just the rule
    descriptors). Consumed by GitHub code-scanning catalogue UIs and
    any tooling that maps SARIF rule descriptors to other formats.
    """
    document = {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "safelint",
                        "version": __version__,
                        "informationUri": _INFORMATION_URI,
                        "rules": [_sarif_descriptor(s) for s in sorted(specs, key=lambda x: x.code)],
                    }
                },
                "results": [],
            }
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False)
