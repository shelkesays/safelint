"""Error-handling rules (SAFE201 / SAFE202 / SAFE203) on C++ files.

C++-specific behaviour:

* SAFE201 (bare_except) fires on the ``catch (...)`` catch-all - its first
  non-Python home. A typed ``catch (const E& e)`` is clean.
* SAFE202 (empty_except) fires on ``catch (...) {}`` and comment-only bodies.
* SAFE203 (logging_on_error) treats a ``std::cerr << ...`` stream insertion as
  logging and a bare ``throw;`` / ``throw e;`` as a re-raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS
from safelint.core.engine import SafetyEngine


def _codes(src: str, tmp_path: Path) -> set[str]:
    """Return violation codes for *src* written as a ``.cpp`` file."""
    sample = tmp_path / "sample.cpp"
    sample.write_text(src, encoding="utf-8")
    return {v.code for v in SafetyEngine(DEFAULTS).check_file(str(sample)).violations}


def test_cpp_catch_all_fires_safe201(tmp_path: Path) -> None:
    """A ``catch (...)`` catch-all fires SAFE201."""
    src = 'void f() {\n    try { g(); } catch (...) { std::cerr << "e"; }\n}\n'
    assert "SAFE201" in _codes(src, tmp_path)


def test_cpp_typed_catch_is_clean_for_safe201(tmp_path: Path) -> None:
    """A typed ``catch (const E& e)`` does not fire SAFE201."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { std::cerr << e.what(); }\n}\n"
    assert "SAFE201" not in _codes(src, tmp_path)


def test_cpp_empty_catch_fires_safe202(tmp_path: Path) -> None:
    """An empty ``catch (const E& e) {}`` body fires SAFE202."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { }\n}\n"
    assert "SAFE202" in _codes(src, tmp_path)


def test_cpp_comment_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A comment-only catch body fires SAFE202."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { /* todo */ }\n}\n"
    assert "SAFE202" in _codes(src, tmp_path)


def test_cpp_string_literal_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body that is just a ``"TODO"`` string literal is a no-op (SAFE202)."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { "TODO"; }\n}\n'
    assert "SAFE202" in _codes(src, tmp_path)


def test_cpp_numeric_literal_only_catch_fires_safe202(tmp_path: Path) -> None:
    """A catch body that is just a ``0;`` literal is a no-op (SAFE202)."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { 0; }\n}\n"
    assert "SAFE202" in _codes(src, tmp_path)


def test_cpp_swallowing_catch_fires_safe203(tmp_path: Path) -> None:
    """A catch that cleans up without logging fires SAFE203."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { cleanup(); }\n}\n"
    assert "SAFE203" in _codes(src, tmp_path)


def test_cpp_cerr_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """A ``std::cerr << ...`` in the catch counts as logging - no SAFE203."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { std::cerr << e.what() << "\\n"; }\n}\n'
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_bare_rethrow_is_clean_for_safe203(tmp_path: Path) -> None:
    """A bare ``throw;`` re-raise is not a swallow - no SAFE203."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { throw; }\n}\n"
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_spdlog_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """A qualified ``spdlog::error(...)`` call resolves to ``error`` and counts as logging."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { spdlog::error("bad"); }\n}\n'
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_unqualified_cerr_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """An unqualified ``cerr << ...`` (via ``using std::cerr``) also counts as logging."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { cerr << e.what(); }\n}\n"
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_rethrow_of_binding_is_clean_for_safe203(tmp_path: Path) -> None:
    """A ``throw e;`` that re-raises the exact caught binding is not a swallow."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { throw e; }\n}\n"
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_throwing_fresh_exception_without_log_fires_safe203(tmp_path: Path) -> None:
    """Throwing a *new* exception (not the caught binding) is not a re-raise - logging is still required."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { throw std::runtime_error("bad"); }\n}\n'
    assert "SAFE203" in _codes(src, tmp_path)


def test_cpp_fprintf_stderr_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """A `fprintf(stderr, ...)` in the catch counts as logging - no SAFE203."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { fprintf(stderr, "error: %s\\n", e.what()); }\n}\n'
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_perror_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """A `perror(...)` in the catch counts as logging (it always writes to stderr) - no SAFE203."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { perror("operation failed"); }\n}\n'
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_fprintf_to_non_stderr_still_fires_safe203(tmp_path: Path) -> None:
    """A `fprintf(logfile, ...)` to a non-stderr stream is not error logging - SAFE203 still fires."""
    src = 'void f() {\n    try { g(); } catch (const std::exception& e) { fprintf(logfile, "%s", e.what()); }\n}\n'
    assert "SAFE203" in _codes(src, tmp_path)


def test_cpp_fputs_to_stderr_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """`fputs(msg, stderr)` logs to stderr (stream is the *second* arg) - no SAFE203."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { fputs(e.what(), stderr); }\n}\n"
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_fwrite_to_stderr_logging_catch_is_clean_for_safe203(tmp_path: Path) -> None:
    """`fwrite(..., stderr)` logs to stderr (stream is the *fourth* arg) - no SAFE203."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { fwrite(e.what(), 1, 4, stderr); }\n}\n"
    assert "SAFE203" not in _codes(src, tmp_path)


def test_cpp_fputs_to_non_stderr_still_fires_safe203(tmp_path: Path) -> None:
    """`fputs(msg, logfile)` to a non-stderr stream is not error logging - SAFE203 still fires."""
    src = "void f() {\n    try { g(); } catch (const std::exception& e) { fputs(e.what(), logfile); }\n}\n"
    assert "SAFE203" in _codes(src, tmp_path)
