# Tree-sitter Migration Execution Plan

**Goal:** Replace Python's `ast` module and `tokenize` module with Tree-sitter across all of safelint,  
keeping Python as the only supported language but building the architecture so adding future languages  
(Go, Rust, C, Java, etc.) requires only adding a new file — not touching the engine or rules.

**Who this is for:** A developer with ~6 months experience. Follow every step in order. Do not skip steps.  
Do not make any change not listed here.

**Total estimated time:** 22–27 hours

---

## Import Ordering Rules (read this before writing any code)

Every file you touch in this migration must pass `ruff check src/ tests/` without errors.
Ruff's isort (`I001`) enforces a strict three-group import ordering. Violating it fails the
Final Verification Checklist and the pre-commit hook. Follow this rule everywhere — source
files, rule files, analysis modules, and test files — without exception.

**Before the three groups — future imports:**

`from __future__ import annotations` must be the **first non-docstring, non-comment statement
in every file**. It is NOT part of Group 1. Do not sort it alphabetically among stdlib imports.
Do not omit it. Every file in this migration starts with it, and Python (and ruff) require it
to precede all other import lines:

```python
"""Optional module docstring."""

from __future__ import annotations  # ← always first, before everything else

# Group 1 starts here
import os
...
```

Placing `from __future__ import annotations` anywhere except the very top causes ruff to
report `E402` ("Module level import not at top of file") and may cause a `SyntaxError` or
`SyntaxWarning` in older Python versions.

**The three groups, always in this order, each separated by a blank line:**

```
# Group 1 — Python standard library
import os
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

# Group 2 — Third-party packages (anything installed via pip)
import tree_sitter
import tree_sitter_python

# Group 3 — Local / first-party (safelint itself)
from safelint.languages._node_utils import walk
from safelint.rules.base import BaseRule
```

**Rules:**
- Never mix groups on adjacent lines without a blank line between them.
- Within each group, isort sorts alphabetically. `import X` lines come before `from X import Y` lines.
- `if TYPE_CHECKING:` blocks go at the end of the imports section, after all three groups.
- Inside test files, the same ordering applies. If you add a stdlib or third-party import
  while working in a section that also adds a local import, the stdlib/third-party lines must
  go ABOVE the local lines — not below, even if the plan describes the changes in a different order.
- Never split imports from the same module across multiple lines:
  `from safelint.languages._node_utils import call_name, walk` ✓
  Two separate `from safelint.languages._node_utils import ...` lines ✗ (ruff I001 failure)

---

## Naming Rules (read this before writing any code)

Every variable, parameter, and method you write must have a name that tells the reader what
it holds or does — without needing to look elsewhere. This applies equally to source files,
rule files, analysis modules, and test files.

**The rule in one sentence:** names must be self-explanatory and reasonably short — not cryptic
abbreviations, and not paragraph-length identifiers.

**What "self-explanatory" means:**

A name is self-explanatory when someone reading the line in isolation can tell what the thing is.

| ✗ Too short / cryptic | ✓ Clear and concise |
|---|---|
| `v` (a Violation) | `violation` |
| `ln` (a line number) | `line_num` |
| `cc` (cyclomatic complexity) | `complexity` |
| `_v()` (makes a Violation) | `_make_violation()` |
| `pfi_names` (per-file-ignore names) | `ignored_names` |
| `ts_lineno` (tree-sitter line helper) | `node_lineno` |

**What "reasonably short" means:**

A name is too long when it restates the type, the module, or the surrounding context that is
already obvious from the code. Trim words that add no meaning for the reader.

| ✗ Unnecessarily long | ✓ Clear and concise |
|---|---|
| `the_violation_object` | `violation` |
| `current_line_number_value` | `line_num` |
| `tree_sitter_parsed_tree_result` | `tree` |
| `list_of_active_rule_violations` | `violations` |

**Rules:**

- Single-letter names (`v`, `n`, `e`, `f`) are only acceptable as loop variables in a
  short comprehension where the type is unmistakable from the surrounding expression:
  `[v for v in rule_violations if not _is_suppressed(v, suppressions)]` ✓
  A function parameter named `v` ✗
- Two-letter or abbreviated names (`cc`, `ln`, `pfi`) are never acceptable outside of
  well-known domain abbreviations (e.g. `db` for database connection in a db module).
- Method names must say what the method does, not what it returns. `_make_violation()` ✓,
  `_v()` ✗. Private helpers prefixed with `_` follow the same rule.
- Do not encode the type into the name: `violations_list` ✗, `violations` ✓.
  The type annotation already carries that information.

**Before committing any code in this migration**, scan the file for single- or two-letter
variable names outside of comprehensions and rename them. `ty check` and `ruff` will not
catch naming violations — you must apply this rule manually.

---

## Quick Reference: AST → Tree-sitter Node Type Mapping

Every `isinstance(node, ast.X)` in the old code becomes `node.type == "..."` in the new code.  
This table is your single source of truth. Keep it open while migrating rules.

| Old (`ast` module) | New (Tree-sitter node type string) |
|---|---|
| `ast.FunctionDef` | `"function_definition"` |
| `ast.AsyncFunctionDef` | `"async_function_definition"` |
| `ast.If` | `"if_statement"` |
| `ast.For` | `"for_statement"` |
| `ast.While` | `"while_statement"` |
| `ast.With` | `"with_statement"` |
| `ast.Try` | `"try_statement"` |
| `ast.ExceptHandler` | `"except_clause"` |
| `ast.Assign` | `"assignment"` |
| `ast.AugAssign` | `"augmented_assignment"` |
| `ast.AnnAssign` | `"annotated_assignment"` |
| `ast.Call` | `"call"` |
| `ast.Name` | `"identifier"` |
| `ast.Attribute` | `"attribute"` |
| `ast.Subscript` | `"subscript"` |
| `ast.Global` | `"global_statement"` |
| `ast.Assert` | `"assert_statement"` |
| `ast.Raise` | `"raise_statement"` |
| `ast.Break` | `"break_statement"` |
| `ast.Expr` (bare expression stmt) | `"expression_statement"` |
| `ast.BinOp` | `"binary_operator"` |
| `ast.BoolOp` | `"boolean_operator"` |
| `ast.UnaryOp` | `"unary_operator"` |
| `ast.Compare` | `"comparison_operator"` |
| `ast.IfExp` (ternary) | `"conditional_expression"` |
| `ast.JoinedStr` (f-string) | `"string"` with `"interpolation"` children (single f-string literal) |
| *(no direct equivalent)* | `"concatenated_string"` — adjacent string/f-string literals: `f"{x}" f"{y}"`. **Always check for this node type alongside `"string"` when matching f-string content.** Without it, taint carried by `x` or `y` is silently dropped and `eval(f"{user_input}" f" extra")` would never fire. |
| `ast.FormattedValue` | `"interpolation"` |
| `ast.List` | `"list"` |
| `ast.Tuple` | `"tuple"` |
| `ast.Set` | `"set"` |
| `ast.Constant` with value `True` | `"true"` |
| `ast.Constant` with value `None` | `"none"` |
| `ast.Constant` (number) | `"integer"` or `"float"` |
| `ast.comprehension` | `"for_in_clause"` |
| comprehension `if` filter | `"if_clause"` (**not** `"if_statement"`) |

**Key API changes:**

| Old | New |
|---|---|
| `ast.walk(tree)` | `walk(tree.root_node)` (our custom function) |
| `ast.iter_child_nodes(node)` | `node.children` |
| `node.lineno` | `node.start_point[0] + 1` |
| `node.end_lineno` | `node.end_point[0] + 1` |
| `node.name` (on FunctionDef) | `node_text(node.child_by_field_name("name"))` |
| `node.id` (on Name node) | `node_text(node)` |
| `id(node)` (object identity) | `node.start_byte` |
| `node.func` (on Call) | `node.child_by_field_name("function")` |
| `ast.parse(source)` | `lang.create_parser().parse(source.encode("utf-8"))` (engine); `parse_python(source)` (tests) |

---

## Phase 1: Add Dependencies

**Estimated time: 30 minutes**

### Step 1.1 — Update `pyproject.toml`

Open `pyproject.toml`. Find the `[project]` section. Change:

```toml
dependencies = []
```

to:

```toml
dependencies = [
    "tree-sitter>=0.23.0",
    "tree-sitter-python>=0.23.0",
]
```

### Step 1.2 — Install the new dependencies

Run this in the project root:

```bash
pip install -e ".[dev]"
```

### Step 1.3 — Verify installation works

Create a temporary file called `verify_ts.py` in the project root (delete it after verification):

```python
import tree_sitter
import tree_sitter_python

PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())
parser = tree_sitter.Parser(PYTHON_LANGUAGE)
source = b"def hello(x):\n    return x + 1\n"
tree = parser.parse(source)
root = tree.root_node
print("root type:", root.type)
print("first child type:", root.children[0].type)
print("function name:", root.children[0].child_by_field_name("name").text)
```

Run `python verify_ts.py`. Expected output:
```
root type: module
first child type: function_definition
function name: b'hello'
```

If you see this, Tree-sitter is working. Delete `verify_ts.py`.

---

## Phase 2: Create the Language Registry

**Estimated time: 2 hours**

This is the architectural foundation. It is what allows future languages to be added by adding  
a single file, without touching the engine or any rule.

### Step 2.1 — Create the `languages` package directory

Run these commands:

```bash
mkdir -p src/safelint/languages
touch src/safelint/languages/__init__.py
touch src/safelint/languages/_types.py
touch src/safelint/languages/_node_utils.py
touch src/safelint/languages/python.py
```

### Step 2.2 — Write `src/safelint/languages/_types.py`

This file defines the `LanguageDefinition` dataclass. Every future language will create one instance  
of this and register it.

**Write this exact content into `src/safelint/languages/_types.py`:**

```python
"""Language definition dataclass — one instance per supported language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import tree_sitter


@dataclass(frozen=True)
class LanguageDefinition:
    """All language-specific configuration needed by the engine and suppression parser.

    To add a new language: create a new module in this package, instantiate this
    dataclass, and register it in ``__init__.py``.
    """

    name: str
    file_extensions: frozenset[str]
    comment_node_type: str
    comment_prefix: str
    create_parser: Callable[[], "tree_sitter.Parser"]
```

### Step 2.3 — Write `src/safelint/languages/_node_utils.py`

This file contains **language-agnostic** Tree-sitter helper functions. Every rule will import  
from here instead of using `ast.*` directly.

**Write this exact content into `src/safelint/languages/_node_utils.py`:**

```python
"""Language-agnostic Tree-sitter node utility functions.

These helpers replace ast.walk(), node.lineno, node.name, etc. across all rules.
They work identically regardless of which language grammar was used to parse the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    import tree_sitter


def walk(node: "tree_sitter.Node") -> Iterator["tree_sitter.Node"]:
    """Yield every node in the subtree rooted at *node*, depth-first.

    This replaces ``ast.walk(tree)`` from the old code.
    Usage: ``for node in walk(tree.root_node): ...``

    Implemented iteratively (not recursively) to avoid Python's default
    recursion limit of 1000. ast.walk() is also iterative for the same
    reason. A recursive implementation will crash with RecursionError on
    large or deeply nested source files.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def lineno(node: "tree_sitter.Node") -> int:
    """Return the 1-based start line number of *node*.

    Tree-sitter uses 0-based row numbers. We add 1 to match Python convention
    and to stay compatible with the existing Violation.lineno field.
    """
    return node.start_point[0] + 1


def end_lineno(node: "tree_sitter.Node") -> int:
    """Return the 1-based end line number of *node*."""
    return node.end_point[0] + 1


def node_text(node: "tree_sitter.Node") -> str:
    """Return the source text covered by *node* as a string.

    Returns an empty string if node.text is None (e.g., on error nodes).
    """
    return node.text.decode("utf-8") if node.text else ""


def call_name(call_node: "tree_sitter.Node") -> str | None:
    """Return the bare callable name from a ``call`` node, or None if unresolvable.

    Handles two forms:
    - ``foo(...)``         → returns ``"foo"``
    - ``obj.method(...)``  → returns ``"method"``

    This replaces ``BaseRule._call_name(node.func)`` from the old code.
    Callers must pass the call node itself (not the function sub-node).
    """
    func_node = call_node.child_by_field_name("function")
    if func_node is None:
        return None
    if func_node.type == "identifier":
        return node_text(func_node)
    if func_node.type == "attribute":
        attr_node = func_node.child_by_field_name("attribute")
        return node_text(attr_node) if attr_node else None
    return None
```

