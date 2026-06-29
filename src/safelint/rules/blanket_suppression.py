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

# PHP comment directives. Bare ``phpcs:ignore`` / ``phpcs:disable`` (no sniff
# list) silence every PHP_CodeSniffer sniff; the scoped
# ``phpcs:ignore Squiz.Foo.Bar`` form is clean. ``@phpstan-ignore-line`` /
# ``@phpstan-ignore-next-line`` suppress every PHPStan error on the line (the
# scoped ``@phpstan-ignore <identifier>`` form is clean). ``@psalm-suppress
# all`` is Psalm's blanket form (scoped ``@psalm-suppress SomeIssue`` is clean).
_PHP_PHPCS_BARE = re.compile(r"^phpcs:(?:ignore|disable)$", re.IGNORECASE)
_PHP_PHPSTAN_LINE = re.compile(r"^@phpstan-ignore(?:-line|-next-line)$", re.IGNORECASE)
_PHP_PSALM_ALL = re.compile(r"^@psalm-suppress\s+all$", re.IGNORECASE)


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


def _go_blanket(comment_text: str) -> str | None:
    """Return the blanket-directive label for a Go comment, or None.

    golangci-lint's ``//nolint`` silences every linter; the scoped
    ``//nolint:errcheck`` (or comma list) targets named linters and is
    clean. staticcheck's bare ``//lint:ignore`` with no check list is
    likewise blanket; the scoped ``//lint:ignore SA1000 reason`` is clean.

    Both directives are recognised by their tools ONLY with no space after
    ``//`` (``//nolint``, not ``// nolint``), so the match requires the
    tight form - a prose comment that merely reads ``// nolint here`` is
    not a real directive and is left alone.

    Only a non-empty ``:`` rule list scopes ``//nolint``. A trailing
    human-readable reason does NOT scope it: ``//nolint // why`` and
    ``//nolint:errcheck // why`` both keep their blanket / scoped status from
    the rule list alone, so the former is still flagged.
    """
    text = comment_text.strip()
    if text.startswith("//nolint"):
        return _go_nolint_label(text[len("//nolint") :])
    if text.startswith("//lint:ignore"):
        return "//lint:ignore" if not text[len("//lint:ignore") :].strip() else None
    return None


def _go_nolint_label(rest: str) -> str | None:
    """Classify the text following ``//nolint``: blanket -> label, scoped / non-directive -> None.

    *rest* is everything after the literal ``//nolint``:

    * ``""`` / starts with whitespace / starts with ``//`` (a trailing
      reason) -> bare directive, blanket.
    * ``:<linters>`` -> scoped to named linters (clean), unless the list is
      empty (``//nolint:`` -> blanket). A trailing `` // reason`` after the
      list is stripped before the emptiness check.
    * anything else (e.g. ``//nolintfoo``) -> not a directive.
    """
    if rest.startswith(":"):
        scope = rest[1:].split("//", 1)[0].strip()
        return "//nolint" if not scope else None
    if rest == "" or rest[0].isspace() or rest.startswith("//"):
        return "//nolint"
    return None


# clang-tidy's NOLINT family. Bare ``// NOLINT`` / ``// NOLINTNEXTLINE`` (and
# the ``NOLINTBEGIN`` / ``NOLINTEND`` block markers) suppress *every* check; a
# parenthesised check list (``// NOLINT(bugprone-foo)``) scopes it and is clean.
# A space after ``//`` is allowed (clang-tidy accepts ``// NOLINT``); the keyword
# is case-sensitive uppercase, so prose ``// nolint here`` is left alone. The
# lookahead keeps ``NOLINTFOO`` from matching the bare ``NOLINT``.
_C_NOLINT = re.compile(r"^//\s*(NOLINT(?:NEXTLINE|BEGIN|END)?)(?=\(|\s|$)(\([^)]*\))?")


def _c_blanket(comment_text: str) -> str | None:
    """Return the blanket-directive label for a C comment, or None.

    A bare clang-tidy ``NOLINT`` form is blanket; a parenthesised check list
    (``// NOLINT(bugprone-foo)``) scopes it and is treated as clean. The one
    parenthesised form that is *still* blanket is the wildcard ``NOLINT(*)`` -
    clang-tidy treats ``(*)`` as "every check", so it suppresses everything just
    like the bare form.
    """
    match = _C_NOLINT.match(comment_text.strip())
    if match is None:
        return None
    args = match.group(2)
    if args and args.replace(" ", "") != "(*)":
        return None
    return f"// {match.group(1)}"


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


