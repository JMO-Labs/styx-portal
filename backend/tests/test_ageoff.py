import os
from datetime import datetime, timedelta, timezone

from app.services.ageoff import plan, stale_files

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _touch(p, when, *, atime=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    m = when.timestamp()
    os.utime(p, (atime.timestamp() if atime else m, m))


def test_stale_files_age_rules(tmp_path):
    old = NOW - timedelta(days=100)
    _touch(tmp_path / "old.txt", old)
    _touch(tmp_path / "sub/old2.txt", old)
    _touch(tmp_path / "fresh.txt", NOW - timedelta(days=1))
    _touch(tmp_path / "read.txt", old, atime=NOW - timedelta(days=1))
    assert sorted(stale_files(tmp_path, NOW)) == ["old.txt", "sub/old2.txt"]


def test_stale_files_skips_symlinks_and_cache_dotfiles(tmp_path):
    old = NOW - timedelta(days=100)
    _touch(tmp_path / "real.txt", old)
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    _touch(tmp_path / ".cache/.hidden", old)
    _touch(tmp_path / ".cache/plain", old)
    _touch(tmp_path / ".bashrc", old)
    assert sorted(stale_files(tmp_path, NOW)) == [".bashrc", ".cache/plain", "real.txt"]


def test_plan_none_when_nothing_stale():
    assert plan([], None, NOW).action == "none"


def test_plan_notice_when_no_notice():
    p = plan(["a"], None, NOW)
    assert (p.action, p.files) == ("notice", ["a"])


def test_plan_wait_then_move():
    sent = NOW - timedelta(days=13)
    assert plan(["a"], sent, NOW).action == "wait"
    p = plan(["a"], NOW - timedelta(days=14), NOW)
    assert (p.action, p.files) == ("move", ["a"])


def test_touched_after_notice_dropped(tmp_path):
    old = NOW - timedelta(days=100)
    sent = NOW - timedelta(days=15)
    _touch(tmp_path / "a", old)
    _touch(tmp_path / "b", old)
    _touch(tmp_path / "b", NOW - timedelta(days=5))
    p = plan(["a", "b"], sent, NOW, home=tmp_path)
    assert (p.action, p.files) == ("move", ["a"])
    _touch(tmp_path / "a", NOW - timedelta(days=2))
    assert plan(["a", "b"], sent, NOW, home=tmp_path).action == "none"