### Step 2.4 — Write `src/safelint/languages/python.py`

This file contains everything Python-specific: the language definition, the parser factory,  
and Python-specific node-type constants (the full mapping table from the Quick Reference above).

**Write this exact content into `src/safelint/languages/python.py`:**

```python
"""Python language definition for safelint.

Registers Python as a supported language and exposes all Python-specific
Tree-sitter node type constants that rules use for type-checking nodes.
"""

from __future__ import annotations

import tree_sitter
import tree_sitter_python

from safelint.languages._types import LanguageDefinition


# ---------------------------------------------------------------------------
# Parser factory
# ---------------------------------------------------------------------------

_PYTHON_TS_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


def _create_python_parser() -> tree_sitter.Parser:
    """Return a fresh Tree-sitter parser configured for Python."""
    return tree_sitter.Parser(_PYTHON_TS_LANGUAGE)


# ---------------------------------------------------------------------------
# Language definition (registered in __init__.py)
# ---------------------------------------------------------------------------

PYTHON: LanguageDefinition = LanguageDefinition(
    name="python",
    file_extensions=frozenset({".py", ".pyw"}),
    comment_node_type="comment",
    comment_prefix="#",
    create_parser=_create_python_parser,
)


# ---------------------------------------------------------------------------
# Node type constants
# Use these in rules instead of magic strings.
# ---------------------------------------------------------------------------

FUNCTION_DEF = "function_definition"
ASYNC_FUNCTION_DEF = "async_function_definition"

IF_STATEMENT = "if_statement"
FOR_STATEMENT = "for_statement"
WHILE_STATEMENT = "while_statement"
WITH_STATEMENT = "with_statement"
TRY_STATEMENT = "try_statement"
EXCEPT_CLAUSE = "except_clause"
ELIF_CLAUSE = "elif_clause"
ELSE_CLAUSE = "else_clause"

ASSIGNMENT = "assignment"
AUGMENTED_ASSIGNMENT = "augmented_assignment"
ANNOTATED_ASSIGNMENT = "annotated_assignment"

CALL = "call"
IDENTIFIER = "identifier"
ATTRIBUTE = "attribute"
SUBSCRIPT = "subscript"

GLOBAL_STATEMENT = "global_statement"
ASSERT_STATEMENT = "assert_statement"
RAISE_STATEMENT = "raise_statement"
BREAK_STATEMENT = "break_statement"
RETURN_STATEMENT = "return_statement"
EXPRESSION_STATEMENT = "expression_statement"

BINARY_OPERATOR = "binary_operator"
BOOLEAN_OPERATOR = "boolean_operator"
UNARY_OPERATOR = "unary_operator"
COMPARISON_OPERATOR = "comparison_operator"
CONDITIONAL_EXPRESSION = "conditional_expression"

STRING = "string"
CONCATENATED_STRING = "concatenated_string"  # adjacent strings/f-strings: f"{x}" f"{y}"
INTERPOLATION = "interpolation"
LIST = "list"
TUPLE = "tuple"
SET = "set"

TRUE = "true"
FALSE = "false"
NONE = "none"
INTEGER = "integer"
FLOAT = "float"

FOR_IN_CLAUSE = "for_in_clause"
IF_CLAUSE = "if_clause"  # the `if` filter inside a comprehension — NOT if_statement
COMMENT = "comment"
WITH_ITEM = "with_item"
PARAMETERS = "parameters"
```

### Step 2.5 — Write `src/safelint/languages/__init__.py`

This is the registry. When future languages are added, you import them here and add them to `_REGISTRY`.

**Write this exact content into `src/safelint/languages/__init__.py`:**

```python
"""Language registry — maps file extensions to LanguageDefinition instances."""

from __future__ import annotations

from pathlib import Path

from safelint.languages._types import LanguageDefinition
from safelint.languages.python import PYTHON

_REGISTRY: dict[str, LanguageDefinition] = {}

for _lang in [PYTHON]:
    for _ext in _lang.file_extensions:
        _REGISTRY[_ext] = _lang


def get_language_for_file(filepath: str) -> LanguageDefinition | None:
    """Return the LanguageDefinition for *filepath* based on its extension, or None."""
    # Path.suffix operates on the filename only, not the full path.
    # rsplit(".", 1) on the full string incorrectly splits on dots in directory names
    # (e.g. /home/user.name/no_ext_file → suffix ".name/no_ext_file" instead of "").
    suffix = Path(filepath).suffix
    return _REGISTRY.get(suffix)


__all__ = ["LanguageDefinition", "get_language_for_file", "PYTHON"]
```

### Step 2.6 — Verify the package is importable

Run:

```bash
python -c "from safelint.languages import get_language_for_file, PYTHON; print(PYTHON.name)"
```

Expected output: `python`

---

## Phase 3: Update `BaseRule`

**Estimated time: 30 minutes**

**File:** `src/safelint/rules/base.py`

Replace the **entire file** with:

```python
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
    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
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
    def _call_name(call_node: "tree_sitter.Node") -> str | None:
        """Return the bare callable name from a ``call`` node, or None if unresolvable.

        Pass the call node itself (not the function sub-node).
        Handles ``foo(...)`` → ``"foo"`` and ``obj.method(...)`` → ``"method"``.
        """
        return call_name(call_node)
```

**Key change:** `check_file` now takes `tree: tree_sitter.Tree` instead of `tree: ast.AST`.  
`_call_name` now takes the `call` node itself, not `node.func`. Every caller must be updated (Phase 5).

---

## Phase 4: Update the Engine

**Estimated time: 1.5 hours**

**File:** `src/safelint/core/engine.py`

Replace the **entire file** with:

```python
"""Safety engine - orchestrates the active rule set against source files."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from safelint.core.config import DEFAULTS, SEVERITY_ORDER
from safelint.languages import _REGISTRY, get_language_for_file
from safelint.languages._node_utils import lineno as node_lineno, node_text, walk
from safelint.rules import ALL_RULES
from safelint.rules.base import Violation
from safelint.rules.test_coverage import TestCouplingRule

if TYPE_CHECKING:
    from safelint.rules.base import BaseRule


_log = logging.getLogger(__name__)

_NOSAFE_PREFIX = "nosafe"


def _nosafe_codes(comment: str, prefix: str = "#") -> set[str] | None | Literal[False]:
    """Parse a single comment string and return the nosafe payload.

    Returns:
        ``None``           — bare nosafe (suppress everything on this line)
        ``set[str]``       — nosafe: CODE, ... (suppress named codes/rules)
        ``Literal[False]`` — not a nosafe directive, or malformed
    """
    body = comment[len(prefix):].strip()
    if not body.lower().startswith(_NOSAFE_PREFIX):
        return False
    remainder = body[len(_NOSAFE_PREFIX):].lstrip()
    if remainder == "":
        return None
    if remainder.startswith(":"):
        codes_str = remainder[1:].strip()
        if not codes_str:
            _log.debug("Ignoring malformed nosafe directive with empty payload: %r", comment.strip())
            return False
        codes = {tok.strip() for tok in codes_str.split(",") if tok.strip()}
        if not codes:
            _log.debug(
                "Ignoring malformed nosafe directive with no usable codes: %r",
                comment.strip(),
            )
            return False
        return codes
    return False


def _parse_suppressions(
    tree: "Any",
    comment_node_type: str,
    comment_prefix: str,
) -> dict[int, set[str] | None]:
    """Return a {lineno: codes} suppression map by querying comment nodes in the Tree-sitter tree.

    This replaces the old tokenize-based implementation. Because Tree-sitter
    parses comment nodes as first-class tree nodes, there is no risk of
    confusing a nosafe directive inside a string literal with a real one.

    ``comment_node_type`` and ``comment_prefix`` come from the LanguageDefinition,
    so this function works for any language without modification.
    """
    suppressions: dict[int, set[str] | None] = {}
    for node in walk(tree.root_node):
        if node.type != comment_node_type:
            continue
        comment_text = node_text(node)
        payload = _nosafe_codes(comment_text, prefix=comment_prefix)
        if payload is not False:
            suppressions[node_lineno(node)] = payload
    return suppressions


def _is_suppressed(violation: Violation, suppressions: dict[int, set[str] | None]) -> bool:
    """Return True when *violation* is covered by a nosafe comment on its line."""
    if violation.lineno not in suppressions:
        return False
    codes = suppressions[violation.lineno]
    if codes is None:
        return True
    return violation.code in codes or violation.rule in codes


def _is_per_file_ignored(
    violation: Violation, ignored_names: frozenset[str], ignored_codes: frozenset[str]
) -> bool:
    """Return True when *violation* is suppressed by a per-file ignore pattern."""
    return violation.code.upper() in ignored_codes or violation.rule in ignored_names


@dataclass
class LintResult:
    """Aggregated violations for a single linted file."""

    path: str
    violations: list[Violation] = field(default_factory=list)
    suppressed: int = 0

    @property
    def has_violations(self) -> bool:
        """Return True when at least one violation was found."""
        return bool(self.violations)


class SafetyEngine:
    """Orchestrates the active rule set against a collection of source files."""

    def __init__(
        self,
        config: dict[str, Any],
        changed_files: list[str] | None = None,
    ) -> None:
        """Build the ordered, active rule set from *config*."""
        rules_cfg: dict[str, Any] = config.get("rules", {})
        exec_cfg: dict[str, Any] = config.get("execution", {})
        self.fail_fast: bool = exec_cfg.get("fail_fast", False)
        self.exclude_paths: list[str] = config.get("exclude_paths", [])

        raw_ignore: list[str] = config.get("ignore", [])
        known_names: frozenset[str] = frozenset(cls.name for cls in ALL_RULES)
        known_codes_upper: frozenset[str] = frozenset(cls.code.upper() for cls in ALL_RULES)
        unknown = frozenset(
            e for e in raw_ignore
            if e not in known_names and e.upper() not in known_codes_upper
        )
        if unknown:
            _log.warning(
                "Unknown entries in ignore list (typo or stale rule?): %s",
                ", ".join(sorted(unknown)),
            )
        ignored_names: frozenset[str] = frozenset(raw_ignore)
        ignored_codes_upper: frozenset[str] = frozenset(e.upper() for e in raw_ignore)

        self.rules: list[BaseRule] = self._build_active_rules(
            rules_cfg, exec_cfg, ignored_names, ignored_codes_upper, changed_files
        )
        self.per_file_ignores: list[tuple[str, frozenset[str], frozenset[str]]] = (
            self._parse_per_file_ignores(
                config.get("per_file_ignores", {}), known_names, known_codes_upper
            )
        )

    @staticmethod
    def _build_active_rules(
        rules_cfg: dict[str, Any],
        exec_cfg: dict[str, Any],
        ignored_names: frozenset[str],
        ignored_codes_upper: frozenset[str],
        changed_files: list[str] | None,
    ) -> list[BaseRule]:
        """Return the ordered list of active rules derived from config."""
        order: list[str] = exec_cfg.get("order", [r.name for r in ALL_RULES])
        order_index: dict[str, int] = {name: i for i, name in enumerate(order)}
        active_rules: list[BaseRule] = []
        for cls in ALL_RULES:
            rule_cfg = dict(rules_cfg.get(cls.name, {}))
            default_enabled = DEFAULTS["rules"].get(cls.name, {}).get("enabled", True)
            if not rule_cfg.get("enabled", default_enabled):
                continue
            if cls.code.upper() in ignored_codes_upper or cls.name in ignored_names:
                continue
            if cls is TestCouplingRule and changed_files is not None:
                rule_cfg["_changed_files"] = changed_files
            active_rules.append(cls(rule_cfg))
        return sorted(active_rules, key=lambda r: order_index.get(r.name, len(order)))

    @staticmethod
    def _parse_per_file_ignores(
        raw_pfi: dict[str, list[str]],
        known_names: frozenset[str],
        known_codes_upper: frozenset[str],
    ) -> list[tuple[str, frozenset[str], frozenset[str]]]:
        """Validate and parse per_file_ignores config into (pattern, names, codes_upper) triples."""
        if not isinstance(raw_pfi, dict):
            msg = f"per_file_ignores must be a mapping, got {type(raw_pfi).__name__}"
            raise TypeError(msg)
        result: list[tuple[str, frozenset[str], frozenset[str]]] = []
        for pattern, entries in raw_pfi.items():
            if not isinstance(entries, (list, tuple)):
                msg = f"per_file_ignores[{pattern!r}] must be a list of strings, got {type(entries).__name__}"
                raise TypeError(msg)
            unknown_entries = frozenset(
                e for e in entries
                if e not in known_names and e.upper() not in known_codes_upper
            )
            if unknown_entries:
                _log.warning(
                    "Unknown entries in per_file_ignores[%r] (typo or stale rule?): %s",
                    pattern,
                    ", ".join(sorted(unknown_entries)),
                )
            result.append((pattern, frozenset(entries), frozenset(e.upper() for e in entries)))
        return result

    def _is_excluded(self, filepath: str) -> bool:
        """Return True when *filepath* matches any configured exclusion pattern."""
        posix = Path(filepath).as_posix()
        return any(fnmatch.fnmatchcase(posix, pattern) for pattern in self.exclude_paths)

    def _file_ignored_set(self, filepath: str) -> tuple[frozenset[str], frozenset[str]]:
        """Return (names, codes_upper) accumulated from all per-file patterns matching *filepath*."""
        posix = Path(filepath).as_posix()
        names: set[str] = set()
        codes_upper: set[str] = set()
        for pattern, ignored_names, ignored_codes in self.per_file_ignores:
            if fnmatch.fnmatchcase(posix, pattern):
                names |= ignored_names
                codes_upper |= ignored_codes
        return frozenset(names), frozenset(codes_upper)

    def check_file(self, filepath: str) -> LintResult:
        """Parse *filepath*, run every active rule, apply inline suppressions, return a LintResult."""
        if self._is_excluded(filepath):
            return LintResult(path=filepath)

        lang = get_language_for_file(filepath)
        if lang is None:
            _log.debug("No language support for %s — skipping", filepath)
            return LintResult(path=filepath)

        try:
            source = Path(filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError is NOT a subclass of OSError — it is a subclass of ValueError.
            # read_text(encoding="utf-8") raises UnicodeDecodeError on latin-1 or binary files.
            # Catching only OSError lets UnicodeDecodeError propagate uncaught, crashing the
            # engine with a traceback instead of returning a clean SAFE000 violation.
            _log.debug("Failed to read %s: %s", filepath, exc)
            return LintResult(
                path=filepath,
                violations=[
                    Violation(
                        rule="parse",
                        code="SAFE000",
                        filepath=filepath,
                        lineno=0,
                        message=f"Read error: {exc}",
                        severity="error",
                    )
                ],
            )

        parser = lang.create_parser()
        tree = parser.parse(source.encode("utf-8"))

        if tree.root_node.has_error:
            # Tree-sitter never raises on invalid syntax — it records errors in the tree.
            # We preserve the SAFE000 contract the old ast.parse()-based engine provided:
            # any file that cannot be fully parsed gets exactly one SAFE000 violation and
            # no other rules run against it (a partial tree produces unreliable results).
            _log.warning("Parse error in %s (tree-sitter reported has_error=True)", filepath)
            return LintResult(
                path=filepath,
                violations=[
                    Violation(
                        rule="parse",
                        code="SAFE000",
                        filepath=filepath,
                        lineno=0,
                        message="Parse error: tree-sitter could not fully parse this file",
                        severity="error",
                    )
                ],
            )

        suppressions = _parse_suppressions(tree, lang.comment_node_type, lang.comment_prefix)
        ignored_names, ignored_codes = self._file_ignored_set(filepath)

        active: list[Violation] = []
        suppressed = 0
        for rule in self.rules:
            rule_violations = rule.check_file(filepath, tree)
            after_nosafe = [v for v in rule_violations if not _is_suppressed(v, suppressions)]
            after_pfi = [
                v for v in after_nosafe
                if not _is_per_file_ignored(v, ignored_names, ignored_codes)
            ]
            suppressed += len(rule_violations) - len(after_pfi)
            active.extend(after_pfi)
            if self.fail_fast and after_pfi:
                break

        return LintResult(path=filepath, violations=active, suppressed=suppressed)

    def check_path(self, path: str | Path) -> list[LintResult]:
        """Lint a single file or recursively lint all supported files under a directory."""
        target = Path(path)
        if target.is_file():
            files = [str(target)]
        else:
            # Build one glob pattern per registered extension (e.g. "*.py", "*.pyw").
            # This keeps file discovery at the OS level, matching the original
            # rglob("*.py") behaviour. Using rglob("*") and filtering in Python
            # causes two problems:
            #   1. Performance: stat() is called on every file in the tree,
            #      including non-source files. On large repos with node_modules/
            #      or similar, this is orders of magnitude slower.
            #   2. Footgun: when a new language is added to the registry its
            #      files would silently be linted without any config change,
            #      surprising users.
            seen: set[str] = set()
            for ext in _REGISTRY:
                for p in target.rglob(f"*{ext}"):
                    s = str(p)
                    if s not in seen and not self._is_excluded(s):
                        seen.add(s)
            files = sorted(seen)
        return [self.check_file(f) for f in files]

    @staticmethod
    def partition_violations(
        violations: list[Violation], fail_threshold: int
    ) -> tuple[list[Violation], list[Violation]]:
        """Split violations into (blocking, advisory) lists based on *fail_threshold*."""
        blocking: list[Violation] = []
        advisory: list[Violation] = []
        for v in violations:
            if SEVERITY_ORDER.get(v.severity, 1) >= fail_threshold:
                blocking.append(v)
            else:
                advisory.append(v)
        return blocking, advisory
```

