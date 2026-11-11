import asyncio
from pathlib import Path

import pytest

from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source, raw_exec

PG = "postgresql+asyncpg://u:secretpw@localhost/db"


def test_missing_source_exits_2_no_file(tmp_path, capsys):
    missing = tmp_path / "nope.db"
    assert tool.main(["--source", str(missing), "--target", PG]) == 2
    assert not missing.exists()


def test_non_postgres_target_exits_2(tmp_path):
    src = tmp_path / "s.db"
    src.touch()
    assert tool.main(["--source", str(src), "--target", "sqlite+aiosqlite:///x"]) == 2


def test_target_defaults_to_env(tmp_path, monkeypatch):
    src = tmp_path / "s.db"
    src.touch()
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x")
    assert tool.main(["--source", str(src)]) == 2


def test_modes_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as e:
        tool.main(["--source", "x", "--dry-run", "--verify-only"])
    assert e.value.code == 2


def test_unstamped_source_exits_2_and_hides_password(tmp_path, capsys):
    src = tmp_path / "u.db"
    raw_exec(src, "CREATE TABLE t (x)")
    assert tool.main(["--source", str(src), "--target", PG]) == 2
    out = capsys.readouterr()
    assert "secretpw" not in out.out + out.err


def test_ok_exit_0(tmp_path):
    src = asyncio.run(make_source(tmp_path / "s.db"))
    rc = tool.main(["--source", str(src), "--target", PG])
    assert rc == 0


def test_tools_files_under_500_lines():
    for f in Path(tool.__file__).parent.glob("*.py"):
        assert len(f.read_text().splitlines()) < 500
