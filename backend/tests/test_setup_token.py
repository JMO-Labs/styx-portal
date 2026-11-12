import pytest
import asyncio

from app.security import setup_token
from tests.helpers_setup import st

@pytest.fixture
async def engine(scratch_engine):
    from sqlmodel import SQLModel
    async with scratch_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return scratch_engine


PW = "correct horse battery staple"


async def test_setup_requires_token(client):
    r = await client.post("/api/auth/setup", json={"username": "admin", "password": PW})
    assert r.status_code == 422 or r.status_code == 403
    r = await client.post("/api/auth/setup", json={
        "username": "admin", "password": PW, "setup_token": "wrong"})
    assert r.status_code == 403
    assert (await client.get("/api/auth/setup-required")).json()["setup_required"] is True


async def test_setup_with_token_ok_and_token_deleted(client, session):
    r = await client.post("/api/auth/setup", json={"username": "admin", "password": PW, **await st()})
    assert r.status_code == 201, r.text
    assert await setup_token.current_or_none(session) is None


async def test_setup_cross_site_refused(client):
    r = await client.post("/api/auth/setup", json={"username": "admin", "password": PW, **await st()},
                          headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


# Fires concurrent requests through the one shared test session; an asyncpg
# connection cannot run concurrent statements, so this harness only works on SQLite.
@pytest.mark.sqlite_only
async def test_concurrent_setup_creates_one_admin(client, session):
    from sqlmodel import select, func
    from app.models import User
    bodies = [{"username": f"admin{i}", "password": PW, **await st()} for i in range(5)]
    rs = await asyncio.gather(*[client.post("/api/auth/setup", json=b) for b in bodies])
    assert sorted(r.status_code for r in rs).count(201) == 1
    n = (await session.exec(select(func.count()).select_from(User))).one()
    assert n == 1


async def test_announce_clears_stale_token_when_users_exist(session):
    await setup_token.current(session)
    await setup_token.announce(session, False)
    assert await setup_token.current_or_none(session) is None


async def test_announce_creates_token_when_pending(session):
    await setup_token.announce(session, True)
    assert await setup_token.current_or_none(session) is not None


async def test_current_is_stable(session):
    assert await setup_token.current(session) == await setup_token.current(session)


async def test_two_sessions_yield_one_token(engine):
    """Concurrent issuers on separate connections converge on one token."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    async def issue():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            return await setup_token.current(s)

    toks = await asyncio.gather(*[issue() for _ in range(6)])
    assert len(set(toks)) == 1


async def test_consume_is_single_use(engine):
    from sqlmodel.ext.asyncio.session import AsyncSession
    async with AsyncSession(engine, expire_on_commit=False) as a:
        tok = await setup_token.current(a)
    async def use():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            ok = await setup_token.consume(s, tok)
            await s.commit()
            return ok
    res = await asyncio.gather(use(), use())
    assert sorted(res) == [False, True]


async def test_consume_wrong_token_rejected(session):
    await setup_token.current(session)
    assert await setup_token.consume(session, "nope") is False
    assert await setup_token.consume(session, None) is False


def test_legacy_file_migrated(tmp_path, monkeypatch):
    f = tmp_path / "setup-token"
    f.write_text("legacy-token\n")
    monkeypatch.setattr(setup_token, "_legacy_path", lambda: f)
    assert setup_token.take_legacy_file() == "legacy-token"
    assert not f.exists()
    assert setup_token.take_legacy_file() is None


async def test_announce_migrates_legacy_file_into_db(session, tmp_path, monkeypatch):
    f = tmp_path / "setup-token"
    f.write_text("legacy-token\n")
    monkeypatch.setattr(setup_token, "_legacy_path", lambda: f)
    await setup_token.announce(session, True)
    assert await setup_token.current_or_none(session) == "legacy-token"
    assert not f.exists()


async def test_announce_drops_legacy_file_when_users_exist(session, tmp_path, monkeypatch):
    f = tmp_path / "setup-token"
    f.write_text("legacy-token\n")
    monkeypatch.setattr(setup_token, "_legacy_path", lambda: f)
    await setup_token.announce(session, False)
    assert not f.exists()
    assert await setup_token.current_or_none(session) is None
