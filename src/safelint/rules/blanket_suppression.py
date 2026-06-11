"""blanket_suppression rule (SAFE603): flag un-scoped suppressions of other analysers.

Holzmann's Power-of-Ten rule 10 ("compile with all warnings enabled and heed
every warning") has a modern failure mode: not disabling warnings at the
compiler, but silencing an entire analyser from inside the source - a bare
``# noqa``, a rule-less ``eslint-disable``, ``@SuppressWarnings("all")``, or
``#[allow(clippy::all)]``. SAFE603 flags the *blanket* forms while leaving
*scoped* suppressions (``# noqa: E501``, ``@SuppressWarnings("unchecked")``)
alone, because a scoped suppression is a deliberate, auditable decision about
one rule.

SAFE603 never flags safelint's own ``# nosafe`` / ``# safelint: ignore``
directives - those are policed by SAFE004 (unused suppression), and SAFE603
fighting them would be self-defeating. The per-language detectors only match
the foreign-analyser directive shapes below, so safelint directives never
match anyway.

Disabled by default: "lint the other linters' comments" is opinionated.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from safelint.languages._node_utils import node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# Python comment directives. Bare forms are blanket; the ``: code`` /
# ``[code]`` / ``=specific`` scoped forms are clean.
_PY_BARE_NOQA = re.compile(r"^noqa$", re.IGNORECASE)
_PY_BARE_TYPE_IGNORE = re.compile(r"^type:\s*ignore\s*$", re.IGNORECASE)
_PY_PYLINT_DISABLE_ALL = re.compile(r"^pylint:\s*disable\s*=\s*all$", re.IGNORECASE)

# JS / TS comment directives. The ``\b`` token boundary on the TS directives
# keeps ``@ts-nocheck`` / ``@ts-ignore`` from matching longer lookalikes like
# ``@ts-nocheckthis``.
_JS_ESLINT_DISABLE = re.compile(r"^(eslint-disable(?:-line|-next-line)?)\b(.*)$")
_JS_TS_IGNORE = re.compile(r"^@ts-ignore\b")
_JS_TS_NOCHECK = re.compile(r"^@ts-nocheck\b")

# A double-quoted Rust string literal, escape-aware: ``\"`` does not terminate
# the literal. Used to blank ``reason = "..."`` contents before scanning a Rust
# ``allow(...)`` attribute for blanket lint names.
_RUST_STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')


def _python_blanket(comment_text: str) -> str | None:
    """Return the blanket-directive label for a Python comment, or None."""
    body = comment_text.lstrip("#").strip()
    if _PY_BARE_NOQA.match(body):
        return "# noqa"
    if _PY_BARE_TYPE_IGNORE.match(body):
        return "# type: ignore"
    if _PY_PYLINT_DISABLE_ALL.match(body):
        return "# pylint: disable=all"
    return None


def _strip_comment_markers(comment_text: str) -> str:
    """Strip ``//`` / ``/* ... */`` markers from a JS-family comment."""
    text = comment_text.strip()
    if text.startswith("//"):
        return text[2:].strip()
    if text.startswith("/*"):
        text = text[2:]
        text = text.removesuffix("*/")
    return text.strip()


def _javascript_blanket(comment_text: str) -> str | None:
    """Return the blanket-directive label for a JS / TS comment, or None.

    ``// @ts-expect-error`` is intentionally NOT flagged: it self-polices
    (it becomes an error when the suppressed error no longer occurs).
    """
    body = _strip_comment_markers(comment_text)
    if _JS_TS_NOCHECK.match(body):
        return "@ts-nocheck"
    if _JS_TS_IGNORE.match(body):
        return "@ts-ignore"
    match = _JS_ESLINT_DISABLE.match(body)
    if match is not None:
        # ESLint allows an optional ``-- description`` suffix after the rule
        # list (``eslint-disable-next-line -- why``). Only the part before
        # ``--`` is the rule list; an empty rule list means a blanket disable
        # regardless of any trailing reason.
        rule_list = match.group(2).split("--", 1)[0].strip()
        if not rule_list:
            return match.group(1)
    return None


def _rust_blanket(attr_text: str) -> str | None:
    """Return the blanket-allow label for a Rust attribute, or None.

    Only ``allow(clippy::all)`` / ``allow(warnings)`` are blanket; a scoped
    allow (``allow(dead_code)`` / ``allow(clippy::too_many_arguments)``) is
    clean. Word-boundary matching keeps ``clippy::all`` from matching
    ``clippy::all_something``.

    String-literal contents are neutralised first so a ``reason = "..."``
    note (Rust 1.81+ attribute syntax) that happens to mention ``warnings``
    or ``clippy::all`` - e.g. ``#[allow(dead_code, reason = "silences
    warnings")]`` - is not mistaken for a blanket allow. The string pattern is
    escape-aware: a backslash-escaped quote inside the reason does not end the
    literal, so an embedded quoted ``warnings`` is still stripped whole.
    """
    text = _RUST_STRING_LITERAL.sub('""', attr_text)
    if "allow" not in text:
        return None
    if re.search(r"(?<!\w)clippy::all(?!\w)", text):
        return "allow(clippy::all)"
    if re.search(r"(?<!\w)warnings(?!\w)", text):
        return "allow(warnings)"
    return None


class BlanketSuppressionRule(BaseRule):
    """Flag un-scoped suppressions of other analysers (Power of Ten rule 10)."""

    name = "blanket_suppression"
    code = "SAFE603"
    language = ("python", "javascript", "typescript", "java", "rust")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every blanket foreign-analyser suppression in *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "java":
            return self._java_check(filepath, tree)
        if lang == "rust":
            return self._rust_check(filepath, tree)
        return self._comment_check(filepath, tree, lang)

    def _comment_check(self, filepath: str, tree: tree_sitter.Tree, lang: str) -> list[Violation]:
        """Scan comment nodes for Python / JS-family blanket directives."""
        detector = _python_blanket if lang == "python" else _javascript_blanket
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "comment":
                continue
            label = detector(node_text(node))
            if label is not None:
                violations.append(self._violation(filepath, node, label))
        return violations

    def _rust_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Scan Rust attribute nodes for ``allow(clippy::all)`` / ``allow(warnings)``."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in ("attribute_item", "inner_attribute_item"):
                continue
            label = _rust_blanket(node_text(node))
            if label is not None:
                violations.append(self._violation(filepath, node, label))
        return violations

    def _java_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Scan Java annotations for ``@SuppressWarnings("all")``."""
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != "annotation":
                continue
            if self._java_suppress_all(node):
                violations.append(self._violation(filepath, node, '@SuppressWarnings("all")'))
        return violations

    @staticmethod
    def _java_suppress_all(annotation_node: tree_sitter.Node) -> bool:
        """Return True if *annotation_node* is ``@SuppressWarnings`` carrying ``"all"``."""
        name = annotation_node.child_by_field_name("name")
        if name is None or node_text(name) != "SuppressWarnings":
            return False
        return any(child.type == "string_literal" and node_text(child).strip("\"'") == "all" for child in walk(annotation_node))

    def _violation(self, filepath: str, node: tree_sitter.Node, label: str) -> Violation:
        """Build the SAFE603 violation for *node* describing the blanket directive *label*."""
        return self._make_violation_for_node(
            filepath,
            node,
            f'Blanket suppression "{label}" silences an entire analyser - suppress specific rule codes instead (Power of Ten rule 10)',
        )