**What changed vs old engine:**
- Removed `import ast`, `import tokenize`, `import io`
- Added `from safelint.languages import get_language_for_file`
- Added `from safelint.languages._node_utils import lineno as node_lineno, node_text, walk` — `node_lineno` is the function that extracts a line number from a Tree-sitter node. The alias keeps it visually distinct from the `lineno` keyword argument used when constructing `Violation` objects in the same file (e.g., `Violation(..., lineno=0, ...)`). Do not rename the alias back to `lineno` — the two uses would become indistinguishable at a glance.
- `_parse_suppressions` now queries Tree-sitter comment nodes (no tokenize pass)
- `_nosafe_codes` now accepts a `prefix` parameter (forward-compatible for multi-language)
- `check_file` now dispatches by language and calls `lang.create_parser().parse(...)`
- `check_path` now builds one `rglob("*<ext>")` per registered extension instead of `rglob("*")`, preserving OS-level glob performance and preventing silent linting of new file types when future languages are added

> **After this step, `python -m safelint` will crash with `AttributeError` until all 12 rule
> files are migrated in Phase 5.** The new engine passes `tree_sitter.Tree` to every rule, but
> unmigrated rules still call `ast.walk(tree)` on it. Do not run `python -m safelint` or the
> full test suite between Phases 4 and 5.12. Phase 5 explains exactly when it is safe to run
> tests again.

---

## Phase 5: Migrate Rules

**Estimated time: 12 hours (~1 hour per rule file)**

**Rules to migrate:**
1. `function_length.py`
2. `nesting_depth.py`
3. `max_arguments.py`
4. `complexity.py`
5. `error_handling.py`
6. `state_purity.py`
7. `loop_safety.py`
8. `side_effects.py`
9. `resource_lifecycle.py`
10. `documentation.py`
11. `dataflow.py` (the rules file — not the analysis module)
12. `test_coverage.py` (type annotation change only — Step 5.12)
13. `analysis/dataflow.py` (the TaintTracker — covered in Phase 6)

**Do each rule one at a time.**

> **Warning — do NOT run the full test suite between individual rule migrations.**
> After Phase 4, the engine passes `tree_sitter.Tree` to every rule. Unmigrated rules still call
> `ast.walk(tree)` on that tree, raising `AttributeError` on the first test that exercises them.
> With `-x`, `pytest` stops immediately on the first failure and the developer appears permanently
> stuck. The incremental test loop does not work until ALL 12 rule files are migrated.
>
> **Instead, run the full test suite exactly once, after completing Step 5.12 (the last rule):**
>
> ```bash
> pytest tests/ -x -q
> ```
>
> Fix any failures, then proceed to Phase 6.
>
> **Expected failures you must NOT try to fix here:** After Step 5.12, tests for `TaintedSinkRule`
> (the rule in `dataflow.py` that calls `TaintTracker`) will still fail with `AttributeError` or
> `TypeError`. This is expected and unfixable at this point — `analysis/dataflow.py` still contains
> the old `ast.NodeVisitor`-based `TaintTracker`, which receives a `tree_sitter.Node` from the
> migrated `dataflow.py` rule file. **Do not attempt to fix these failures.** They are resolved in
> Phase 6 when `analysis/dataflow.py` is rewritten. All other test failures after Step 5.12 must
> be fixed before proceeding.

---

### Step 5.1 — `src/safelint/rules/function_length.py`

Replace the entire file:

```python
"""function_length rule - body must not exceed max_lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import end_lineno, lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class FunctionLengthRule(BaseRule):
    """Reject functions whose body exceeds the configured line limit."""

    name = "function_length"
    code = "SAFE101"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag any function or async function longer than max_lines."""
        max_lines: int = self.config.get("max_lines", 60)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            length = end_lineno(node) - lineno(node)
            if length > max_lines:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" is {length} lines (max {max_lines})',
                    )
                )
        return violations
```

---

### Step 5.2 — `src/safelint/rules/nesting_depth.py`

**Important:** In Tree-sitter's Python grammar, `elif` is represented as `"elif_clause"` — not as  
another `"if_statement"`. This means the special `elif` depth correction from the old code is  
**no longer needed for nesting depth**. The new code is simpler.

> **Do not apply this reasoning to Step 5.4 (complexity).** Nesting depth and cyclomatic complexity
> are different metrics. An `elif` does not add a new nesting level (so it is correctly excluded
> from `_DEPTH_NODE_TYPES`), but it IS a separate decision branch that increments cyclomatic
> complexity. Step 5.4 explicitly imports and counts `ELIF_CLAUSE` for exactly this reason.

Replace the entire file:

```python
"""nesting_depth rule - control-flow nesting must not exceed max_depth."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_STATEMENT,
    TRY_STATEMENT,
    WHILE_STATEMENT,
    WITH_STATEMENT,
)
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation

_DEPTH_NODE_TYPES = frozenset({
    IF_STATEMENT,
    FOR_STATEMENT,
    WHILE_STATEMENT,
    WITH_STATEMENT,
    TRY_STATEMENT,
})


class NestingDepthRule(BaseRule):
    """Reject functions whose control-flow nesting exceeds the configured depth."""

    name = "nesting_depth"
    code = "SAFE102"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag any function whose maximum control-flow nesting depth exceeds max_depth."""
        max_depth: int = self.config.get("max_depth", 2)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            depth = self._max_depth(node)  # node is the function_definition root
            if depth > max_depth:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" nesting depth is {depth} (max {max_depth})',
                    )
                )
        return violations

    @staticmethod
    def _max_depth(root: "tree_sitter.Node") -> int:
        """Return the maximum control-flow nesting depth rooted at *root*.

        Only the node types in _DEPTH_NODE_TYPES increment the depth counter.
        ``elif_clause`` is NOT in this set — in Tree-sitter's Python grammar,
        elif is its own node type, so it does not double-count like it did with
        the ast module's representation.

        Implemented iteratively (not recursively) for the same reason walk() is
        iterative: a recursive implementation hits Python's default call-stack
        limit of 1000 on large or deeply nested function bodies.
        """
        max_seen = 0
        # Stack holds (node, depth_at_node) pairs.
        stack: list[tuple["tree_sitter.Node", int]] = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if node.type in _DEPTH_NODE_TYPES:
                depth += 1
            if depth > max_seen:
                max_seen = depth
            for child in node.children:
                stack.append((child, depth))
        return max_seen
```

---

### Step 5.3 — `src/safelint/rules/max_arguments.py`

Replace the entire file:

