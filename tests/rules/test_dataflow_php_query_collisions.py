"""SAFE801: the `query` collisions from #158, and the true positive they shadowed.

Against FreeScout, 0 of 10 SAFE801 findings substantiated the claim that user
input reaches a dangerous sink. Six were the same shape: a zero-argument
`query()` on a php-imap folder object, reported as SQL injection.

#158 proposed two fixes: require a `receiver_sinks` declaration for the
zero-argument receiver branch, and drop the bareword `query` from the default
`sinks_php`. Only the first is applied. All three colliding forms are
zero-argument calls, so the first fix alone silences them, and dropping `query`
would have cost the mysqli / PDO injection pinned at the bottom of this file -
the commonest PHP SQLi there is. These tests hold that reasoning in place: if
the receiver fix ever regresses, the collisions come back here rather than in
someone's repository.
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from safelint.core.config import DEFAULTS, deep_merge
from safelint.core.engine import SafetyEngine


def _safe801(sample: Path) -> list[str]:
    """SAFE801 messages from the SHIPPED defaults, with the rule merely enabled."""
    engine = SafetyEngine(deep_merge(DEFAULTS, {"rules": {"tainted_sink": {"enabled": True}}}))
    return [v.message for v in engine.check_file(str(sample)).violations if v.code == "SAFE801"]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    sample = tmp_path / name
    sample.write_text(textwrap.dedent(body), encoding="utf-8")
    return sample


def test_php_imap_folder_query_is_not_sql(tmp_path: Path) -> None:
    """FreeScout's own line. `$folder` is a php-imap folder; `query()` builds an
    IMAP search, takes no arguments, and has no payload to inject.

    The claimed taint source was `$mailbox`, an Eloquent model loaded from the
    database, tainted only because the PHP tracker seeds every parameter.
    """
    sample = _write(
        tmp_path,
        "imap.php",
        """\
        <?php
        function fetchMessages($mailbox) {
            $folder = $mailbox->getFolder();
            return $folder->query()->unseen()->since(now()->subDays(1))->leaveUnread()->get();
        }
        """,
    )
    assert _safe801(sample) == []


def test_eloquent_query_builder_is_not_sql(tmp_path: Path) -> None:
    """`$model->query()` is Eloquent's parameterised builder, not raw SQL."""
    sample = _write(
        tmp_path,
        "eloquent.php",
        """\
        <?php
        function recent($model) {
            return $model->query()->where('active', 1)->get();
        }
        """,
    )
    assert _safe801(sample) == []


def test_mysqli_query_with_a_concatenated_argument_still_reports(tmp_path: Path) -> None:
    """The true positive that keeping `query` in the defaults preserves.

    This is why #158's first recommendation was not applied: dropping the
    bareword would have made the commonest PHP SQL injection invisible by
    default, to fix false positives the receiver change had already removed.
    """
    sample = _write(
        tmp_path,
        "inject.php",
        """\
        <?php
        function lookup($db) {
            $q = 'SELECT * FROM t WHERE id = '.$_GET['id'];
            $db->query($q);
        }
        """,
    )
    messages = _safe801(sample)
    assert len(messages) == 1
    assert "query" in messages[0]


def test_a_tainted_argument_is_what_distinguishes_them(tmp_path: Path) -> None:
    """Same sink, same receiver, three argument shapes - only the tainted one reports.

    Spelling out the actual discriminator: not the method name, not the
    receiver, but whether user data reaches an argument.
    """
    sample = _write(
        tmp_path,
        "shapes.php",
        """\
        <?php
        function f($db) {
            $db->query();
            $db->query('SELECT 1');
            $db->query($_GET['id']);
        }
        """,
    )
    messages = _safe801(sample)
    assert len(messages) == 1
