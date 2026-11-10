import logging
import os
import stat

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app import database
from app.db_migrate import migrate


def test_restrict_perms_sqlite_file(tmp_path):
    f = tmp_path / "t.db"
    f.write_text("x")
    bak = tmp_path / "t.db.pre-alembic.bak"
    bak.write_text("x")
    os.chmod(f, 0o644)
    os.chmod(bak, 0o644)
    database._restrict_db_perms(make_url(f"sqlite+aiosqlite:///{f}"))
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(bak).st_mode) == 0o600


@pytest.mark.parametrize("url", ["sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:",
                                 "postgresql+asyncpg://u:p@db/styx"])
def test_restrict_perms_noop(url, monkeypatch):
    calls = []
    monkeypatch.setattr(database.os, "chmod", lambda *a: calls.append(a))
    database._restrict_db_perms(make_url(url))
    assert calls == []


async def test_db_url_password_not_logged(caplog):
    engine = create_async_engine("postgresql+asyncpg://styx:s3cret@127.0.0.1:1/styx")
    caplog.set_level(logging.DEBUG)
    with pytest.raises(Exception) as exc:
        await migrate(engine)
    await engine.dispose()
    assert "s3cret" not in caplog.text
    assert "s3cret" not in str(exc.value)
    assert "127.0.0.1" in caplog.text  # the URL was logged, masked