```python
"""max_arguments rule - argument count (excluding self/cls) must not exceed max_args."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation

# Parameter node types that count toward the argument limit.
# Deliberately excludes list_splat_pattern (*args) and
# dictionary_splat_pattern (**kwargs) to match the old ast behaviour.
_COUNTED_PARAM_TYPES = frozenset({
    "identifier",
    "typed_parameter",
    "default_parameter",
    "typed_default_parameter",
})


def _count_args(func_node: "tree_sitter.Node") -> tuple[int, str | None]:
    """Return (count, first_param_name) for *func_node*.

    ``first_param_name`` is used to detect and skip ``self`` / ``cls``.
    """
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:
        return 0, None
    count = 0
    first_name: str | None = None
    for child in params_node.named_children:
        if child.type not in _COUNTED_PARAM_TYPES:
            continue
        count += 1
        if first_name is None:
            if child.type == "identifier":
                first_name = node_text(child)
            else:
                name_node = child.child_by_field_name("name")
                if name_node:
                    first_name = node_text(name_node)
    return count, first_name


class MaxArgumentsRule(BaseRule):
    """Reject functions whose argument count (excluding self/cls) exceeds the limit."""

    name = "max_arguments"
    code = "SAFE103"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag any function with more arguments than max_args."""
        max_args: int = self.config.get("max_args", 7)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            count, first_name = _count_args(node)
            if first_name in ("self", "cls"):
                count -= 1
            if count > max_args:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" has {count} arguments (max {max_args})',
                    )
                )
        return violations
```

---

### Step 5.4 — `src/safelint/rules/complexity.py`

Replace the entire file:

```python
"""complexity rule - cyclomatic complexity must not exceed max_complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    BOOLEAN_OPERATOR,
    CONDITIONAL_EXPRESSION,
    ELIF_CLAUSE,
    EXCEPT_CLAUSE,
    FOR_IN_CLAUSE,
    FOR_STATEMENT,
    FUNCTION_DEF,
    IF_CLAUSE,
    IF_STATEMENT,
    WHILE_STATEMENT,
)
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class ComplexityRule(BaseRule):
    """Reject functions whose cyclomatic complexity exceeds max_complexity."""

    name = "complexity"
    code = "SAFE104"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag functions whose cyclomatic complexity exceeds the configured maximum."""
        max_cc: int = self.config.get("max_complexity", 10)
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            complexity = self._cyclomatic_complexity(node)
            if complexity > max_cc:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" has cyclomatic complexity {complexity} (max {max_cc})'
                        " - split into smaller functions",
                    )
                )
        return violations

    @staticmethod
    def _cyclomatic_complexity(func_node: "tree_sitter.Node") -> int:
        """Count cyclomatic complexity for *func_node* (McCabe 1976).

        Increments for:
        - if / elif / for / while / except → each is one branch
        - boolean_operator → each extra operand is one branch
          (``a and b and c`` has 2 boolean operators but adds 2 to CC)
        - conditional_expression (ternary) → one branch
        - for_in_clause (comprehension condition) → one branch per ``if`` inside

        NOTE: In tree-sitter-python, ``elif`` is an ``elif_clause`` node — NOT a
        second ``if_statement``. The old ast-based code counted each elif as a
        separate ``ast.If`` node. Omitting ``ELIF_CLAUSE`` here would undercount
        complexity by one for every elif branch, breaking existing tests.
        """
        complexity = 1
        for node in walk(func_node):
            if node.type in (IF_STATEMENT, ELIF_CLAUSE, FOR_STATEMENT, WHILE_STATEMENT,
                              EXCEPT_CLAUSE, CONDITIONAL_EXPRESSION):
                complexity += 1
            elif node.type == BOOLEAN_OPERATOR:
                # Each boolean_operator node connects exactly two operands.
                # A chain ``a and b and c`` produces two boolean_operator nodes.
                # Each adds 1 branch, so we simply count nodes.
                complexity += 1
            elif node.type == FOR_IN_CLAUSE:
                # Count the number of ``if`` filters inside this comprehension clause.
                # Comprehension filters use the node type "if_clause", NOT "if_statement".
                # "if_statement" is for standalone if blocks and never appears inside a
                # for_in_clause. Using IF_STATEMENT here would always return 0.
                complexity += sum(1 for child in node.children if child.type == IF_CLAUSE)
        return complexity
```

---

### Step 5.5 — `src/safelint/rules/error_handling.py`

Replace the entire file:

```python
"""Error-handling rules: bare_except, empty_except, logging_on_error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, walk
from safelint.languages.python import (
    ATTRIBUTE,
    CALL,
    EXCEPT_CLAUSE,
    IDENTIFIER,
    RAISE_STATEMENT,
    TUPLE,
    TRY_STATEMENT,
)
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class BareExceptRule(BaseRule):
    """Reject bare ``except:`` clauses that silently catch SystemExit and KeyboardInterrupt."""

    name = "bare_except"
    code = "SAFE201"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag every except handler with no exception type specified."""
        violations = []
        for node in walk(tree.root_node):
            if node.type != TRY_STATEMENT:
                continue
            for child in node.children:
                if child.type != EXCEPT_CLAUSE:
                    continue
                # In Tree-sitter's Python grammar, a bare ``except:`` has no
                # named children before the colon — only the keyword "except"
                # and ":". A typed except has an identifier, attribute, or tuple
                # child. The tuple case covers ``except (ValueError, TypeError):``
                # which uses a "tuple" node for the exception type — NOT an
                # identifier. Missing "tuple" here produces a false positive,
                # flagging every multi-exception handler as a bare except.
                has_exception_type = any(
                    c.type in (IDENTIFIER, ATTRIBUTE, TUPLE) for c in child.named_children
                )
                if not has_exception_type:
                    violations.append(
                        self._make_violation(
                            filepath,
                            lineno(child),
                            "Bare except clause - specify the exception type(s)",
                        )
                    )
        return violations


class EmptyExceptRule(BaseRule):
    """Reject except blocks whose body is empty (silent failure)."""

    name = "empty_except"
    code = "SAFE202"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag every except handler with an empty body."""
        violations = []
        for node in walk(tree.root_node):
            if node.type != TRY_STATEMENT:
                continue
            for child in node.children:
                if child.type != EXCEPT_CLAUSE:
                    continue
                # The body of an except_clause is a "block" child.
                body_node = child.child_by_field_name("body")
                if body_node is None:
                    # Try alternate: block is last named child
                    named = child.named_children
                    body_node = named[-1] if named else None
                body_is_empty = body_node is None or not body_node.named_children
                if body_is_empty:
                    violations.append(
                        self._make_violation(
                            filepath,
                            lineno(child),
                            "Empty except block - add error handling or a logging call",
                        )
                    )
        return violations


class LoggingOnErrorRule(BaseRule):
    """Require a logging call in every except block that does not simply re-raise."""

    name = "logging_on_error"
    code = "SAFE203"

    _LOG_METHODS = frozenset({
        "debug", "info", "warning", "error", "exception", "critical"
    })

    def _only_reraises(self, except_node: "tree_sitter.Node") -> bool:
        """Return True when the handler body is just a bare ``raise``."""
        body_node = except_node.child_by_field_name("body")
        if body_node is None:
            named = except_node.named_children
            body_node = named[-1] if named else None
        if body_node is None:
            return False
        stmts = body_node.named_children
        if len(stmts) != 1:
            return False
        stmt = stmts[0]
        if stmt.type != RAISE_STATEMENT:
            return False
        # A bare ``raise`` has no named children (no exception expression).
        return not stmt.named_children

    def _has_log_call(self, except_node: "tree_sitter.Node") -> bool:
        """Return True when the handler body contains at least one logging call."""
        for node in walk(except_node):
            if node.type != CALL:
                continue
            name = call_name(node)
            if name and name in self._LOG_METHODS:
                return True
        return False

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag except blocks that handle an error without any logging call."""
        violations = []
        for node in walk(tree.root_node):
            if node.type != TRY_STATEMENT:
                continue
            for child in node.children:
                if child.type != EXCEPT_CLAUSE:
                    continue
                body_node = child.child_by_field_name("body")
                if body_node is None:
                    named = child.named_children
                    body_node = named[-1] if named else None
                has_body = body_node is not None and bool(body_node.named_children)
                if has_body and not self._only_reraises(child) and not self._has_log_call(child):
                    violations.append(
                        self._make_violation(
                            filepath,
                            lineno(child),
                            "Except block missing logging call"
                            " - errors must be logged before being swallowed",
                        )
                    )
        return violations
```

---

### Step 5.6 — `src/safelint/rules/state_purity.py`

Replace the entire file:

```python
"""State & purity rules: global_state and global_mutation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import (
    ANNOTATED_ASSIGNMENT,
    ASSIGNMENT,
    ASYNC_FUNCTION_DEF,
    AUGMENTED_ASSIGNMENT,
    FUNCTION_DEF,
    GLOBAL_STATEMENT,
    IDENTIFIER,
)
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class GlobalStateRule(BaseRule):
    """Reject use of the ``global`` keyword inside functions."""

    name = "global_state"
    code = "SAFE301"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag any function that declares a global variable."""
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else "<anonymous>"
            for child in walk(node):
                if child.type != GLOBAL_STATEMENT:
                    continue
                names = ", ".join(
                    node_text(c) for c in child.named_children if c.type == IDENTIFIER
                )
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(child),
                        f'Function "{func_name}" declares global: {names}'
                        " - use dependency injection instead",
                    )
                )
        return violations


class GlobalMutationRule(BaseRule):
    """Reject functions that declare globals and then write to them."""

    name = "global_mutation"
    code = "SAFE302"

    def _collect_global_names(self, func_node: "tree_sitter.Node") -> set[str]:
        """Return all names declared via ``global`` inside *func_node*."""
        names: set[str] = set()
        for child in walk(func_node):
            if child.type == GLOBAL_STATEMENT:
                for c in child.named_children:
                    if c.type == IDENTIFIER:
                        names.add(node_text(c))
        return names

    def _mutating_assignments(
        self,
        func_node: "tree_sitter.Node",
        global_names: set[str],
    ) -> list[tuple[int, str]]:
        """Return (lineno, name) for each write to a declared global in *func_node*."""
        results = []
        for node in walk(func_node):
            if node.type in (ASSIGNMENT, AUGMENTED_ASSIGNMENT):
                left = node.child_by_field_name("left")
                if left and left.type == IDENTIFIER and node_text(left) in global_names:
                    results.append((lineno(node), node_text(left)))
            elif node.type == ANNOTATED_ASSIGNMENT:
                # annotated_assignment: first named child is the target identifier
                if node.named_children:
                    target = node.named_children[0]
                    if target.type == IDENTIFIER and node_text(target) in global_names:
                        results.append((lineno(node), node_text(target)))
        return results

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag every write to a declared global variable inside a function."""
        violations = []
        for func in walk(tree.root_node):
            if func.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            global_names = self._collect_global_names(func)
            if not global_names:
                continue
            name_node = func.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else "<anonymous>"
            for line_num, name in self._mutating_assignments(func, global_names):
                violations.append(
                    self._make_violation(
                        filepath,
                        line_num,
                        f'Function "{func_name}" writes to global "{name}"'
                        " - globals must not be mutated",
                    )
                )
        return violations
```

---

### Step 5.7 — `src/safelint/rules/loop_safety.py`

Replace the entire file:

```python
"""loop_safety rule - while True must have a break; others must use comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, walk
from safelint.languages.python import BREAK_STATEMENT, COMPARISON_OPERATOR, TRUE, WHILE_STATEMENT
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class UnboundedLoopRule(BaseRule):
    """Flag while loops that lack a provable bound."""

    name = "unbounded_loops"
    code = "SAFE501"

    def _check_while_node(
        self, filepath: str, node: "tree_sitter.Node"
    ) -> Violation | None:
        """Return a violation if *node* is an unbounded while loop, else None."""
        condition = node.child_by_field_name("condition")
        if condition is None:
            return None

        is_literal_true = condition.type == TRUE

        if is_literal_true:
            has_break = any(c.type == BREAK_STATEMENT for c in walk(node))
            if not has_break:
                return self._make_violation(
                    filepath,
                    lineno(node),
                    "while True loop has no break - potential infinite loop",
                )
            return None

        if condition.type != COMPARISON_OPERATOR:
            return self._make_violation(
                filepath,
                lineno(node),
                "while loop condition is not a comparison - verify the loop is bounded",
            )
        return None

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag while loops that may be infinite."""
        violations = []
        for node in walk(tree.root_node):
            if node.type != WHILE_STATEMENT:
                continue
            v = self._check_while_node(filepath, node)
            if v:
                violations.append(v)
        return violations
```

