"""Tests for SAFE908 csrf_protection_disabled (Django + Laravel presets)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


if TYPE_CHECKING:
    from pathlib import Path


def _codes(src: Path) -> list[str]:
    """Run the engine with SAFE908 enabled and return the SAFE908 codes fired on *src*."""
    cfg = deep_merge(DEFAULTS, {"rules": {"csrf_protection_disabled": {"enabled": True}}})
    return [v.code for v in SafetyEngine(cfg).check_file(str(src)).violations if v.code == "SAFE908"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Python (Django)
# ---------------------------------------------------------------------------


def test_python_bare_csrf_exempt(tmp_path: Path) -> None:
    """``@csrf_exempt`` on a view fires."""
    src = _write(tmp_path, "views.py", "@csrf_exempt\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_called_csrf_exempt(tmp_path: Path) -> None:
    """``@csrf_exempt()`` (called form) fires."""
    src = _write(tmp_path, "views.py", "@csrf_exempt()\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_method_decorator_csrf_exempt(tmp_path: Path) -> None:
    """``@method_decorator(csrf_exempt)`` (class-based-view form) fires."""
    src = _write(tmp_path, "views.py", "@method_decorator(csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_unrelated_decorator_is_clean(tmp_path: Path) -> None:
    """An unrelated decorator (``@login_required``) does not fire."""
    src = _write(tmp_path, "views.py", "@login_required\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_kwarg_name_is_clean(tmp_path: Path) -> None:
    """``csrf_exempt`` as an unrelated keyword-argument NAME does not fire -
    ``@foo(csrf_exempt=True)`` configures ``foo``; it does not apply the
    ``csrf_exempt`` decorator."""
    src = _write(tmp_path, "views.py", "@foo(csrf_exempt=True)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_kwarg_value_is_clean(tmp_path: Path) -> None:
    """``csrf_exempt`` as a keyword-argument VALUE does not fire -
    ``@register(handler=csrf_exempt)`` passes the callable to ``register``; it
    does not apply ``@csrf_exempt``. A positional ``method_decorator(csrf_exempt)``
    still fires (covered above)."""
    src = _write(tmp_path, "views.py", "@register(handler=csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_method_decorator_keyword_decorator_fires(tmp_path: Path) -> None:
    """``@method_decorator(decorator=csrf_exempt)`` DOES apply csrf_exempt and fires.

    Unlike an unrelated ``handler=csrf_exempt`` value, ``decorator=`` is the
    ``method_decorator`` argument that actually applies the decorator to a
    class-based view."""
    src = _write(tmp_path, "views.py", "@method_decorator(decorator=csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_method_decorator_keyword_decorator_dotted_fires(tmp_path: Path) -> None:
    """``@method_decorator(decorator=mod.csrf_exempt)`` (dotted value) also fires.

    The ``decorator=`` kwarg is found by walking ancestors, so an intervening
    ``attribute`` node between the identifier and the keyword argument does not
    hide the exemption."""
    src = _write(tmp_path, "views.py", "@method_decorator(decorator=views.csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == ["SAFE908"]


def test_python_unrelated_decorator_keyword_value_is_clean(tmp_path: Path) -> None:
    """``@register(decorator=csrf_exempt)`` on a non-``method_decorator`` call is clean.

    The ``decorator=`` keyword only applies ``csrf_exempt`` when the enclosing
    call is Django's ``method_decorator``. An unrelated function that happens to
    take a ``decorator=`` argument does not disable CSRF, so it must not fire."""
    src = _write(tmp_path, "views.py", "@register(decorator=csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_dotted_kwarg_value_is_clean(tmp_path: Path) -> None:
    """``csrf_exempt`` as a DOTTED unrelated kwarg value does not fire.

    ``@register(handler=mod.csrf_exempt)`` passes the callable to ``register``;
    the intervening ``attribute`` node must not defeat the kwarg-name check."""
    src = _write(tmp_path, "views.py", "@register(handler=mod.csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_nested_call_kwarg_value_is_clean(tmp_path: Path) -> None:
    """``csrf_exempt`` NESTED in a call inside an unrelated kwarg value does not fire.

    ``@register(handler=wrapper(csrf_exempt))`` references the callable but does
    not apply it as a decorator; the intervening ``call`` node must not defeat
    the kwarg-name check."""
    src = _write(tmp_path, "views.py", "@register(handler=wrapper(csrf_exempt))\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_kwarg_name_with_csrf_exempt_value_is_clean(tmp_path: Path) -> None:
    """``@foo(csrf_exempt=csrf_exempt)`` does not fire.

    ``csrf_exempt`` as the kwarg NAME configures ``foo``; a ``csrf_exempt`` in
    that same kwarg's VALUE is inert too and must not fire (the name-branch must
    still scan the value)."""
    src = _write(tmp_path, "views.py", "@foo(csrf_exempt=csrf_exempt)\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_csrf_exempt_kwarg_name_with_nested_csrf_exempt_value_is_clean(tmp_path: Path) -> None:
    """``@foo(csrf_exempt=wrapper(csrf_exempt))`` does not fire - the nested value is inert."""
    src = _write(tmp_path, "views.py", "@foo(csrf_exempt=wrapper(csrf_exempt))\ndef v(request):\n    return None\n")
    assert _codes(src) == []


def test_python_method_decorator_alias_keyword_decorator_fires(tmp_path: Path) -> None:
    """An aliased ``method_decorator`` still applies ``decorator=csrf_exempt`` and fires.

    ``from django.utils.decorators import method_decorator as md`` then
    ``@md(decorator=csrf_exempt)`` genuinely applies the decorator; the alias is
    resolved from the import so the exemption is not missed."""
    src = _write(
        tmp_path,
        "views.py",
        "from django.utils.decorators import method_decorator as md\n@md(decorator=csrf_exempt)\ndef v(request):\n    return None\n",
    )
    assert _codes(src) == ["SAFE908"]


def test_python_function_local_method_decorator_alias_does_not_leak_scope(tmp_path: Path) -> None:
    """A function-local ``method_decorator as md`` import must not affect other scopes.

    Only module-level aliases are collected, so an unrelated ``@md(decorator=csrf_exempt)``
    in a different function (where ``md`` is a locally-defined, non-Django callable) does
    not fire - the local import in ``a`` does not pollute the file-wide alias set."""
    body = (
        "def a():\n"
        "    from django.utils.decorators import method_decorator as md\n"
        "    return md\n"
        "\n"
        "def make():\n"
        "    def md(**kw):\n"
        "        return lambda f: f\n"
        "    @md(decorator=csrf_exempt)\n"
        "    def v(request):\n"
        "        return None\n"
        "    return v\n"
    )
    src = _write(tmp_path, "views.py", body)
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# PHP (Laravel)
# ---------------------------------------------------------------------------


def test_php_nonempty_except_fires(tmp_path: Path) -> None:
    """A non-empty ``$except`` route allow-list fires."""
    src = _write(tmp_path, "VerifyCsrfToken.php", "<?php\nclass VerifyCsrfToken { protected $except = ['stripe/*', 'webhook']; }\n")
    assert _codes(src) == ["SAFE908"]


def test_php_empty_except_is_clean(tmp_path: Path) -> None:
    """An empty ``$except = []`` exempts nothing and does not fire."""
    src = _write(tmp_path, "VerifyCsrfToken.php", "<?php\nclass VerifyCsrfToken { protected $except = []; }\n")
    assert _codes(src) == []


def test_php_unrelated_property_is_clean(tmp_path: Path) -> None:
    """A non-``except`` property initialised to a non-empty array does not fire."""
    src = _write(tmp_path, "M.php", "<?php\nclass M { protected $fillable = ['name', 'email']; }\n")
    assert _codes(src) == []


# ---------------------------------------------------------------------------
# PHP class context (#162): ``$except`` only means CSRF inside VerifyCsrfToken
# ---------------------------------------------------------------------------

_LARAVEL_SCAFFOLD = """<?php
namespace App\\Http\\Middleware;

