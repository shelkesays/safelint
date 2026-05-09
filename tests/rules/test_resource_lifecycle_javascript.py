"""Tests for ``resource_lifecycle`` (SAFE401) on JavaScript files."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _engine(overrides: dict | None = None) -> SafetyEngine:
    """SafetyEngine with optional config overrides merged on top of DEFAULTS."""
    config = deep_merge(DEFAULTS, overrides or {})
    return SafetyEngine(config)


# ---------------------------------------------------------------------------
# Acquirer calls outside any try/finally fire.
# ---------------------------------------------------------------------------


def test_js_create_read_stream_outside_try_finally_fires(tmp_path: Path) -> None:
    """``fs.createReadStream(...)`` called bare in a function body fires SAFE401."""
    sample = tmp_path / "stream.js"
    sample.write_text(
        "function readData(path) {\n  const stream = fs.createReadStream(path);\n  return processStream(stream);\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe401 = [v for v in result.violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "createReadStream" in safe401[0].message


def test_js_create_write_stream_outside_try_finally_fires(tmp_path: Path) -> None:
    """``fs.createWriteStream(...)`` outside try/finally fires."""
    sample = tmp_path / "write.js"
    sample.write_text(
        "function writeData(path, data) {\n"
        "  const stream = fs.createWriteStream(path);\n"
        "  stream.write(data);\n"
        "  stream.end();\n"  # explicit cleanup, but rule is strict — no try/finally
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_create_server_outside_try_finally_fires(tmp_path: Path) -> None:
    """``http.createServer(...)`` outside try/finally fires."""
    sample = tmp_path / "server.js"
    sample.write_text(
        "function startServer(port) {\n  const server = http.createServer(handler);\n  server.listen(port);\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_open_sync_outside_try_finally_fires(tmp_path: Path) -> None:
    """``fs.openSync(...)`` (raw fd) outside try/finally fires."""
    sample = tmp_path / "fd.js"
    sample.write_text(
        "function readFD(path) {\n"
        "  const fd = fs.openSync(path, 'r');\n"
        "  return fd;\n"  # no cleanup at all
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


# ---------------------------------------------------------------------------
# Acquirer calls inside try/finally do not fire.
# ---------------------------------------------------------------------------


def test_js_create_read_stream_inside_try_finally_does_not_fire(tmp_path: Path) -> None:
    """Wrapped in ``try { ... } finally { ... }`` — clean."""
    sample = tmp_path / "wrapped.js"
    sample.write_text(
        "function readData(path) {\n  let stream;\n  try {\n    stream = fs.createReadStream(path);\n    return processStream(stream);\n  } finally {\n    if (stream) stream.close();\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


def test_js_nested_try_finally_around_call_does_not_fire(tmp_path: Path) -> None:
    """An outer try/finally also counts when the call is nested inside."""
    sample = tmp_path / "nested_try.js"
    sample.write_text(
        "function readData(path) {\n  try {\n    if (path) {\n      const stream = fs.createReadStream(path);\n      return processStream(stream);\n    }\n  } finally {\n    cleanup();\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


# ---------------------------------------------------------------------------
# Acquirer calls inside try-without-finally fire.
# ---------------------------------------------------------------------------


def test_js_try_with_only_catch_no_finally_fires(tmp_path: Path) -> None:
    """``try { stream = ... } catch { }`` (no finally) doesn't satisfy the rule."""
    sample = tmp_path / "try_catch.js"
    sample.write_text(
        "function readData(path) {\n  try {\n    const stream = fs.createReadStream(path);\n    return processStream(stream);\n  } catch (e) {\n    console.error(e);\n  }\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_clean_function_does_not_fire(tmp_path: Path) -> None:
    """A function with no acquirer calls is clean."""
    sample = tmp_path / "clean.js"
    sample.write_text(
        "function add(a, b) { return a + b; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


def test_js_unrelated_function_call_does_not_fire(tmp_path: Path) -> None:
    """Calls to functions NOT in the tracked list don't fire."""
    sample = tmp_path / "unrelated.js"
    sample.write_text(
        "function f(path) { const data = JSON.parse(path); return data; }\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


def test_js_user_can_extend_tracked_list(tmp_path: Path) -> None:
    """``tracked_functions_javascript`` is config-overridable."""
    sample = tmp_path / "custom.js"
    sample.write_text(
        "function f() { const handle = acquireHandle(); return handle; }\n",
        encoding="utf-8",
    )
    # Default: ``acquireHandle`` not tracked — no fire.
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)

    # With override: fires.
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"resource_lifecycle": {"tracked_functions_javascript": ["acquireHandle"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_acquirer_in_nested_function_does_not_inherit_outer_try_finally(tmp_path: Path) -> None:
    """A resource acquirer in a nested function isn't guarded by the OUTER function's try/finally.

    The outer ``finally`` runs when the outer function returns —
    not when ``setTimeout`` (or any other deferred caller) eventually
    invokes the nested function. The inner stream needs its own
    ``try/finally`` (or its own ``using`` declaration) to be safe.
    Without the function-boundary check in ``_is_inside_try_finally``
    this case would silently slip past SAFE401.
    """
    sample = tmp_path / "nested_callback.js"
    sample.write_text(
        "function outer() {\n"
        "  try {\n"
        "    setTimeout(function callback() {\n"
        "      const stream = fs.createReadStream(path);\n"  # NOT guarded by outer finally
        "      return processStream(stream);\n"
        "    }, 1000);\n"
        "  } finally {\n"
        "    cleanup();\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_acquirer_in_nested_arrow_does_not_inherit_outer_try_finally(tmp_path: Path) -> None:
    """Same scope-leak hazard as the previous test, but with an arrow function."""
    sample = tmp_path / "nested_arrow.js"
    sample.write_text(
        "function outer() {\n"
        "  try {\n"
        "    const handler = () => {\n"
        "      const stream = fs.createReadStream(path);\n"
        "      return processStream(stream);\n"
        "    };\n"
        "    queue.push(handler);\n"
        "  } finally {\n"
        "    cleanup();\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_connect_call_outside_try_finally_fires(tmp_path: Path) -> None:
    """DB / socket ``connect(...)`` calls fire when not in try/finally."""
    sample = tmp_path / "connect.js"
    sample.write_text(
        "function loadFromDB() {\n  const db = connect('postgres://...');\n  return db.query('select 1');\n}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_new_worker_outside_try_finally_fires(tmp_path: Path) -> None:
    """``new Worker(...)`` (constructor invocation) must also fire SAFE401.

    Regression guard: the runtime presets populate
    ``tracked_functions_javascript`` with constructor names
    (``Worker``, ``WebSocket``, ``MutationObserver``, ...) — invoked
    via ``new`` rather than as plain calls. A call-only walk would
    silently miss every browser preset entry.
    """
    sample = tmp_path / "new_worker.js"
    sample.write_text(
        "function start() {\n  const w = new Worker('worker.js');\n  return w;\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"resource_lifecycle": {"tracked_functions_javascript": ["Worker"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    safe401 = [v for v in result.violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "Worker" in safe401[0].message


def test_js_new_member_constructor_fires(tmp_path: Path) -> None:
    """``new fs.WriteStream(...)`` — ``call_name`` resolves member_expression constructors."""
    sample = tmp_path / "new_member.js"
    sample.write_text(
        "function start() {\n  const s = new fs.WriteStream(path);\n  return s;\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"resource_lifecycle": {"tracked_functions_javascript": ["WriteStream"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert any(v.code == "SAFE401" for v in result.violations)


def test_js_new_inside_try_finally_does_not_fire(tmp_path: Path) -> None:
    """Constructor wrapped in try/finally is correctly recognised as guarded."""
    sample = tmp_path / "new_wrapped.js"
    sample.write_text(
        "function start() {\n  let w;\n  try {\n    w = new Worker('worker.js');\n    return work(w);\n  } finally {\n    if (w) w.terminate();\n  }\n}\n",
        encoding="utf-8",
    )
    cfg = deep_merge(
        DEFAULTS,
        {"rules": {"resource_lifecycle": {"tracked_functions_javascript": ["Worker"]}}},
    )
    result = SafetyEngine(cfg).check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


def test_js_acquirer_inside_finally_block_fires(tmp_path: Path) -> None:
    """A resource acquired inside a ``finally { ... }`` is NOT guarded.

    Walking up the parent chain naively reaches the same try_statement
    whose ``finally`` is the *enclosing* block — so without the
    finally-self check, ``try { ... } finally { fs.createReadStream(...) }``
    would be silently accepted. There's no subsequent finally to
    guarantee the cleanup of THIS resource, so the rule must fire.
    """
    sample = tmp_path / "in_finally.js"
    sample.write_text(
        "function f(path) {\n"
        "  try {\n"
        "    work();\n"
        "  } finally {\n"
        "    const stream = fs.createReadStream(path);\n"  # acquired in finally → unguarded
        "    processStream(stream);\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    safe401 = [v for v in result.violations if v.code == "SAFE401"]
    assert len(safe401) == 1
    assert "createReadStream" in safe401[0].message


def test_js_acquirer_inside_outer_finally_with_inner_try_finally_does_not_fire(tmp_path: Path) -> None:
    """An acquirer in an outer finally is fine if it has its own try/finally.

    The outer ``finally`` doesn't guard *itself*, but the inner
    ``try { acquire() } finally { close() }`` inside the outer finally
    does — so this case must be clean.
    """
    sample = tmp_path / "nested_finally_safe.js"
    sample.write_text(
        "function f(path) {\n"
        "  try {\n"
        "    work();\n"
        "  } finally {\n"
        "    let stream;\n"
        "    try {\n"
        "      stream = fs.createReadStream(path);\n"
        "      processStream(stream);\n"
        "    } finally {\n"
        "      if (stream) stream.close();\n"
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)


def test_js_acquirer_inside_catch_block_remains_guarded(tmp_path: Path) -> None:
    """An acquirer in ``catch (e) { ... }`` IS guarded by the same try's finally.

    The finally clause runs after the catch handler, so resources opened
    in the catch arm are cleaned up by the same try's finally. This is
    the positive control for the finally-self check — only the finally
    arm itself is excluded; catch arms remain guarded.
    """
    sample = tmp_path / "in_catch_guarded.js"
    sample.write_text(
        "function f(path) {\n"
        "  try {\n"
        "    work();\n"
        "  } catch (e) {\n"
        "    const stream = fs.createReadStream(path);\n"  # in catch → finally runs after
        "    processStream(stream);\n"
        "  } finally {\n"
        "    cleanup();\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = _engine().check_file(str(sample))
    assert not any(v.code == "SAFE401" for v in result.violations)