---

### Step 5.8 — `src/safelint/rules/side_effects.py`

Replace the entire file:

```python
"""Side-effect rules: side_effects_hidden and side_effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, node_text, walk
from safelint.languages.python import ASYNC_FUNCTION_DEF, CALL, FUNCTION_DEF
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class SideEffectsHiddenRule(BaseRule):
    """Reject functions with pure-sounding names that perform I/O."""

    name = "side_effects_hidden"
    code = "SAFE303"

    def _first_io_call(
        self, func_node: "tree_sitter.Node", io_funcs: frozenset[str]
    ) -> "tree_sitter.Node | None":
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in walk(func_node):
            if child.type != CALL:
                continue
            name = call_name(child)
            if name and name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag pure-named functions that contain I/O calls."""
        io_funcs: frozenset[str] = frozenset(
            self.config.get("io_functions", ["open", "print", "input"])
        )
        pure_prefixes: tuple[str, ...] = tuple(self.config.get("pure_prefixes", []))

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            name_lower = func_name.lower()
            if not any(
                name_lower.startswith(p) or name_lower == p.rstrip("_")
                for p in pure_prefixes
            ):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(io_call),
                        f'Function "{func_name}" looks pure but calls I/O primitive "{io_name}"'
                        " - rename to signal intent or use dependency injection",
                    )
                )
        return violations


class SideEffectsRule(BaseRule):
    """Flag I/O primitives called inside any function not explicitly named for I/O."""

    name = "side_effects"
    code = "SAFE304"

    def _first_io_call(
        self, func_node: "tree_sitter.Node", io_funcs: frozenset[str]
    ) -> "tree_sitter.Node | None":
        """Return the first I/O call node found inside *func_node*, or None."""
        for child in walk(func_node):
            if child.type != CALL:
                continue
            name = call_name(child)
            if name and name in io_funcs:
                return child
        return None

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag functions that hide side effects behind a non-I/O name."""
        io_funcs: frozenset[str] = frozenset(
            self.config.get("io_functions", ["open", "print", "input"])
        )
        io_keywords: list[str] = self.config.get("io_name_keywords", [])

        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            name_node = node.child_by_field_name("name")
            func_name = node_text(name_node) if name_node else ""
            if any(kw in func_name for kw in io_keywords):
                continue
            io_call = self._first_io_call(node, io_funcs)
            if io_call:
                io_name = call_name(io_call) or "<unknown>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(io_call),
                        f'Function "{func_name}" calls I/O primitive "{io_name}"'
                        " - rename to signal intent or use dependency injection",
                    )
                )
        return violations
```

---

### Step 5.9 — `src/safelint/rules/resource_lifecycle.py`

**Key change:** `id(node)` is replaced by `node.start_byte` for deduplication.  
`node.start_byte` is unique per call site in the source file (two different calls cannot  
start at the same byte offset).

Replace the entire file:

```python
"""resource_lifecycle rule - tracked resource functions must use context managers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, walk
from safelint.languages.python import CALL, WITH_ITEM, WITH_STATEMENT
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class ResourceLifecycleRule(BaseRule):
    """Require tracked resource-acquisition calls to be wrapped in a with statement."""

    name = "resource_lifecycle"
    code = "SAFE401"

    def _collect_guarded(
        self, tree: "tree_sitter.Tree", tracked: frozenset[str]
    ) -> set[int]:
        """Return the set of start_byte values for tracked calls already inside a with block.

        We use ``node.start_byte`` as a unique identifier for each call node.
        Two different call nodes in the same file always have different start_byte values.
        """
        guarded: set[int] = set()
        for node in walk(tree.root_node):
            if node.type != WITH_STATEMENT:
                continue
            for child in walk(node):
                if child.type != WITH_ITEM:
                    continue
                value = child.child_by_field_name("value")
                if value and value.type == CALL:
                    name = call_name(value)
                    if name and name in tracked:
                        guarded.add(value.start_byte)
        return guarded

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag unguarded calls to tracked resource-acquisition functions."""
        tracked: frozenset[str] = frozenset(
            self.config.get("tracked_functions", ["open"])
        )
        cleanup: frozenset[str] = frozenset(
            self.config.get("cleanup_patterns", ["close"])
        )
        guarded = self._collect_guarded(tree, tracked)
        cleanup_str = " / ".join(sorted(cleanup))

        violations = []
        for node in walk(tree.root_node):
            if node.type != CALL:
                continue
            name = call_name(node)
            if not name or name not in tracked or node.start_byte in guarded:
                continue
            violations.append(
                self._make_violation(
                    filepath,
                    lineno(node),
                    f'"{name}()" called outside a with block - use a context manager'
                    f" or ensure {cleanup_str} is called on all exit paths",
                )
            )
        return violations
```

---

### Step 5.10 — `src/safelint/rules/documentation.py`

Replace the entire file:

```python
"""documentation rule - functions should contain at least one assert (heuristic)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import lineno, node_text, walk
from safelint.languages.python import ASSERT_STATEMENT, ASYNC_FUNCTION_DEF, FUNCTION_DEF
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


class MissingAssertionsRule(BaseRule):
    """Warn when a function contains no assert statements (disabled by default)."""

    name = "missing_assertions"
    code = "SAFE601"

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag functions that lack any assert statement."""
        violations = []
        for node in walk(tree.root_node):
            if node.type not in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                continue
            has_assert = any(c.type == ASSERT_STATEMENT for c in walk(node))
            if not has_assert:
                name_node = node.child_by_field_name("name")
                func_name = node_text(name_node) if name_node else "<anonymous>"
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Function "{func_name}" has no assert statements',
                    )
                )
        return violations
```

---

### Step 5.11 — `src/safelint/rules/dataflow.py`

This file has three rules: `TaintedSinkRule`, `ReturnValueIgnoredRule`, `NullDereferenceRule`.  
`TaintedSinkRule` uses `TaintTracker` from `analysis/dataflow.py` — that module is rewritten  
in Phase 6. Migrate `ReturnValueIgnoredRule` and `NullDereferenceRule` here, and update  
`TaintedSinkRule`'s parameter extraction.

Replace the entire file:

```python
"""Dataflow hybrid rules: tainted_sink, return_value_ignored, null_dereference."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from safelint.analysis.dataflow import TaintTracker
from safelint.languages._node_utils import call_name, lineno, node_text, walk
from safelint.languages.python import (
    ASYNC_FUNCTION_DEF,
    ATTRIBUTE,
    CALL,
    EXPRESSION_STATEMENT,
    FUNCTION_DEF,
    IDENTIFIER,
    SUBSCRIPT,
)
from safelint.rules.base import BaseRule

if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


# ---------------------------------------------------------------------------
# Parameter extraction helper
# ---------------------------------------------------------------------------

_ALL_PARAM_TYPES = frozenset({
    "identifier",
    "typed_parameter",
    "default_parameter",
    "typed_default_parameter",
    "list_splat_pattern",
    "dictionary_splat_pattern",
})


def _param_names(func_node: "tree_sitter.Node") -> set[str]:
    """Return all parameter names for *func_node*, excluding self / cls."""
    params_node = func_node.child_by_field_name("parameters")
    if params_node is None:
        return set()
    names: set[str] = set()
    for child in params_node.named_children:
        if child.type not in _ALL_PARAM_TYPES:
            continue
        if child.type == "identifier":
            name = node_text(child)
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            # *args and **kwargs: first named child is the identifier
            inner = child.named_children[0] if child.named_children else None
            name = node_text(inner) if inner else ""
        else:
            name_node = child.child_by_field_name("name")
            name = node_text(name_node) if name_node else ""
        if name and name not in ("self", "cls"):
            names.add(name)
    return names


# ---------------------------------------------------------------------------
# TaintedSinkRule
# ---------------------------------------------------------------------------


class TaintedSinkRule(BaseRule):
    """Track user-controlled inputs flowing into dangerous sinks."""

    name = "tainted_sink"
    code = "SAFE801"

    _DEFAULT_SINKS: ClassVar[list[str]] = [
        "eval", "exec", "compile", "system", "popen", "Popen",
        "run", "call", "check_output", "execute",
    ]
    _DEFAULT_SANITIZERS: ClassVar[list[str]] = [
        "escape", "sanitize", "clean", "validate", "quote", "encode", "bleach",
    ]
    _DEFAULT_SOURCES: ClassVar[list[str]] = [
        "input", "readline", "recv", "recvfrom", "read",
    ]

    def _check_func(
        self,
        filepath: str,
        func_node: "tree_sitter.Node",
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
    ) -> list[Violation]:
        """Run taint analysis on a single function and return violations."""
        params = _param_names(func_node)
        tracker = TaintTracker(params, sinks, sanitizers, sources)
        tracker.visit(func_node)
        return [
            self._make_violation(
                filepath,
                line_num,
                f'Tainted variable "{var}" flows into dangerous sink "{sink}"'
                " - sanitize input before use",
            )
            for line_num, var, sink in tracker.sink_hits
        ]

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Run taint analysis on every function in *tree*."""
        sinks = frozenset(self.config.get("sinks", self._DEFAULT_SINKS))
        sanitizers = frozenset(self.config.get("sanitizers", self._DEFAULT_SANITIZERS))
        sources = frozenset(self.config.get("sources", self._DEFAULT_SOURCES))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type in (FUNCTION_DEF, ASYNC_FUNCTION_DEF):
                violations.extend(self._check_func(filepath, node, sinks, sanitizers, sources))
        return violations


# ---------------------------------------------------------------------------
# ReturnValueIgnoredRule
# ---------------------------------------------------------------------------


class ReturnValueIgnoredRule(BaseRule):
    """Flag calls to error-signalling functions whose return value is discarded."""

    name = "return_value_ignored"
    code = "SAFE802"

    _DEFAULT_FLAGGED: ClassVar[list[str]] = [
        "run", "call", "check_output",
        "write", "send", "sendall", "sendfile",
        "seek", "truncate",
        "remove", "unlink", "rename", "replace",
        "makedirs", "mkdir", "rmdir",
    ]

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag bare calls whose return value is discarded."""
        flagged = frozenset(self.config.get("flagged_calls", self._DEFAULT_FLAGGED))
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            # expression_statement wraps a bare expression used as a statement.
            # If the sole child is a call node and that call is flagged, emit.
            if node.type != EXPRESSION_STATEMENT:
                continue
            named = node.named_children
            if not named or named[0].type != CALL:
                continue
            call_node = named[0]
            name = call_name(call_node)
            if name and name in flagged:
                violations.append(
                    self._make_violation(
                        filepath,
                        lineno(node),
                        f'Return value of "{name}" is discarded'
                        " - check the result or assign it to a named variable",
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# NullDereferenceRule
# ---------------------------------------------------------------------------


class NullDereferenceRule(BaseRule):
    """Flag chained attribute or subscript access on calls that can return None."""

    name = "null_dereference"
    code = "SAFE803"

    _DEFAULT_NULLABLE: ClassVar[frozenset[str]] = frozenset({
        "get", "pop", "find", "next", "first",
        "one_or_none", "scalar", "scalar_one_or_none", "fetchone",
    })

    def _deref_hit(
        self, node: "tree_sitter.Node", nullable: frozenset[str]
    ) -> tuple[int, str] | None:
        """Return (lineno, method) if *node* is an unsafe chained dereference."""
        if node.type not in (ATTRIBUTE, SUBSCRIPT):
            return None
        # The two node types use different field names for the object being accessed:
        #   attribute  → field "object"  e.g. result.strip()
        #   subscript  → field "value"   e.g. result[0]
        # Using "object" for both would return None for subscript nodes, silently
        # skipping all subscript-based null-dereference patterns.
        if node.type == ATTRIBUTE:
            obj = node.child_by_field_name("object")
        else:
            obj = node.child_by_field_name("value")
        if obj is None or obj.type != CALL:
            return None
        name = call_name(obj)
        if name and name in nullable:
            return lineno(node), name
        return None

    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:
        """Flag immediate dereferences on nullable-returning calls."""
        extra: frozenset[str] = frozenset(self.config.get("nullable_methods", []))
        nullable = self._DEFAULT_NULLABLE | extra
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            result = self._deref_hit(node, nullable)
            if result:
                line_num, method = result
                violations.append(
                    self._make_violation(
                        filepath,
                        line_num,
                        f'Result of "{method}()" is immediately dereferenced without a None check'
                        ' - guard with "if result is not None"',
                    )
                )
        return violations
```

