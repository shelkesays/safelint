"""Shared cross-framework rules (SAFE905-909) for the Python + PHP presets.

Each rule serves multiple frameworks and is gated purely by ``enabled`` (a
framework preset flips it on), exactly like the Spring 9xx rules. Detection is
language-family aware (Python vs PHP node shapes), not specific-framework aware:
the preset decides *whether* the rule runs, and the rule matches every known
pattern for the file's language. All tree walks are iterative (SAFE105).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core._validators import _validated_string_list, resolve_lang_config_lookup
from safelint.languages import php as _php
from safelint.languages import python as _py
from safelint.languages._node_utils import CALL_TYPES, call_name, node_text, resolve_lang_name, walk
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
    """Return the literal content of a Python ``string`` node, or None if not a string.

    A string prefix (``r`` / ``b`` / ``f`` / ``u``, in any case or combination)
    sits before the opening quote, so drop everything up to the first quote before
    stripping quotes - otherwise an empty prefixed literal like ``r""`` would read
    as the non-empty ``r`` and be mistaken for a real value.
    """
    if node is None or node.type != _py.STRING:
        return None
    text = node_text(node)
    quote_at = next((i for i, ch in enumerate(text) if ch in "'\""), 0)
    return text[quote_at:].strip("'\"")


# SAFE905: a ``debug=True`` / ``reload=True`` keyword argument only counts on a
# framework app-runner call (``app.run(debug=True)`` / ``uvicorn.run(reload=True)``),
# not on unrelated calls like ``client.connect(debug=True)``.
_PY_DEBUG_RUNNER_CALLS = frozenset({"run"})
# An ``x.debug = True`` attribute assignment only counts when the receiver looks
# like a web-app object (``app`` / ``flask_app`` / ``application``), not
# ``parser.debug`` / ``logger.debug`` etc.
_PY_APP_RECEIVERS = frozenset({"application"})
# SAFE906: Pydantic v2 ``model_config = ConfigDict(extra="allow")`` config
# builders. The keyword-argument ``extra="allow"`` form only counts inside one
# of these calls, not on any unrelated call.
_PYDANTIC_CONFIG_CALLS = frozenset({"ConfigDict", "SettingsConfigDict"})


def _enclosing_call_name(node: tree_sitter.Node) -> str:
    """Return the callee name of the nearest enclosing ``call``, or "" if none."""
    parent = node.parent
    while parent is not None:
        if parent.type == _py.CALL:
            return call_name(parent) or ""
        parent = parent.parent
    return ""


def _nearest_class_name(node: tree_sitter.Node) -> str:
    """Return the name of the nearest enclosing ``class_definition``, or "" if none."""
    parent = node.parent
    while parent is not None:
        if parent.type == _py.CLASS_DEF:
            name = parent.child_by_field_name("name")
            return node_text(name) if name is not None else ""
        parent = parent.parent
    return ""


def _inside_model_config_dict(pair: tree_sitter.Node) -> bool:
    """Return True when *pair* is inside a ``model_config = {...}`` dict literal."""
    dictionary = pair.parent
    if dictionary is None or dictionary.type != _py.DICTIONARY:
        return False
    assignment = dictionary.parent
    if assignment is None or assignment.type != _py.ASSIGNMENT:
        return False
    left = assignment.child_by_field_name("left")
    return left is not None and left.type == _py.IDENTIFIER and node_text(left) == "model_config"


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
        # ``extra="allow"`` only counts inside a Pydantic config construct:
        # a ``ConfigDict(...)`` call (keyword arg) or a ``model_config = {...}``
        # dict (pair), not on any unrelated call / dict with the same key.
        if node.type == _py.KEYWORD_ARGUMENT and _enclosing_call_name(node) in _PYDANTIC_CONFIG_CALLS:
            return _mass_assign_kv(node.named_children, "keyword argument")
        if node.type == _py.PAIR and _inside_model_config_dict(node):
            return _mass_assign_kv(node.named_children, "dict entry")
        return None

    def _python_assignment_hit(self, node: tree_sitter.Node) -> str | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or left.type != _py.IDENTIFIER:
            return None
        name = node_text(left)
        value = _py_string_value(right)
        cls = _nearest_class_name(node)
        # ``fields = "__all__"`` is a mass-assignment signal only in a ModelForm /
        # serializer ``class Meta``; ``extra = "allow"`` only in a Pydantic v1
        # ``class Config`` - not as bare constants or in unrelated classes.
        if name == "fields" and value == "__all__" and cls == "Meta":
            return 'ModelForm fields = "__all__" binds every field - list fields explicitly instead'
        if name == "extra" and value == "allow" and cls == "Config":
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
# A concrete validation *call* anywhere in the function marks it as validating -
# the raw read is then assumed intentional and not flagged. A bare reference to a
# ``Serializer`` / ``Schema`` class name is deliberately NOT accepted as proof:
# naming a serializer without calling ``is_valid()`` does not validate anything,
# so treating the name as validation would hide real unvalidated-input findings.
_PY_VALIDATION_CALLS = frozenset({"is_valid", "full_clean", "validate", "model_validate", "parse_obj"})
# PHP (Laravel): ``$request->validate(...)`` is the built-in validating call.
_PHP_VALIDATION_CALLS = frozenset({"validate"})
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


def _php_is_bulk_request_call(node: tree_sitter.Node) -> bool:
    """Return True when *node* is a whole-object request read (``$request->all()`` / bare ``->input()``).

    ``$request->input('field')`` is a *targeted* single-field read, so it is
    excluded - matching the Python side, which excludes ``request.POST.get('x')``.
    Only ``->all()`` and a bare ``->input()`` (no field name) consume the whole body.
    """
    if node.type != _php.MEMBER_CALL_EXPRESSION or not _php_receiver_is_request(node):
        return False
    method = call_name(node)
    if method == "all":
        return True
    return method == "input" and _php_argc(node) == 0


def _php_receiver_is_request(node: tree_sitter.Node) -> bool:
    """Return True when a member call's receiver is THE framework request object.

    Accepts only the two canonical Laravel receivers - ``$request`` (the injected
    ``Request``) and ``$this->request`` (a controller storing it as a property).
    Deliberately NOT matched:

    * a merely request-*suffixed* variable (``$otherrequest``, ``$userRequest``)
      - a different variable, not the request being read;
    * an arbitrary ``*->request`` property chain (``$foo->request``) - ``$foo``
      is some other object whose ``request`` property is not the framework
      request.

    Accepting either would let an unrelated ``validate()`` clear a real
    ``$request->all()`` read it never validated (a security false negative).

    Shared with the bulk-read detector :func:`_php_is_bulk_request_call`, so the
    read and validate sides use ONE receiver notion and cannot drift: applying
    the same canonical-receiver match to both keeps them symmetric (tightening
    only the validate side would instead let a read fire while its own validate
    no longer cleared it).
    """
    obj = node.child_by_field_name("object")
    return obj is not None and _php_text_is_request(node_text(obj))


def _php_text_is_request(text: str) -> bool:
    """Return True when *text* names the framework request (``$request`` / ``$this->request``)."""
    return text.lstrip("$") in ("request", "this->request")


def _php_first_arg_is_request(node: tree_sitter.Node) -> bool:
    """Return True when the call's first argument is the framework request.

    Recognises the Laravel ``ValidatesRequests`` trait form
    ``$this->validate($request, $rules)``, where the request is validated as the
    first *argument* rather than being the receiver. Without this, that stock
    controller idiom - receiver ``$this`` - would not clear the ``$request->all()``
    read and SAFE907 would false-positive on correctly-validated code.

    Only consulted from the ``member_call_expression`` branch of
    :func:`_php_is_validation` (the built-in ``validate`` is a member call:
    ``$request->validate`` / ``$this->validate``). Laravel has no global
    ``validate()`` helper, so the plain-function-call form is deliberately not a
    built-in validator - a project that uses its own global validator adds it to
    ``request_validators_php`` instead.
    """
    args = node.child_by_field_name("arguments")
    if args is None or not args.named_children:
        return False
    return _php_text_is_request(node_text(args.named_children[0]))


def _php_is_validation(node: tree_sitter.Node, configured: frozenset[str]) -> bool:
    """Return True when *node* is a validation call that clears the SAFE907 finding.

    Two forms, deliberately scoped to avoid a security false negative:

    * the **built-in** Laravel validator (``_PHP_VALIDATION_CALLS``) is matched
      only when it actually validates THE request - either as
      ``$request->validate(...)`` (request as receiver) or as the
      ``ValidatesRequests`` trait form ``$this->validate($request, $rules)``
      (request as first argument), in both the plain (``->``) and nullsafe
      (``?->``) member-call forms. A ``validate`` on an unrelated receiver with
      no request argument (``Validator::validate($other)``,
      ``$otherValidator->validate($other)``) does not clear the finding.
    * a **configured** project validator (``request_validators_php``) is matched
      in ANY PHP call form (``call_name`` resolves the bareword across member /
      nullsafe / scoped / plain function calls), so a global helper such as
      ``validate_export_request($req)`` clears - the user opted into that name.
    """
    name = call_name(node)
    if name is None:
        return False
    if name in _PHP_VALIDATION_CALLS and node.type in (_php.MEMBER_CALL_EXPRESSION, _php.NULLSAFE_MEMBER_CALL_EXPRESSION) and (_php_receiver_is_request(node) or _php_first_arg_is_request(node)):
        return True
    return node.type in CALL_TYPES and name in configured


class UnvalidatedRequestInputRule(BaseRule):
    """Flag request data consumed without a validation layer (SAFE907).

    The cross-framework generalisation of Spring's SAFE903 (``@RequestBody``
    without ``@Valid``) for the non-Java frameworks. Per function / method: a
    whole-object request-data read with no validation in the same scope.

    * **Python**: ``request.POST`` / ``request.data`` / ``request.json`` /
      ``request.form`` / ``request.body`` consumed whole, with no concrete
      validation *call* (``is_valid`` / ``full_clean`` / ``validate`` /
      ``model_validate`` / ``parse_obj``) in the function (Django / Flask /
      FastAPI). A bare ``Serializer`` / ``Schema`` name is not accepted as
      validation. Single-field access (``request.POST.get('x')``) is not flagged.
    * **PHP (Laravel)**: ``$request->all()`` / bare ``$request->input()`` with no
      ``$request->validate(...)`` call in the method (``$request->input('field')``
      is a targeted read and is not flagged).

    The validating-call set is extensible: a project that validates request
    input through its own helper (``validate_export_request`` / an allowlist
    filter builder) adds its names to ``request_validators`` (Python, bare key)
    / ``request_validators_php`` (PHP), unioned with the built-ins above - so the
    raw read no longer fires without resorting to a file-level ignore that would
    also hide a genuinely-unvalidated read added later.

    Conservative + heuristic (a validation call *anywhere* in the scope clears
    the whole function); default-disabled, enabled by the framework presets.
    """

    name = "unvalidated_request_input"
    code = "SAFE907"
    language = ("python", "php")

    def _resolve_configured_validators(self, lang_name: str) -> frozenset[str]:
        """Return the configured project-validator names for *lang_name* (built-ins added separately).

        Python uses the bare ``request_validators`` key; PHP uses
        ``request_validators_php`` (the standard per-language suffix convention).
        A mistyped scalar fails loud via :func:`_validated_string_list`, matching
        every other configurable name list.
        """
        raw, error_key = resolve_lang_config_lookup(self.config, "request_validators", lang_name, default=[])
        return frozenset(_validated_string_list(raw, error_key))

    def check_file(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        """Dispatch to the per-language detector for *filepath*."""
        lang = resolve_lang_name(filepath)
        if lang == "python":
            # Python built-ins (``is_valid`` / ``validate`` / ...) match any
            # receiver by name - idiomatic Python validates on a serializer /
            # form object, not on ``request`` - so they union with the config set.
            validators = _PY_VALIDATION_CALLS | self._resolve_configured_validators("python")
            return self._check(filepath, tree, _PY_FUNCTION_TYPES, self._python_function_hit, validators)
        if lang == "php":
            # PHP passes CONFIGURED names only; the built-in ``$request->validate``
            # is matched separately (receiver-scoped) inside ``_php_function_hit``.
            return self._check(filepath, tree, _php.FUNCTION_TYPES, self._php_function_hit, self._resolve_configured_validators("php"))
        return []  # pragma: no cover - engine dispatch already filters by language tuple

    def _check(self, filepath: str, tree: tree_sitter.Tree, func_types: frozenset[str], analyse, validators: frozenset[str]) -> list[Violation]:  # noqa: ANN001
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type not in func_types:
                continue
            hit = analyse(node, func_types, validators)
            if hit is not None:
                message = "request data consumed without a validation layer - validate/deserialise input before use"
                violations.append(self._make_violation_for_node(filepath, hit, message))
        return violations

    def _python_function_hit(self, func: tree_sitter.Node, func_types: frozenset[str], validators: frozenset[str]) -> tree_sitter.Node | None:
        raw_read = None
        for node in walk(func, skip_types=tuple(func_types)):
            if raw_read is None and _py_bulk_request_read(node):
                raw_read = node
            elif node.type == _py.CALL and call_name(node) in validators:
                return None  # a validation signal clears the whole function
        return raw_read

    def _php_function_hit(self, func: tree_sitter.Node, func_types: frozenset[str], configured: frozenset[str]) -> tree_sitter.Node | None:
        raw_read = None
        for node in walk(func, skip_types=tuple(func_types)):
            # The built-in ``validate`` clears only as ``$request->validate(...)``;
            # a configured project validator clears in any call form. See
            # ``_php_is_validation`` for the security rationale.
            if _php_is_validation(node, configured):
                return None
            if raw_read is None and _php_is_bulk_request_call(node):
                raw_read = node
        return raw_read


class CsrfProtectionDisabledRule(BaseRule):
    """Flag CSRF protection explicitly disabled in code (SAFE908).

    CSRF protection is on by default in these frameworks; turning it off in code
    is a deliberate hole an attacker can drive state-changing requests through.
    Detected patterns:

    * **Python (Django)**: a ``@csrf_exempt`` decorator - bare (``@csrf_exempt``),
      called (``@csrf_exempt()``), or wrapped for a class-based view
      (``@method_decorator(csrf_exempt)``).
    * **PHP (Laravel)**: a non-empty ``$except`` property - the
      ``VerifyCsrfToken`` middleware's route allow-list. An empty ``$except = []``
      exempts nothing and is clean.

    Serves django (python) + laravel (php); default-disabled, enabled by those
    presets. More false-positive-prone than SAFE905-907 (a same-named decorator
    or ``$except`` property elsewhere would match), hence off by default.
    """

    name = "csrf_protection_disabled"
    code = "SAFE908"
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
            if node.type == _py.DECORATOR and self._python_exempts_csrf(node):
                message = "@csrf_exempt disables CSRF protection - remove it or scope protection explicitly"
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    @staticmethod
    def _python_exempts_csrf(decorator: tree_sitter.Node) -> bool:
        """Return True if ``csrf_exempt`` is applied as a decorator.

        It counts as a name, a call, or an argument. An unrelated keyword-argument
        NAME that happens to be ``csrf_exempt`` (e.g. ``@foo(csrf_exempt=True)``)
        does not disable CSRF and must not fire.
        """
        for node in walk(decorator):
            if node.type != _py.IDENTIFIER or node_text(node) != "csrf_exempt":
                continue
            parent = node.parent
            is_kwarg_name = parent is not None and parent.type == _py.KEYWORD_ARGUMENT and parent.child_by_field_name("name") == node
            if not is_kwarg_name:
                return True
        return False

    def _check_php(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type == _php.PROPERTY_ELEMENT and self._php_except_nonempty(node):
                message = "$except exempts routes from CSRF protection - keep the allow-list empty or minimal"
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    @staticmethod
    def _php_except_nonempty(element: tree_sitter.Node) -> bool:
        """Return True if *element* is a ``$except`` property initialised to a non-empty array."""
        name = element.child_by_field_name("name")
        if name is None or node_text(name).lstrip("$") != "except":
            return False
        value = element.child_by_field_name("default_value")
        if value is None or value.type != _php.ARRAY_CREATION_EXPRESSION:
            return False
        return any(child.type == _php.ARRAY_ELEMENT_INITIALIZER for child in value.named_children)


class HardcodedSecretRule(BaseRule):
    """Flag a secret key assigned a string literal in code (SAFE909).

    A committed secret is a credential leak the moment it lands in version
    control. Detected patterns:

    * **Python**: ``SECRET_KEY = "..."`` (Django) / ``x.secret_key = "..."``
      (Flask ``app.secret_key``), where the value is a **string literal**.
      Reading from the environment (``SECRET_KEY = os.environ["X"]`` /
      ``= env("X")``) is a call, not a literal, and is clean.
    * **PHP (Laravel)**: a ``'key' => 'base64:...'`` config entry - a hardcoded
      ``APP_KEY`` in ``config/app.php``. Restricted to the ``key`` / ``app_key``
      config value, so an unrelated ``base64:`` literal elsewhere is not flagged.
      ``'key' => env('APP_KEY')`` has no literal and is clean; ``.env`` files are
      not parsed, so this is code-only (a documented limit).

    Serves django / flask (python) + laravel (php); default-disabled, enabled by
    those presets. Off by default because a literal placeholder in an example or
    test settings file can be a false positive.
    """

    name = "hardcoded_secret"
    code = "SAFE909"
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
            if node.type != _py.ASSIGNMENT:
                continue
            message = self._python_secret_hit(node)
            if message is not None:
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    @staticmethod
    def _python_secret_hit(node: tree_sitter.Node) -> str | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or right.type != _py.STRING or not _py_string_value(right):
            return None
        if left.type == _py.IDENTIFIER and node_text(left) == "SECRET_KEY":
            return "SECRET_KEY is a hardcoded string literal - load it from the environment instead"
        if left.type == _py.ATTRIBUTE and _py_attr_last_name(left) == "secret_key":
            return f"{node_text(left)} is a hardcoded secret - load it from the environment instead"
        return None

    def _check_php(self, filepath: str, tree: tree_sitter.Tree) -> list[Violation]:
        violations: list[Violation] = []
        for node in walk(tree.root_node):
            if node.type == _php.ARRAY_ELEMENT_INITIALIZER and self._php_app_key_hit(node):
                message = "hardcoded base64: APP_KEY config value - load it from the environment (env('APP_KEY')) instead"
                violations.append(self._make_violation_for_node(filepath, node, message))
        return violations

    @staticmethod
    def _php_app_key_hit(element: tree_sitter.Node) -> bool:
        """Return True if *element* is a ``'key' => 'base64:...'`` app-key config entry.

        Restricted to the Laravel app-key shape (a ``key`` / ``app_key`` config
        entry whose value is a ``base64:`` literal) so an unrelated ``base64:``
        string elsewhere (a fixture, a ciphertext, ``return "base64:x";``) is not
        misread as a hardcoded secret.
        """
        kids = element.named_children
        if len(kids) < 2 or kids[0].type not in _PHP_STRING_TYPES or kids[1].type not in _PHP_STRING_TYPES:
            return False
        if node_text(kids[0]).strip("'\"").lower() not in ("key", "app_key"):
            return False
        return node_text(kids[1]).strip("'\"").startswith("base64:")