use Illuminate\\Foundation\\Http\\Middleware\\{base} as Middleware;

class {name} extends Middleware
{{
    protected $except = [{entries}];
}}
"""


def _middleware(tmp_path: Path, name: str, base: str, entries: str) -> Path:
    """Write Laravel's generated middleware shape: a class extending an aliased framework base."""
    body = _LARAVEL_SCAFFOLD.format(name=name, base=base, entries=entries)
    return _write(tmp_path, f"{name}.php", body)


def test_php_scaffolded_verify_csrf_token_fires(tmp_path: Path) -> None:
    """The shape Laravel scaffolds - ``VerifyCsrfToken extends Middleware`` - still fires."""
    src = _middleware(tmp_path, "VerifyCsrfToken", "VerifyCsrfToken", "'stripe/*'")
    assert _codes(src) == ["SAFE908"]


def test_php_trim_strings_except_is_clean(tmp_path: Path) -> None:
    """Laravel's stock ``TrimStrings`` carries an ``$except`` that has nothing to do with CSRF (#162)."""
    src = _middleware(tmp_path, "TrimStrings", "TrimStrings", "'password', 'password_confirmation'")
    assert _codes(src) == []


def test_php_encrypt_cookies_except_is_clean(tmp_path: Path) -> None:
    """``EncryptCookies::$except`` lists cookies left unencrypted, not CSRF-exempt routes (#162)."""
    src = _middleware(tmp_path, "EncryptCookies", "EncryptCookies", "'remember_choice'")
    assert _codes(src) == []


