"""Shared cross-framework rules (SAFE905-907) for the Python + PHP presets.

Each rule serves multiple frameworks and is gated purely by ``enabled`` (a
framework preset flips it on), exactly like the Spring 9xx rules. Detection is
language-family aware (Python vs PHP node shapes), not specific-framework aware:
the preset decides *whether* the rule runs, and the rule matches every known
pattern for the file's language. All tree walks are iterative (SAFE105).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages._node_utils import call_name, node_text, resolve_lang_name, walk
from safelint.rules.base import BaseRule


_PY_FUNCTION_TYPES = frozenset({_py.FUNCTION_DEF, _py.ASYNC_FUNCTION_DEF})


if TYPE_CHECKING:
    import tree_sitter

    from safelint.rules.base import Violation


_PY_DEBUG_KWARGS = frozenset({"debug", "reload"})
_PY_DEBUG_ATTR_NAMES = frozenset({"debug", "DEBUG"})
_PHP_STRING_TYPES = frozenset({_php.STRING, _php.ENCAPSED_STRING})


def _py_attr_last_name(attr: tree_sitter.Node) -> str:
    """Return the final identifier of a Python ``attribute`` (``app.debug`` -> ``debug``)."""
    kids = attr.named_children
    return node_text(kids[-1]) if kids else ""


def _py_string_value(node: tree_sitter.Node | None) -> str | None:
    """Return the literal content of a Python ``string`` node, or None if not a string."""
    if node is None or node.type != _py.STRING:
        return None
    return node_text(node).strip("'\"")


# SAFE905: a ``debug=True`` / ``reload=True`` keyword argument only counts on a
# framework app-runner call (``app.run(debug=True)`` / ``uvicorn.run(reload=True)``),
# not on unrelated calls like ``client.connect(debug=True)``.
_PY_DEBUG_RUNNER_CALLS = frozenset({"run"})
# An ``x.debug = True`` attribute assignment only counts when the receiver looks
# like a web-app object (``app`` / ``flask_app`` / ``application``), not
# ``parser.debug`` / ``logger.debug`` etc.
_PY_APP_RECEIVERS = frozenset({"application"})


def _enclosing_call_name(node: tree_sitter.Node) -> str:
    """Return the callee name of the nearest enclosing ``call``, or "" if none."""
    parent = node.parent
    while parent is not None:
        if parent.type == _py.CALL:
            return call_name(parent) or ""
        parent = parent.parent
    return ""


def _inside_class(node: tree_sitter.Node) -> bool:
    """Return True when *node* has a ``class_definition`` ancestor."""
    parent = node.parent
    while parent is not None:
        if parent.type == _py.CLASS_DEF:
            return True
        parent = parent.parent
    return False


def _py_looks_like_app(attr: tree_sitter.Node) -> bool:
    """Return True when an attribute's receiver looks like a web-app object."""
    kids = attr.named_children
    if not kids:
        return False
    receiver = node_text(kids[0]).lower()
    return receiver.endswith("app") or receiver in _PY_APP_RECEIVERS