def _php_comment_lines(comment_text: str) -> list[str]:
    """Return the cleaned content lines of a PHP comment.

    ``//`` / ``#`` line comments yield a single line. ``/* ... */`` and
    ``/** ... */`` block / docblock comments yield every line with the ``/*``
    / ``*/`` markers and each line's leading ``*`` continuation stripped, so a
    directive sitting on **any** line of a multi-line docblock (not just a
    single-line ``/** @psalm-suppress all */``) is seen.
    """
    text = comment_text.strip()
    if text.startswith("//"):
        return [text[2:].strip()]
    if text.startswith("#"):
        return [text[1:].strip()]
    if text.startswith("/*"):
        inner = text[2:].removesuffix("*/")
        return [line.strip().lstrip("*").strip() for line in inner.splitlines()]
    return [text.strip()]


def _php_blanket_line(line: str) -> str | None:
    """Return the blanket-directive label for a single cleaned comment line, or None."""
    if _PHP_PHPCS_BARE.match(line) or _PHP_PHPSTAN_LINE.match(line):
        return line
    if _PHP_PSALM_ALL.match(line):
        return "@psalm-suppress all"
    return None


def _php_blanket(comment_text: str) -> str | None:
    """Return the blanket-directive label for a PHP comment, or None.

    Bare ``phpcs:ignore`` / ``phpcs:disable`` (no sniff list),
    ``@phpstan-ignore-line`` / ``@phpstan-ignore-next-line`` (no identifier),
    and ``@psalm-suppress all`` are blanket. Their scoped counterparts
    (``phpcs:ignore Squiz.Foo``, ``@phpstan-ignore <id>``,
    ``@psalm-suppress SomeIssue``) target named checks and are left alone.
    Every line of a multi-line docblock is checked, so the directive is found
    wherever it sits.
    """
    for line in _php_comment_lines(comment_text):
        label = _php_blanket_line(line)
        if label is not None:
            return label
    return None


# Comment-based blanket detectors keyed by language. Languages absent
# here (and not handled by the dedicated Java / Rust attribute scans, or
# PHP's combined comment + ``@``-operator scan) fall back to the JS-family
# detector in ``_comment_check``.
_COMMENT_DETECTORS_BY_LANG = {
    "python": _python_blanket,
    "go": _go_blanket,
    "c": _c_blanket,
}


class BlanketSuppressionRule(BaseRule):
    """Flag un-scoped suppressions of other analysers (Power of Ten rule 10)."""

    name = "blanket_suppression"
    code = "SAFE603"
    language = ("python", "javascript", "typescript", "java", "rust", "go", "php", "c")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Flag every blanket foreign-analyser suppression in *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "java":
            return self._java_check(filepath, tree)
        if lang == "rust":
            return self._rust_check(filepath, tree)
        if lang == "php":
            return self._php_check(filepath, tree)
        return self._comment_check(filepath, tree, lang)

    def _php_check(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Scan PHP for blanket directive comments AND the ``@`` error-suppression operator.

        PHP needs both a comment scan (``phpcs:ignore`` / ``@phpstan-ignore-line``
        / ``@psalm-suppress all``) and a node scan: the ``@`` operator
        (``error_suppression_expression``) is PHP's most literal "silence the
        analyser" construct, so every use is flagged.
        """
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            violation = self._php_node_violation(filepath, node)
            if violation is not None:
                violations.append(violation)
        return violations

    def _php_node_violation(self, filepath: str, node: tree_sitter.Node) -> Violation | None:
        """Return a SAFE603 violation for a PHP comment directive or ``@`` operator, else None."""
        if node.type == "comment":
            label = _php_blanket(node_text(node))
            return self._violation(filepath, node, label) if label is not None else None
        if node.type == "error_suppression_expression":
            return self._make_violation_for_node(
                filepath,
                node,
                'The "@" error-suppression operator silences all errors from this expression - handle the error explicitly instead (Power of Ten rule 10)',
            )
        return None

    def _comment_check(self, filepath: str, tree: tree_sitter.Tree, lang: str) -> list[Violation]:
        """Scan comment nodes for Python / Go / JS-family blanket directives."""
        detector = _COMMENT_DETECTORS_BY_LANG.get(lang, _javascript_blanket)
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