---

### Step 5.12 — `src/safelint/rules/test_coverage.py`

This file is the only rule file that does **not** use the Tree-sitter tree at all — both rules do
filesystem lookups and ignore the `tree` argument entirely. The only change needed is to update the
type annotation and the `TYPE_CHECKING` import so `ty check` does not fail with an
incompatible-override error after Phase 3 changed the abstract method signature.

> **Important:** The Final Verification Checklist's grep command
> (`grep -r "^import ast" src/safelint/`) silently misses this file because the import is
> **indented** (`    import ast` inside `if TYPE_CHECKING:`). `ty check` WILL catch it. Complete
> this step before running `ty check` or you will see an error like:
> `error: method "check_file" overrides abstract method with incompatible signature`.

Replace the `TYPE_CHECKING` block at the top of the file:

```python
# OLD — remove this
if TYPE_CHECKING:
    import ast
    from safelint.rules.base import Violation

# NEW — replace with this
if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation
```

Then update **both** `check_file` signatures from:

```python
def check_file(self, filepath: str, tree: ast.AST) -> list[Violation]:  # noqa: ARG002
```

to:

```python
def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:  # noqa: ARG002
```

Apply this change to `TestExistenceRule.check_file` **and** `TestCouplingRule.check_file`.
The body of both methods is unchanged — they never use the `tree` argument.

The sections of the file that change are shown below. **Everything else in the file is unchanged — do NOT replace the entire file with this excerpt.** The `...` markers mean "leave the existing code here untouched":

```python
"""Test-coverage rules: test_existence and test_coupling (disabled by default)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from safelint.rules.base import BaseRule


if TYPE_CHECKING:
    import tree_sitter                       # ← was: import ast

    from safelint.rules.base import Violation


class TestExistenceRule(BaseRule):
    ...                                      # class body unchanged
    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:  # noqa: ARG002
        ...                                  # method body unchanged


class TestCouplingRule(BaseRule):
    ...                                      # class body unchanged
    def check_file(self, filepath: str, tree: "tree_sitter.Tree") -> list[Violation]:  # noqa: ARG002
        ...                                  # method body unchanged
```

---

## Phase 6: Rewrite `TaintTracker` (analysis/dataflow.py)

**Estimated time: 3 hours**

This is the most complex change. The old `TaintTracker` subclassed `ast.NodeVisitor`.  
The new one implements manual tree traversal with the same dispatch logic.

**File:** `src/safelint/analysis/dataflow.py`

Replace the **entire file** with:

```python
"""Intra-procedural taint analysis using Tree-sitter.

The :class:`TaintTracker` walks a single function body and tracks which
variables carry data derived from tainted sources (function parameters,
configurable I/O calls). When a tainted value reaches a configurable
dangerous sink the hit is recorded in :attr:`TaintTracker.sink_hits`.

Design goals
------------
* Intra-procedural only — no cross-function call graph needed.
* Assignment propagation: ``x = tainted_y`` makes ``x`` tainted.
* Sanitizer calls clear taint: ``x = escape(tainted_y)`` → ``x`` clean.
* Source calls inject taint: ``x = input()`` → ``x`` tainted.
* f-strings, containers, and arithmetic operators spread taint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages._node_utils import call_name, lineno, node_text, walk
from safelint.languages.python import (
    ANNOTATED_ASSIGNMENT,
    ASSIGNMENT,
    AUGMENTED_ASSIGNMENT,
    BINARY_OPERATOR,
    BOOLEAN_OPERATOR,
    CALL,
    COMPARISON_OPERATOR,
    CONCATENATED_STRING,
    CONDITIONAL_EXPRESSION,
    IDENTIFIER,
    INTERPOLATION,
    LIST,
    SET,
    STRING,
    TUPLE,
    UNARY_OPERATOR,
)

if TYPE_CHECKING:
    import tree_sitter


_SPREADING_TYPES = frozenset({
    BINARY_OPERATOR,
    BOOLEAN_OPERATOR,
    UNARY_OPERATOR,
    COMPARISON_OPERATOR,
    CONDITIONAL_EXPRESSION,
})

_CONTAINER_TYPES = frozenset({LIST, TUPLE, SET})


class TaintTracker:
    """Track tainted variable flow through a function body.

    Instantiate with the set of already-tainted parameter names, the sets of
    sink / sanitizer / source call names, then call ``visit(func_node)``.
    Results are in :attr:`sink_hits` as ``(lineno, var_name, sink_name)`` triples.
    """

    def __init__(
        self,
        params: set[str],
        sinks: frozenset[str],
        sanitizers: frozenset[str],
        sources: frozenset[str],
    ) -> None:
        """Initialise tracker with tainted entry parameters and rule config."""
        self.tainted: set[str] = set(params)
        self.sinks = sinks
        self.sanitizers = sanitizers
        self.sources = sources
        self.sink_hits: list[tuple[int, str, str]] = []

    # ------------------------------------------------------------------
    # Main traversal
    # ------------------------------------------------------------------

    def visit(self, root: "tree_sitter.Node") -> None:
        """Process every node under *root* for taint propagation.

        This replaces ``ast.NodeVisitor.generic_visit`` + the ``visit_*`` pattern.
        Implemented iteratively (explicit stack) to avoid Python's default
        recursion limit of 1 000 frames on deep ASTs — same pattern as
        ``walk()`` and ``NestingDepthRule._max_depth``.
        """
        stack: list["tree_sitter.Node"] = [root]
        while stack:
            node = stack.pop()
            if node.type == ASSIGNMENT:
                self._visit_assignment(node)
            elif node.type == AUGMENTED_ASSIGNMENT:
                self._visit_aug_assignment(node)
            elif node.type == ANNOTATED_ASSIGNMENT:
                self._visit_ann_assignment(node)
            elif node.type == CALL:
                self._visit_call(node)
            stack.extend(reversed(node.children))

    # ------------------------------------------------------------------
    # Assignment visitors
    # ------------------------------------------------------------------

    def _visit_assignment(self, node: "tree_sitter.Node") -> None:
        """Propagate taint through ``x = value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left and right:
            self._update_name(left, is_tainted=self._is_tainted(right))

    def _visit_aug_assignment(self, node: "tree_sitter.Node") -> None:
        """Propagate taint through ``x += value``."""
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left and right and self._is_tainted(right):
            self._update_name(left, is_tainted=True)

    def _visit_ann_assignment(self, node: "tree_sitter.Node") -> None:
        """Propagate taint through ``x: T = value``."""
        # tree-sitter-python grammar field names for annotated_assignment:
        #   "name"  → the variable being annotated (e.g. `x`)
        #   "type"  → the annotation expression (e.g. `int`)
        #   "right" → the optional RHS value (e.g. `input()`)
        # NOTE: the field is "right", NOT "default" — "default" does not exist
        # in this node type and child_by_field_name("default") always returns None,
        # which would silently make this entire method dead code.
        #
        # IMPORTANT: call _update_name unconditionally (passing the bool), NOT inside
        # `if self._is_tainted(value):`. The conditional form only sets taint and never
        # clears it. If `x` was tainted earlier and is reassigned to a clean value
        # (`x: int = escape(user_input)`), the conditional form leaves `x` in the
        # tainted set — producing false positives for every subsequent use of `x`.
        # Compare with _visit_assignment which correctly passes the bool both ways:
        #   self._update_name(left, is_tainted=self._is_tainted(right))
        value = node.child_by_field_name("right")
        if not value:
            return
        if node.named_children:
            target = node.named_children[0]
            self._update_name(target, is_tainted=self._is_tainted(value))

    # ------------------------------------------------------------------
    # Call visitor
    # ------------------------------------------------------------------

    def _visit_call(self, node: "tree_sitter.Node") -> None:
        """Check whether this call reaches a sink with tainted arguments."""
        name = call_name(node)
        if name not in self.sinks:
            return
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return
        for arg in args_node.named_children:
            if self._is_tainted(arg):
                self._record_sink_hit(lineno(node), arg, name)

    def _record_sink_hit(
        self, line_num: int, arg_node: "tree_sitter.Node", sink: str
    ) -> None:
        """Append a hit record for a tainted argument reaching *sink*."""
        arg_name = node_text(arg_node) if arg_node.type == IDENTIFIER else "<expr>"
        self.sink_hits.append((line_num, arg_name, sink))

    # ------------------------------------------------------------------
    # Taint propagation helpers
    # ------------------------------------------------------------------

    def _update_name(
        self, target: "tree_sitter.Node", *, is_tainted: bool
    ) -> None:
        """Add or remove *target* from the tainted set if it is a bare identifier."""
        if target.type != IDENTIFIER:
            return
        name = node_text(target)
        if is_tainted:
            self.tainted.add(name)
        else:
            self.tainted.discard(name)

    def _is_tainted(self, node: "tree_sitter.Node") -> bool:
        """Return True if *node* may carry tainted data."""
        if node.type == IDENTIFIER:
            return node_text(node) in self.tainted
        if node.type == CALL:
            return self._call_tainted(node)
        if node.type == STRING:
            return self._fstring_tainted(node)
        if node.type == CONCATENATED_STRING:
            # Adjacent string / f-string literals: f"{x}" f"{y}"
            # Tree-sitter uses "concatenated_string" for these — NOT "string".
            # Without this branch, taint carried by x or y is silently dropped
            # and eval(f"{user_input}" f" extra") would never fire.
            return any(self._is_tainted(child) for child in node.named_children)
        if node.type in _CONTAINER_TYPES:
            return self._container_tainted(node)
        if node.type in _SPREADING_TYPES:
            return self._spreading_tainted(node)
        return False

    def _call_tainted(self, node: "tree_sitter.Node") -> bool:
        """Return True if this call produces a tainted value."""
        name = call_name(node)
        if name in self.sanitizers:
            return False
        if name in self.sources:
            return True
        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return False
        return any(self._is_tainted(arg) for arg in args_node.named_children)

    def _fstring_tainted(self, node: "tree_sitter.Node") -> bool:
        """Return True if any interpolated expression in an f-string is tainted.

        Tree-sitter represents f-strings as ``string`` nodes containing
        ``interpolation`` children. We only check the expressions inside
        those interpolations — plain string content is never tainted.
        """
        for child in walk(node):
            if child.type == INTERPOLATION:
                for inner in child.named_children:
                    if self._is_tainted(inner):
                        return True
        return False

    def _container_tainted(self, node: "tree_sitter.Node") -> bool:
        """Return True if any element of a list/tuple/set literal is tainted."""
        return any(self._is_tainted(child) for child in node.named_children)

    def _spreading_tainted(self, node: "tree_sitter.Node") -> bool:
        """Return True if any operand of a binary/boolean/etc. expression is tainted.

        Calls ``_is_tainted`` recursively on each named child so that source calls
        inside expressions (e.g. ``clean_var + input()``) are detected.
        Walking and checking only ``IDENTIFIER`` nodes misses ``CALL`` children whose
        return value is tainted (e.g. a configured source function), producing false
        negatives where ``eval(x + input())`` does not fire a sink hit.
        """
        return any(self._is_tainted(child) for child in node.named_children)
```

---

### Step 6.1 — Update `src/safelint/analysis/__init__.py` module docstring

The `__init__.py` for the `analysis` package currently describes itself as using "hybrid AST + dataflow
rules". After Phase 6, the module uses Tree-sitter exclusively. Open the file and replace the module
docstring with:

```python
"""Intra-procedural dataflow analysis using Tree-sitter."""
```

The rest of the file is unchanged:

```python
from safelint.analysis.dataflow import TaintTracker

__all__ = ["TaintTracker"]
```

This is a one-line change. No logic is affected. Skipping it leaves a stale description that
will mislead contributors reading the module for the first time.

Verify the change was applied:

```bash
python -c "import safelint.analysis; print(safelint.analysis.__doc__)"
```

Expected output: `Intra-procedural dataflow analysis using Tree-sitter.`

---

## Phase 7: Update Tests

**Estimated time: 2–3 hours**