class DebugModeEnabledRule(BaseRule):
    """Flag a framework debug / reload flag hard-enabled in code (SAFE905).

    Debug mode in production leaks stack traces, settings, and (Flask/Werkzeug)
    an interactive console. Detected patterns:

    * **Python**: ``DEBUG = True`` (Django settings), ``app.debug = True`` /
      ``app.run(debug=True)`` (Flask), ``uvicorn.run(..., reload=True)`` /
      ``debug=True`` (FastAPI/ASGI).
    * **PHP**: a config array entry ``'app.debug' => true`` (Laravel
      ``config([...])``). ``.env`` files are not parsed, so this is code-only -
      a documented limit.

    Serves django / flask / fastapi (python) + laravel (php); default-disabled,
    enabled by those presets.
    """

    name = "debug_mode_enabled"
    code = "SAFE905"
    language = ("python", "php")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Dispatch to the per-language detector for *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "python":
            return self._check_python(filepath, tree)
        if lang == "php":
            return self._check_php(filepath, tree)
        return []  # pragma: no cover - engine dispatch already filters by language tuple

    def _check_python(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            message = self._python_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def _python_hit(self, node: tree_sitter.Node) -> str | None:
        if node.type == _py.ASSIGNMENT:
            return self._python_assignment_hit(node)
        if node.type == _py.KEYWORD_ARGUMENT:
            return self._python_kwarg_hit(node)
        return None

    def _python_assignment_hit(self, node: tree_sitter.Node) -> str | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or right.type != _py.TRUE:
            return None
        if left.type == _py.IDENTIFIER and node_text(left) == "DEBUG":
            return "DEBUG = True - never enable debug mode in production (Django)"
        if left.type == _py.ATTRIBUTE and _py_attr_last_name(left) in _PY_DEBUG_ATTR_NAMES and _py_looks_like_app(left):
            return f"debug mode enabled via {node_text(left)} = True - disable it in production"
        return None

    def _python_kwarg_hit(self, node: tree_sitter.Node) -> str | None:
        kids = node.named_children
        if len(kids) < 2 or kids[1].type != _py.TRUE:
            return None
        # Only a framework app-runner call (``run(...)``) counts, so an unrelated
        # ``client.connect(debug=True)`` is not misread as debug mode.
        if _enclosing_call_name(node) not in _PY_DEBUG_RUNNER_CALLS:
            return None
        name = node_text(kids[0])
        if name in _PY_DEBUG_KWARGS:
            return f"{name}=True enables debug/reload mode - do not enable it in production"
        return None

    def _check_php(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _php.ARRAY_ELEMENT_INITIALIZER:
                continue
            message = self._php_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def _php_hit(self, node: tree_sitter.Node) -> str | None:
        kids = node.named_children
        if len(kids) < 2 or kids[0].type not in _PHP_STRING_TYPES or kids[1].type != _php.BOOLEAN:
            return None
        if node_text(kids[1]).lower() != "true":
            return None
        key = node_text(kids[0]).strip("'\"").lower()
        if key.endswith("debug"):
            return f"config '{key}' => true enables debug mode - disable it in production"
        return None


class MassAssignmentRule(BaseRule):
    """Flag unbounded attribute binding from request data (SAFE906).

    "Bind everything the client sent" defeats the point of an allow-list.
    Detected patterns:

    * **Python (Django)**: a ``ModelForm`` ``Meta.fields = "__all__"``.
    * **Python (Pydantic)**: an input model declaring ``extra = "allow"`` -
      whether as ``class Config: extra = "allow"`` (v1),
      ``model_config = ConfigDict(extra="allow")`` or
      ``model_config = {"extra": "allow"}`` (v2) - which lets a client inject
      arbitrary extra fields.
    * **PHP (Laravel)**: an Eloquent ``$guarded = []`` (guards nothing, so every
      attribute is mass-assignable). ``$fillable`` allow-lists are safe.

    Serves django + pydantic (python) + laravel (php); default-disabled.
    """

    name = "mass_assignment"
    code = "SAFE906"
    language = ("python", "php")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Dispatch to the per-language detector for *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "python":
            return self._check_python(filepath, tree)
        if lang == "php":
            return self._check_php(filepath, tree)
        return []  # pragma: no cover - engine dispatch already filters by language tuple

    def _check_python(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            message = self._python_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    def _python_hit(self, node: tree_sitter.Node) -> str | None:
        if node.type == _py.ASSIGNMENT:
            return self._python_assignment_hit(node)
        if node.type == _py.KEYWORD_ARGUMENT:
            return _mass_assign_kv(node.named_children, "keyword argument")
        if node.type == _py.PAIR:
            return _mass_assign_kv(node.named_children, "dict entry")
        return None

    def _python_assignment_hit(self, node: tree_sitter.Node) -> str | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        # ``fields = "__all__"`` / ``extra = "allow"`` are only mass-assignment
        # signals inside a class body (a ModelForm ``Meta`` / Pydantic model
        # config), not as bare module-level constants.
        if left is None or left.type != _py.IDENTIFIER or not _inside_class(node):
            return None
        name = node_text(left)
        value = _py_string_value(right)
        if name == "fields" and value == "__all__":
            return 'ModelForm fields = "__all__" binds every field - list fields explicitly instead'
        if name == "extra" and value == "allow":
            return 'Pydantic extra = "allow" accepts arbitrary extra input fields - use the default (ignore/forbid)'
        return None

    def _check_php(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type != _php.PROPERTY_ELEMENT:
                continue
            if _php_guarded_empty(node):
                violations.append(
                    self._make_violation_for_node(
                        filepath,
                        node,
                        "Eloquent $guarded = [] guards nothing - every attribute is mass-assignable; use $fillable",
                    )
                )
        return violations


def _mass_assign_kv(kids: list[tree_sitter.Node], shape: str) -> str | None:
    """Return a Pydantic ``extra="allow"`` message for a name/value pair, or None."""
    if len(kids) < 2:
        return None
    key = node_text(kids[0]) if kids[0].type == _py.IDENTIFIER else _py_string_value(kids[0])
    if key == "extra" and _py_string_value(kids[1]) == "allow":
        return f'Pydantic extra="allow" ({shape}) accepts arbitrary extra input fields - use the default'
    return None


def _php_guarded_empty(node: tree_sitter.Node) -> bool:
    """Return True for a ``$guarded = []`` property element (empty array value)."""
    kids = node.named_children
    if len(kids) < 2 or kids[0].type != _php.VARIABLE_NAME:
        return False
    var = node_text(kids[0]).lstrip("$")
    value = kids[1]
    return var == "guarded" and value.type == _php.ARRAY_CREATION_EXPRESSION and not value.named_children


# Whole-object request-data reads (Django ``request.POST`` / DRF ``request.data``
# / Flask ``request.json`` / FastAPI ``Request.query_params``). Single-field
# access (``request.POST.get('x')`` / ``request.POST['x']``) is targeted, not
# "consume the whole body", so it is excluded via the parent-node check below.
_PY_REQUEST_BULK = frozenset({"data", "json", "form", "POST", "GET", "values", "body", "query_params"})
# Presence of any of these in the function marks it as validating - the raw read
# is then assumed intentional and not flagged.
_PY_VALIDATION_CALLS = frozenset({"is_valid", "full_clean", "validate", "model_validate", "parse_obj", "validated_data"})
_PY_VALIDATION_HINTS = ("Serializer", "Schema")
_PHP_BULK_REQUEST_METHODS = frozenset({"all", "input"})


def _php_argc(node: tree_sitter.Node) -> int:
    """Return the number of arguments passed in a PHP call node."""
    args = node.child_by_field_name("arguments")
    return len(args.named_children) if args is not None else 0


def _py_is_request_base(node: tree_sitter.Node) -> bool:
    """Return True when *node* is a ``request`` reference (``request`` or ``self.request``)."""
    if node.type == _py.IDENTIFIER:
        return node_text(node) == "request"
    if node.type == _py.ATTRIBUTE:
        kids = node.named_children
        return bool(kids) and node_text(kids[-1]) == "request"
    return False


def _py_bulk_request_read(node: tree_sitter.Node) -> bool:
    """Return True when *node* is a whole-object bulk request-data read (not a field access)."""
    if node.type != _py.ATTRIBUTE:
        return False
    kids = node.named_children
    if len(kids) < 2 or node_text(kids[-1]) not in _PY_REQUEST_BULK or not _py_is_request_base(kids[0]):
        return False
    parent = node.parent
    # Exclude ``request.POST.get(...)`` / ``request.POST['x']`` - targeted reads.
    return parent is None or parent.type not in (_py.ATTRIBUTE, _py.SUBSCRIPT)


def _py_is_validation(node: tree_sitter.Node) -> bool:
    """Return True when *node* is a validation call or a serializer/schema reference."""
    if node.type == _py.CALL:
        return call_name(node) in _PY_VALIDATION_CALLS
    if node.type == _py.IDENTIFIER:
        return any(hint in node_text(node) for hint in _PY_VALIDATION_HINTS)
    return False


def _php_is_bulk_request_call(node: tree_sitter.Node) -> bool:
    """Return True when *node* is a whole-object request read (``$request->all()`` / bare ``->input()``).

    ``$request->input('field')`` is a *targeted* single-field read, so it is
    excluded - matching the Python side, which excludes ``request.POST.get('x')``.
    Only ``->all()`` and a bare ``->input()`` (no field name) consume the whole body.
    """
    if node.type != _php.MEMBER_CALL_EXPRESSION:
        return False
    obj = node.child_by_field_name("object")
    if obj is None or not node_text(obj).lstrip("$").endswith("request"):
        return False
    method = call_name(node)
    if method == "all":
        return True
    return method == "input" and _php_argc(node) == 0


class UnvalidatedRequestInputRule(BaseRule):
    """Flag request data consumed without a validation layer (SAFE907).

    The cross-framework generalisation of Spring's SAFE903 (``@RequestBody``
    without ``@Valid``) for the non-Java frameworks. Per function / method: a
    whole-object request-data read with no validation in the same scope.

    * **Python**: ``request.POST`` / ``request.data`` / ``request.json`` /
      ``request.form`` / ``request.body`` consumed whole, with no ``is_valid`` /
      ``full_clean`` / ``validate`` / ``model_validate`` call and no
      ``Serializer`` / ``Schema`` reference in the function (Django / Flask /
      FastAPI). Single-field access (``request.POST.get('x')``) is not flagged.
    * **PHP (Laravel)**: ``$request->all()`` / ``$request->input(...)`` with no
      ``$request->validate(...)`` call in the method.

    Conservative + heuristic (a validation call *anywhere* in the scope clears
    the whole function); default-disabled, enabled by the framework presets.
    """

    name = "unvalidated_request_input"
    code = "SAFE907"
    language = ("python", "php")

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Dispatch to the per-language detector for *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "python":
            return self._check(filepath, tree, _PY_FUNCTION_TYPES, self._python_function_hit)
        if lang == "php":
            return self._check(filepath, tree, _php.FUNCTION_TYPES, self._php_function_hit)
        return []  # pragma: no cover - engine dispatch already filters by language tuple

    def _check(self, filepath: str, tree: tree_sitter.Tree, func_types: frozenset[str], analyse) -> list[Violation]:  # noqa: ANN001
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in func_types:
                continue
            hit = analyse(node, func_types)
            if hit is not None:
                message = "request data consumed without a validation layer - validate/deserialise input before use"
                violations.append(self._make_violation_for_node(filepath, hit, message))
        return violations

    def _python_function_hit(self, func: tree_sitter.Node, func_types: frozenset[str]) -> tree_sitter.Node | None:
        raw_read = None
        for node in walk(func, skip_types=tuple(func_types)):
            if raw_read is None and _py_bulk_request_read(node):
                raw_read = node
            elif _py_is_validation(node):
                return None  # a validation signal clears the whole function
        return raw_read

    def _php_function_hit(self, func: tree_sitter.Node, func_types: frozenset[str]) -> tree_sitter.Node | None:
        raw_read = None
        for node in walk(func, skip_types=tuple(func_types)):
            if node.type == _php.MEMBER_CALL_EXPRESSION and call_name(node) == "validate":
                return None
            if raw_read is None and _php_is_bulk_request_call(node):
                raw_read = node
        return raw_read
