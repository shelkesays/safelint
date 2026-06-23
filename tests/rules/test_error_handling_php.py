"""Tests for ``empty_except`` (SAFE202) and ``logging_on_error`` (SAFE203) on PHP files.

Both rules are opt-in, so each test enables the rule under test explicitly.

PHP behaviour exercised here:

* PHP ``catch`` always carries a type (there is no bare catch), so SAFE201
  is not registered for PHP and is not tested.
* SAFE202 treats a catch body of nothing, a lone ``;``, comment-only, or a
  bare literal / string statement as empty.
* SAFE203 wants a logging call or a re-raise of the caught error; a fresh
  ``throw new R();`` does not count. In PHP ``throw`` is an expression
  (``expression_statement > throw_expression > variable_name``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    return SafetyEngine(deep_merge(DEFAULTS, overrides or {}))


_EMPTY_EXCEPT = {"rules": {"empty_except": {"enabled": True}}}
_LOGGING = {"rules": {"logging_on_error": {"enabled": True}}}


# ---------------------------------------------------------------------------
# empty_except (SAFE202)
# ---------------------------------------------------------------------------


def test_php_empty_catch_body_fires_safe202(tmp_path: Path) -> None:
    """A catch block with no statements fires SAFE202."""
    sample = tmp_path / "empty.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) {}\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_catch_with_only_empty_statement_fires_safe202(tmp_path: Path) -> None:
    """A catch body of a lone ``;`` fires SAFE202."""
    sample = tmp_path / "semi.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { ; }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_comment_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body holding only a comment fires SAFE202."""
    sample = tmp_path / "comment.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { /* todo */ }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_two_comments_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body holding two comments still has no real work and fires SAFE202."""
    sample = tmp_path / "comments.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { /* a */ /* b */ }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_literal_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body of a bare integer literal statement fires SAFE202."""
    sample = tmp_path / "literal.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { 0; }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_string_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body of a bare string literal statement fires SAFE202."""
    sample = tmp_path / "string.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { 'TODO'; }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert any(v.code == "SAFE202" for v in violations)


def test_php_catch_with_real_handling_is_clean(tmp_path: Path) -> None:
    """A catch block that does real work does not fire SAFE202."""
    sample = tmp_path / "handled.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { error_log($e); }\n", encoding="utf-8")
    violations = _engine(_EMPTY_EXCEPT).check_file(str(sample)).violations
    assert not any(v.code == "SAFE202" for v in violations)


# ---------------------------------------------------------------------------
# logging_on_error (SAFE203)
# ---------------------------------------------------------------------------


def test_php_catch_without_logging_fires_safe203(tmp_path: Path) -> None:
    """A catch block that swallows the error without logging fires SAFE203."""
    sample = tmp_path / "silent.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { $a = 1; }\n", encoding="utf-8")
    violations = _engine(_LOGGING).check_file(str(sample)).violations
    assert any(v.code == "SAFE203" for v in violations)


def test_php_catch_with_fresh_throw_fires_safe203(tmp_path: Path) -> None:
    """A fresh ``throw new R();`` is not a re-raise, so SAFE203 fires."""
    sample = tmp_path / "fresh_throw.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { throw new R(); }\n", encoding="utf-8")
    violations = _engine(_LOGGING).check_file(str(sample)).violations
    assert any(v.code == "SAFE203" for v in violations)


def test_php_catch_with_reraise_is_clean(tmp_path: Path) -> None:
    """``throw $e;`` re-raises the caught error and does not fire SAFE203."""
    sample = tmp_path / "reraise.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { throw $e; }\n", encoding="utf-8")
    violations = _engine(_LOGGING).check_file(str(sample)).violations
    assert not any(v.code == "SAFE203" for v in violations)


def test_php_catch_with_error_log_is_clean(tmp_path: Path) -> None:
    """A catch that calls ``error_log($e)`` satisfies SAFE203."""
    sample = tmp_path / "errorlog.php"
    sample.write_text("<?php\ntry { x(); } catch (\\E $e) { error_log($e); }\n", encoding="utf-8")
    violations = _engine(_LOGGING).check_file(str(sample)).violations
    assert not any(v.code == "SAFE203" for v in violations)


def test_php_catch_with_logger_method_is_clean(tmp_path: Path) -> None:
    """``$log->error($e)`` / ``$log->notice($e)`` satisfy SAFE203."""
    for verb in ("error", "notice"):
        sample = tmp_path / f"logger_{verb}.php"
        sample.write_text(
            f"<?php\ntry {{ x(); }} catch (\\E $e) {{ $log->{verb}($e); }}\n",
            encoding="utf-8",
        )
        violations = _engine(_LOGGING).check_file(str(sample)).violations
        assert not any(v.code == "SAFE203" for v in violations), f"$log->{verb}() should satisfy SAFE203"