> **The Phase 5 prohibition on running tests no longer applies.** Phase 5 said "do NOT run the
> full test suite between individual rule migrations" because unmigrated rules would crash
> immediately. By the time you reach Phase 7, all 12 rule files (Phase 5) and the TaintTracker
> (Phase 6) are fully migrated. Running the test suite now is safe and required.

Run the full test suite first to see what breaks:

```bash
pytest tests/ -v 2>&1 | tee test_output.txt
```

**Which parsing approach to use for new or updated tests:**

> Use the `parse_python` conftest fixture (Pattern A) as the default for any test that calls
> `rule.check_file`. Use a module-level `_parse_python` helper (Pattern D's form) only when you
> need to call a function directly — not via pytest injection — such as `_parse_suppressions`.
> Use `_parse_func` (Pattern F's form) only when you need a `function_definition` node rather
> than the whole tree. Do NOT inline the parser construction inside a test function body when
> writing new tests — Pattern G is a legacy exception for one specific test; it is not the model
> to copy.

**Before fixing any individual failing test, set up `conftest.py` first.**

The `parse_python` fixture is needed by the majority of test files. Tests that use it will fail
with `fixture 'parse_python' not found` — a different error from the `AttributeError` or
`TypeError` they would otherwise produce — until conftest.py is in place. Do this now.

**If `tests/conftest.py` does not exist**, create it with this exact content:

```python
from __future__ import annotations

import pytest
import tree_sitter
import tree_sitter_python

_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


@pytest.fixture
def parse_python():
    """Return a function that parses Python source into a Tree-sitter Tree."""
    def _parse(source: str) -> tree_sitter.Tree:
        parser = tree_sitter.Parser(_PYTHON_LANGUAGE)
        return parser.parse(source.encode("utf-8"))
    return _parse
```

**If `tests/conftest.py` already exists** (it has other fixtures or imports):
- Add `import tree_sitter` and `import tree_sitter_python` into the **existing import block at
  the top of the file** — not after any `@pytest.fixture` definitions. If `import pytest` or
  `from __future__ import annotations` are already present, do NOT add them again (duplicate →
  ruff F811 / E402).
- Before adding `_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())`,
  search the file for `_PYTHON_LANGUAGE`. If it is already defined, **skip this sub-step** —
  adding it again produces ruff F811. Verify the existing value equals
  `tree_sitter.Language(tree_sitter_python.language())`; if it points to something else,
  replace the existing line instead of adding a new one.
- Before adding the `parse_python` fixture, search the file for `def parse_python`. If the
  fixture already exists, **skip this sub-step** — a duplicate fixture causes pytest to use
  the wrong definition silently. Verify the existing fixture returns a `tree_sitter.Tree`
  (not an `ast.AST`); if it returns the wrong type, update the body to match the template
  above rather than adding a second fixture.
- If neither `_PYTHON_LANGUAGE` nor `parse_python` already exists, add them: `_PYTHON_LANGUAGE`
  immediately after the import block, and `parse_python` after all existing fixtures.

> **Naming convention:** `conftest.py` uses `_PYTHON_LANGUAGE` as the module-level language
> constant. Test files that define their own parser (Patterns D, F, G) must also name it
> `_PYTHON_LANGUAGE`, not `_LANG`, so future test authors have one convention to follow.

After updating conftest.py, re-run the test suite to get a clean failure list before working
through the patterns:

```bash
pytest tests/ -v 2>&1 | tee test_output.txt
```

For each failing test, the fix is one of these seven patterns. **Note: some failures appear
as collection `ERROR` entries at the very top of the output — before any test names — rather
than as `FAILED` test names.** A collection error in `test_dataflow.py` (e.g.,
`ImportError: cannot import name '_call_name'`) is NOT a failing test; it is pytest failing
to import the file at all. Map it to Pattern F, not to any entry in the test result list.

**Pattern A — Test calls `rule.check_file(filepath, ast_tree)` directly.**

Old:
```python
import ast
tree = ast.parse(source)
violations = rule.check_file("test.py", tree)
```

New (conceptual illustration — **do NOT paste this block into test files**):
```python
violations = rule.check_file("test.py", parse_python(source))
```

> The `parse_python` fixture was set up in `conftest.py` above. Receive it as a parameter:
> `def test_something(parse_python): tree = parse_python(source) ...`

Then in every test file that used `ast.parse`, replace the import and parse call with the fixture:

```python
# Old
def test_something():
    import ast
    tree = ast.parse("def foo(): ...")
    rule = SomeRule({})
    assert rule.check_file("test.py", tree) == [...]

# New
def test_something(parse_python):
    tree = parse_python("def foo(): ...")
    rule = SomeRule({})
    assert rule.check_file("test.py", tree) == [...]
```

> **Also remove any top-level `import ast` from the file.** After updating test functions to
> use the `parse_python` fixture, a module-level `import ast` at the top of the file becomes
> dead code. Ruff F401 will flag it. Search for `import ast` at the top of the file and delete
> that line. Patterns F and G say this explicitly for their own files; it applies here too.

**Pattern B — Test asserts on `violation.lineno`.**

Line numbers should not change, since Tree-sitter counts lines starting from 0 and we add 1  
(`lineno(node) = node.start_point[0] + 1`). However, if a test is failing on line number,  
verify by printing the Tree-sitter parse result:

```python
for child in tree.root_node.children:
    print(child.type, child.start_point)
```

If the printed line number differs from the test's expected value, **update the assertion to
match the Tree-sitter number** — `lineno(node)` is the new ground truth. The old expected value
was based on `ast` line numbering; if they differ by exactly 1, the most common cause is a
leading blank line in the test source string (e.g. a triple-quoted string that starts with `\n`).
Remove the leading newline from the test string and the numbers will agree. If they differ by
more than 1, re-examine the test source string for extra blank lines or unexpected indentation
before the construct being tested.

**Pattern C — Test mocks or patches `ast` inside the rule under test.**

After Phase 5, no rule imports `ast`. Any test that patches a name from `ast` into a rule or
the engine will fail at **collection time** — not at test time — with:

```
AttributeError: <module 'safelint.core.engine'> does not have the attribute 'ast'
```

This is the same kind of collection error as Pattern F's `ImportError`. It appears at the top
of the pytest output as an `ERROR` entry, not as a `FAILED` test.

**What caused the mock:** The test was controlling what the parser returned — either to simulate
a specific AST structure or to avoid actually parsing source. In Tree-sitter, there is nothing
to mock: the parser runs directly on bytes and is fast enough for test use. Remove the patch
entirely and replace the whole test with real parsing using the `parse_python` fixture
(Pattern A):

```python
# Old — mocking ast to control what gets parsed (raises AttributeError after Phase 4)
with mock.patch("safelint.core.engine.ast") as mock_ast:
    mock_ast.parse.return_value = some_mock_tree
    result = engine.check_file("test.py")
    assert ...

# New — use a real temp file or monkeypatch Path.read_text, then parse normally
def test_something(tmp_path, parse_python):
    source = "def foo(): pass\n"
    f = tmp_path / "test.py"
    f.write_text(source)
    result = engine.check_file(str(f))
    assert ...
```

If the test only checked that violations are returned correctly (not that `ast.parse` was called
a specific number of times), the `mock.patch` can be dropped entirely — just write the source
to a real temp file or use the fixture directly on the rule. If the test was asserting on mock
call counts or mock arguments, those assertions have no equivalent in Tree-sitter and should
be deleted; the behaviour they tested is now covered by the engine's `has_error` path
(Pattern E) or by rule-level tests (Pattern A).

**Pattern D — Test for `_parse_suppressions` or tokenize behaviour.**

The `_parse_suppressions` function now lives in `engine.py` and its signature changed fundamentally:

```python
# Old signature — takes a raw source string
_parse_suppressions(source: str) -> dict[int, set[str] | None]

# New signature — takes a parsed Tree-sitter tree + language constants
_parse_suppressions(tree, comment_node_type: str, comment_prefix: str) -> dict[int, set[str] | None]
```

Every call like `_parse_suppressions("x = 1  # nosafe\n")` raises
`TypeError: missing 2 required positional arguments` after Phase 4.
Rewrite each call by first parsing the source into a tree:

```python
# Old
result = _parse_suppressions("x = 1  # nosafe\n")
```

**First, search ALL test files for every caller of `_parse_suppressions`:**

```bash
grep -rn "_parse_suppressions" tests/
```

Apply the fix below to every file that appears in the output — not only `test_suppression.py`.
If `test_engine.py` or any other file calls `_parse_suppressions`, it needs the same treatment.
Missing even one file leaves a `TypeError: missing 2 required positional arguments` failure that
the checklist's `pytest` run will surface as a confusing error unrelated to Pattern D.

For each file that calls `_parse_suppressions`, add the following helper block. Place `import tree_sitter` and
`import tree_sitter_python` ABOVE any existing `from safelint...` imports already in the
file — third-party imports (Group 2) must come before local imports (Group 3). The blank
line between `import tree_sitter_python` and `from safelint...` is required by isort;
omitting it causes a ruff I001 failure.

> **Import merge warning:** `test_suppression.py` already has
> `from safelint.core.engine import _parse_suppressions`. You must insert
> `from safelint.languages.python import PYTHON` into that same local import group, sorted
> alphabetically by module path. `safelint.core.engine` < `safelint.languages.python`
> alphabetically, so the correct merged order is:
> ```python
> from safelint.core.engine import _parse_suppressions
> from safelint.languages.python import PYTHON
> ```
> Placing `from safelint.languages.python import PYTHON` above
> `from safelint.core.engine import _parse_suppressions` reverses the alphabetical order
> and causes a ruff I001 failure.

Add the following to the **import/module-level section** at the top of `test_suppression.py`
(the imports and module-level definitions below go at the top; the test function stub is for
illustration — do NOT paste it as module-level code):

```python
# ── module-level additions (top of file, above existing safelint imports) ──
import tree_sitter
import tree_sitter_python

from safelint.languages.python import PYTHON

_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


def _parse_python(source: str) -> tree_sitter.Tree:
    return tree_sitter.Parser(_PYTHON_LANGUAGE).parse(source.encode("utf-8"))
```

Then inside each existing test function that called the old `_parse_suppressions`, replace the
old call with the new one. The new call goes **inside the test function body**, not at module level:

```python
# Old call — inside a test function:
result = _parse_suppressions("x = 1  # nosafe\n")

# New call — inside the same test function:
result = _parse_suppressions(
    _parse_python("x = 1  # nosafe\n"),
    PYTHON.comment_node_type,
    PYTHON.comment_prefix,
)
```

**Special case — `test_parse_incomplete_source_returns_empty` must be deleted, not updated.**

```python
# DELETE this test entirely — it tests tokenize-failure behaviour that no longer exists
def test_parse_incomplete_source_returns_empty() -> None:
    assert _parse_suppressions("def foo(\n") == {}
```

The old test asserted that `tokenize` raising on malformed source returned `{}`. Tree-sitter never
raises, so this case no longer exists. Any file with a parse error now returns SAFE000 from the
engine and never reaches `_parse_suppressions` at all. Delete this test; the engine-level behaviour
is already covered by `test_engine_parse_error_returns_parse_violation`.

**Pattern E — Test expects a `SAFE000` violation on a file with a syntax error.**

The old engine called `ast.parse()`, which raised `SyntaxError` on invalid Python, and that exception
was caught and turned into a `SAFE000` violation. Tree-sitter **never raises** — it is error-tolerant
and simply sets `tree.root_node.has_error = True` when the source cannot be parsed cleanly.

**The Phase 4 engine code already handles this correctly.** The `has_error` block in `check_file`
returns a `SAFE000` violation immediately and stops running rules. No changes to `engine.py` are
needed here. You only need to update the test assertions to match the new message string:

```python
# Old test message (will FAIL — message changed)
assert result.violations[0].message == "Parse error: ..."     # old ast message

# New test message (matches Phase 4 engine code)
assert result.violations[0].code == "SAFE000"
assert "tree-sitter" in result.violations[0].message
```

The violation structure (one violation, code `SAFE000`, lineno 0) is preserved exactly.

> **If the old test also asserted `violations[0].lineno`, update it to `0`.** The old
> `ast.parse()` engine caught `SyntaxError`, which carries the actual line number of the
> syntax error. Old tests may have asserted `violations[0].lineno == 5` (or some other
> non-zero value). The new engine always records `lineno=0` for parse errors, regardless
> of where in the file the error occurs. After updating the message assertion, if the test
> still fails on `AssertionError: assert 5 == 0`, that is the cause — update the lineno
> assertion to `0`.

> **Why not just delete these tests?** The parse-error path is a real user-facing contract.
> If someone runs safelint against a file that hasn't been saved yet (mid-edit) they expect
> a clear `SAFE000` rather than a silent pass-with-no-violations. Keep the tests; fix the assertion.

**Pattern F — `test_dataflow.py` — `_call_name` import failure and TaintTracker type mismatch.**

This file has two distinct breakages after Phase 6 and is NOT covered by any earlier pattern.

**Problem 1 — `_call_name` import breaks at file load time.**

The existing import line is:

```python
# Old — raises ImportError after Phase 6: no such name in analysis/dataflow anymore
from safelint.analysis.dataflow import TaintTracker, _call_name
```

**Action: delete that entire line and replace it with these two lines** (do not add them below the old line — remove the old line first):

```python
from safelint.analysis.dataflow import TaintTracker
from safelint.languages._node_utils import call_name, walk
```

> **Important:** Problem 2's `_parse_func` helper also needs `walk` from `_node_utils`. Import
> both `call_name` and `walk` in this single line now so the file never has two separate
> `from safelint.languages._node_utils import ...` lines. Ruff's isort (`I001`) treats split
> imports from the same module as an ordering violation and fails `ruff check src/ tests/`.

`_call_name` moved to `safelint.languages._node_utils` and was renamed `call_name` (no underscore).
The calling convention also changed: old took `call.func` (the sub-node), new takes the full `call` node.

**Search `test_dataflow.py` for every occurrence of `_call_name(` and update each one** — there
will be multiple call sites (for identifier calls, attribute calls, subscript calls, None-return
cases). The pattern below applies globally; do not update only the one example shown:

```python
# Old call (passes the func sub-node — no longer valid)
assert _call_name(call.func) == "foo"

# New call (passes the whole call node)
assert call_name(call_node) == "foo"
```

**Also remove `import ast` from the top of `test_dataflow.py`.**  After Problem 2 replaces every
`ast.parse()` call with `_parse_func()`, the `import ast` line becomes dead code.  Ruff's `F401`
rule (selected via `"F"` in `pyproject.toml`) will flag it as an unused import and fail the
pre-commit hook.  Delete it.

To get a `tree_sitter` call node for these tests, parse the source with the `parse_python` fixture
from `conftest.py` (Pattern A) and walk to the first `call` node:

```python
def test_call_name_from_name_node(parse_python):
    tree = parse_python("foo()")
    call_node = next(n for n in walk(tree.root_node) if n.type == "call")
    assert call_name(call_node) == "foo"
```

**Problem 2 — TaintTracker unit tests pass `ast.FunctionDef` to `tracker.visit()`.**

The old tests did:
```python
tree = ast.parse(src)
func = tree.body[0]          # ast.FunctionDef — has no .children attribute
tracker.visit(func)          # AttributeError in Phase 6 code
```

Replace with Tree-sitter parsing, then pass the `function_definition` node:

**Step 1 — add these lines at the TOP of `test_dataflow.py`, BEFORE the safelint imports from Problem 1.** These are module-level additions only. Do not paste them inside any test function.

Isort ordering (see "Import Ordering Rules") requires:
`stdlib (textwrap) → third-party (tree_sitter, tree_sitter_python) → local (safelint.*)`
Placing these AFTER the `from safelint...` lines causes a ruff I001 failure.

> **NOTE:** add `import textwrap` only if it is not already present in the file.
> If the file already has `import textwrap`, do NOT add a second copy — duplicate import
> triggers ruff F811. `walk` was already imported in the combined line from Problem 1 —
> do NOT add another `from safelint.languages._node_utils import ...` line.

```python
import textwrap  # ← required: _parse_func uses textwrap.dedent
import tree_sitter
import tree_sitter_python

_PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())


def _parse_func(src: str) -> "tree_sitter.Node":
    """Return the first function_definition (or async_function_definition) node in src."""
    tree = tree_sitter.Parser(_PYTHON_LANGUAGE).parse(textwrap.dedent(src).encode("utf-8"))
    # Must match BOTH function_definition and async_function_definition.
    # Using only "function_definition" raises StopIteration for any async def test.
    return next(
        n for n in walk(tree.root_node)
        if n.type in ("function_definition", "async_function_definition")
    )
```

> **Two blank lines before `_parse_func` are required.** Ruff `E302` requires exactly two
> blank lines before every top-level function definition. The code block above includes them.
> If your editor collapses them when pasting, restore the two blank lines manually before
> running `ruff format --check`.

**Step 2 — update every existing `TaintTracker` test in the file** to use `_parse_func` instead of `ast.parse`. The pattern below shows the before/after transformation. Apply it to every test that calls `tracker.visit(func)`:

```python
# Old pattern (raises AttributeError — ast.FunctionDef has no .children)
tree = ast.parse(src)
func = tree.body[0]
tracker.visit(func)

# New pattern — pass a Tree-sitter function_definition node
func = _parse_func(src)
tracker.visit(func)
```

The example below shows a fully updated test. Replace `make_tracker(...)` with whatever
your existing file uses to construct a `TaintTracker` — it is typically a small helper
already defined near the top of `test_dataflow.py` (e.g., `make_tracker(params)` or a
direct `TaintTracker(params, sinks, sanitizers, sources)` call). Do NOT add a new
`make_tracker` function if one already exists, and do NOT hardcode the TaintTracker
constructor if the file already has a helper — the plan cannot know which form your
file uses. Check the file and use whichever form is already there.

```python
def test_tracker_direct_param_to_sink():
    src = """
    def process(user_input):
        eval(user_input)
    """
    func = _parse_func(src)
    tracker = make_tracker({"user_input"})  # ← replace with your file's existing form
    tracker.visit(func)
    assert len(tracker.sink_hits) == 1
    _lineno, var, sink = tracker.sink_hits[0]
    assert var == "user_input"
    assert sink == "eval"
```

Apply the same `_parse_func(src)` / `tracker.visit(func)` replacement to every
`TaintTracker` unit test in the file.

---

**Pattern G — `test_coverage.py` — direct `BaseRule._call_name(call.func)` call with an ast node.**

In `test_coverage.py`, the test `test_base_rule_call_name_returns_none_for_subscript` does:

```python
tree = ast.parse("func_map['key']()")
...
assert rule._call_name(call.func) is None   # call.func is ast.Subscript — no .child_by_field_name
```

After Phase 3, `BaseRule._call_name` delegates to `call_name(call_node)`, which calls
`call_node.child_by_field_name("function")`. An `ast.Subscript` has no such method →
`AttributeError`. This test is NOT caught by Pattern A (which targets `check_file` calls, not
`_call_name`).

Replace with a Tree-sitter parsed subscript call:

```python
def test_base_rule_call_name_returns_none_for_subscript():
    """call_name returns None when the function expression is not identifier or attribute."""
    # NOTE: ruff's isort (I001) applies to ALL import blocks — including those inside
    # function bodies. The ordering below (third-party before local) is required by ruff,
    # not just a convention. Putting `from safelint...` above `import tree_sitter` here
    # would produce a ruff I001 failure exactly as it would at module level.
    import tree_sitter
    import tree_sitter_python

    from safelint.languages._node_utils import call_name, walk

    _PYTHON_LANGUAGE = tree_sitter.Language(tree_sitter_python.language())
    tree = tree_sitter.Parser(_PYTHON_LANGUAGE).parse(b"func_map['key']()")
    # The call node's function child is a subscript, not an identifier or attribute
    call_node = next(n for n in walk(tree.root_node) if n.type == "call")
    assert call_name(call_node) is None
```

Note: the test now directly uses `call_name` from `_node_utils` rather than going through
`rule._call_name`. The behaviour is identical (both delegate to the same function), but
using the module-level function is cleaner for a unit test.

**After replacing the test, remove the top-level `import ast` from the import section at the
top of `tests/test_coverage.py`.** The new test uses local imports inside the function body,
so the module-level `import ast` becomes dead code. Ruff F401 will flag it. Do not search by
line number — the line's position depends on the file's prior state. Search for the literal text
`import ast` and delete that line. The Final Verification Checklist's
`grep -rn "^\s*import ast\b" tests/` will catch it if you forget.

---

## Final Verification Checklist

Run these commands in order. All must pass before the migration is complete.

```bash
# 1. No import of ast or tokenize anywhere in the src/ directory
#    Use the anchored \s* pattern to catch both top-level and indented imports
#    (e.g. `    import ast` inside a TYPE_CHECKING block). The unanchored `^import ast`
#    would silently miss those, giving a false green when test_coverage.py still has
#    its old TYPE_CHECKING block. Step 5.12 explicitly warns about this case.
grep -rn "^\s*import ast\b" src/safelint/
grep -rn "^\s*import tokenize\b" src/safelint/
# Expected: no output from either command

# 1b. Also check tests/ — Patterns D, F, G leave stale top-level `import ast`
#     if the developer only added new imports without removing the old line.
#     The anchored pattern below catches both top-level and indented imports (e.g. inside
#     TYPE_CHECKING blocks) without producing false positives from string literals or
#     comments that mention "import ast" as explanatory text.
grep -rn "^\s*import ast\b" tests/
# Expected: no output

# 2. No import of io (was only used for tokenize's StringIO usage)
grep -r "^import io$" src/safelint/
# Expected: no output

# 3. Full test suite passes
pytest tests/ -v

# 4. Coverage still meets threshold (80%)
pytest tests/ --cov=src --cov-report=term-missing

# 5. Ruff linting passes — run against BOTH src/ and tests/
#    Running only `ruff check src/` misses unused imports left behind in test files
#    (e.g. `import ast` after Pattern D/F/G migrations).
ruff check src/ tests/

# 5b. Ruff formatting passes
#     `ruff check` does NOT check formatting — that is a separate pass.
#     If your pre-commit hook runs `ruff format`, this step must pass before you commit.
#     If it fails, run `ruff format src/ tests/` to auto-fix, then re-run `ruff check`
#     to confirm no new lint issues were introduced by the formatting changes.
ruff format --check src/ tests/

# 6. Type checker passes
ty check

# 7. Run safelint on itself
#    NOTE: this command may print violations (e.g. nesting_depth, function_length,
#    side_effects inside the engine or rule files). That is EXPECTED — these are
#    pre-existing violations that existed before the migration. This step only
#    verifies the tool does not crash. A non-zero exit code from violations alone
#    is NOT a sign of migration failure. A Python traceback IS.
python -m safelint src/safelint/

# 8. Run safelint on the tests directory
python -m safelint tests/
```

---

## Troubleshooting Guide

**"AttributeError: 'NoneType' object has no attribute 'type'"**  
A `child_by_field_name()` call returned `None`. The field name might differ in the installed  
version of `tree-sitter-python`. Debug by printing the node structure:

```python
# WARNING: debugging helper only — NEVER copy this into rule files or production code.
# This function is RECURSIVE. On a real source file it will hit Python's 1000-frame
# recursion limit and crash with RecursionError. Use it ONLY on small, hand-crafted
# test strings (< 20 lines). All production traversal uses walk() — see _node_utils.py.
def print_tree(node, indent=0):
    print("  " * indent + f"{node.type} [{node.start_point}–{node.end_point}]")
    for child in node.children:
        print_tree(child, indent + 1)
```

Run `print_tree(tree.root_node)` on a small example to see the exact field names.

**"body of except_clause not found"**  
The `except_clause` body access uses `child_by_field_name("body")` with a fallback to  
the last named child. If both return None, print the except_clause node children to see  
the exact structure for the installed grammar version.

**"Taint tracker not finding sink hits"**  
The `arguments` field of a `call` node gives an `argument_list` node. Its `named_children`  
are the actual argument expressions. If `named_children` is empty when you expected arguments,  
check that the test code is syntactically valid Python.

**Tests that check suppression comments fail**  
The new `_parse_suppressions` walks the Tree-sitter tree for `comment` nodes. If a `# nosafe`  
comment in a test is inside a string literal, Tree-sitter will NOT produce a comment node for  
it (strings and comments are different node types). This is actually the *correct* behaviour —  
the old tokenize approach had the same guarantee.
