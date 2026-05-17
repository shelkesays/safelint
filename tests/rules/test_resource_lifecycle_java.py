"""Tests for ``resource_lifecycle`` (SAFE401) on Java files.

Java-specific strict-matching tests for the manual ``try { ... } finally { ... }``
form. Try-with-resources and bare-no-guard cases are covered by the broader
integration fixture (``tests/fixtures/spring_boot/ResourceUsage.java`` +
``tests/integration/test_spring_boot_e2e.py``); this file targets the
finally-must-close-the-acquired-variable strictness specifically.
"""

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


def _safe401_codes(violations: list) -> list[str]:
    return [v.code for v in violations if v.code == "SAFE401"]


def test_java_finally_closes_variable_does_not_fire(tmp_path: Path) -> None:
    """``try { in = new FileInputStream(p); } finally { in.close(); }`` is clean."""
    sample = tmp_path / "ManualClose.java"
    sample.write_text(
        "import java.io.FileInputStream;\n"
        "import java.io.IOException;\n"
        "public class ManualClose {\n"
        "    public void read(String path) throws IOException {\n"
        "        FileInputStream in = null;\n"
        "        try {\n"
        "            in = new FileInputStream(path);\n"
        "            in.read();\n"
        "        } finally {\n"
        "            if (in != null) {\n"
        "                in.close();\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
    )
    result = _engine({"rules": {"resource_lifecycle": {"enabled": True}}}).check_file(str(sample))
    assert _safe401_codes(result.violations) == [], "Should not fire when finally closes the acquired variable"


def test_java_finally_does_not_close_variable_fires(tmp_path: Path) -> None:
    """``try { in = new FileInputStream(p); } finally { audit(); }`` fires (reviewer's example).

    The finally block runs *something* but does NOT close the acquired
    resource, so the resource leaks if the try body throws. The strict
    matcher catches this case where the heuristic-only version on JS
    today would silently let it through.
    """
    sample = tmp_path / "NonClosingFinally.java"
    sample.write_text(
        "import java.io.FileInputStream;\n"
        "import java.io.IOException;\n"
        "public class NonClosingFinally {\n"
        "    public void read(String path) throws IOException {\n"
        "        FileInputStream in = null;\n"
        "        try {\n"
        "            in = new FileInputStream(path);\n"
        "            in.read();\n"
        "        } finally {\n"
        "            audit();\n"
        "        }\n"
        "    }\n"
        "    private void audit() {}\n"
        "}\n",
    )
    result = _engine({"rules": {"resource_lifecycle": {"enabled": True}}}).check_file(str(sample))
    assert len(_safe401_codes(result.violations)) == 1, "Should fire once; finally does not close `in`"


def test_java_bare_expression_acquirer_fires(tmp_path: Path) -> None:
    """``try { new FileInputStream(p); } finally { ... }`` fires - no variable, no possible close."""
    sample = tmp_path / "BareExpr.java"
    sample.write_text(
        "import java.io.FileInputStream;\n"
        "import java.io.IOException;\n"
        "public class BareExpr {\n"
        "    public void read(String path) throws IOException {\n"
        "        try {\n"
        "            new FileInputStream(path).read();\n"
        "        } finally {\n"
        "            audit();\n"
        "        }\n"
        "    }\n"
        "    private void audit() {}\n"
        "}\n",
    )
    result = _engine({"rules": {"resource_lifecycle": {"enabled": True}}}).check_file(str(sample))
    assert len(_safe401_codes(result.violations)) == 1, "Bare acquirer can never be closed; must fire"


def test_java_helper_close_pattern_false_positive(tmp_path: Path) -> None:
    """``IOUtils.closeQuietly(in)`` is a known false positive under strict matching.

    This test documents the trade-off: the strict matcher only recognises a
    direct ``<var>.close()`` invocation, so close-helpers like Apache Commons
    IO's ``closeQuietly`` are NOT recognised and SAFE401 fires. Users hitting
    this can either switch to try-with-resources or add ``// nosafe: SAFE401``
    on the acquirer line.

    Removing this assertion would mean the helper pattern silently passes,
    which is the looser behaviour we deliberately moved away from.
    """
    sample = tmp_path / "HelperClose.java"
    sample.write_text(
        "import java.io.FileInputStream;\n"
        "import java.io.IOException;\n"
        "import org.apache.commons.io.IOUtils;\n"
        "public class HelperClose {\n"
        "    public void read(String path) throws IOException {\n"
        "        FileInputStream in = null;\n"
        "        try {\n"
        "            in = new FileInputStream(path);\n"
        "            in.read();\n"
        "        } finally {\n"
        "            IOUtils.closeQuietly(in);\n"
        "        }\n"
        "    }\n"
        "}\n",
    )
    result = _engine({"rules": {"resource_lifecycle": {"enabled": True}}}).check_file(str(sample))
    assert len(_safe401_codes(result.violations)) == 1, (
        "Documented strict-matching trade-off: helper-close patterns are not recognised."
    )