def test_php_renamed_subclass_of_aliased_base_fires(tmp_path: Path) -> None:
    """A differently-named class extending the ``VerifyCsrfToken`` alias is still the CSRF middleware."""
    src = _middleware(tmp_path, "CustomCsrf", "VerifyCsrfToken", "'hooks/*'")
    assert _codes(src) == ["SAFE908"]


def test_php_qualified_extends_fires(tmp_path: Path) -> None:
    """``extends \\Illuminate\\...\\VerifyCsrfToken`` resolves on its final segment."""
    body = "<?php\nclass C extends \\Illuminate\\Foundation\\Http\\Middleware\\VerifyCsrfToken { protected $except = ['a']; }\n"
    assert _codes(_write(tmp_path, "C.php", body)) == ["SAFE908"]


def test_php_except_outside_any_class_is_clean(tmp_path: Path) -> None:
    """A file-scope ``$except`` has no class context at all and cannot be a CSRF allow-list."""
    assert _codes(_write(tmp_path, "boot.php", "<?php\n$except = ['a'];\n")) == []


def test_php_except_in_a_trait_is_clean(tmp_path: Path) -> None:
    """A trait has no ``extends`` clause, so an ``$except`` declared there has no CSRF context.

    Documents the limit of the class-context check: a trait mixed into
    ``VerifyCsrfToken`` is not followed. Reporting every trait ``$except`` is the
    false positive #162 is about, so the quiet side is the right default.
    """
    body = "<?php\ntrait HasExceptions { protected $except = ['a']; }\n"
    assert _codes(_write(tmp_path, "HasExceptions.php", body)) == []


def test_php_unrelated_middleware_without_extends_is_clean(tmp_path: Path) -> None:
    """A standalone class named neither ``VerifyCsrfToken`` nor extending it does not fire."""
    body = "<?php\nclass ThrottleRequests { protected $except = ['api/*']; }\n"
    assert _codes(_write(tmp_path, "ThrottleRequests.php", body)) == []


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_disabled_by_default(tmp_path: Path) -> None:
    """With the rule at its default (disabled), nothing fires even on @csrf_exempt."""
    src = _write(tmp_path, "views.py", "@csrf_exempt\ndef v(request):\n    return None\n")
    assert [v.code for v in SafetyEngine(DEFAULTS).check_file(str(src)).violations if v.code == "SAFE908"] == []
