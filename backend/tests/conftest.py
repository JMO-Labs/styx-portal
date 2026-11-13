import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import asyncio

import pytest
import sqlalchemy
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# noqa: E402 — set environment variables BEFORE importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-long-enough-32-chars")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DEV_CORS", "true")
os.environ.setdefault("RATE_LIMIT_AUTH", "1000/60")
os.environ.setdefault("RATE_LIMIT_DEFAULT", "1000/60")
_test_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("SECRETS_FILE", os.path.join(_test_tmpdir, "secrets.json"))

import yaml  # noqa: E402

# kustomize emits bare `=` (matchType), a YAML 1.1 'value' tag PyYAML can't construct.
yaml.SafeLoader.add_constructor("tag:yaml.org,2002:value", lambda _l, node: node.value)

from app.main import app  # noqa: E402
from tests.helpers_setup import st  # noqa: E402
from tests.gitlab_stub import serve, stub_cert  # noqa: E402,F401 - shared HTTPS stub fixtures
from app.database import get_session  # noqa: E402
from app.routers.instances import get_docker_manager, get_screenshot_service  # noqa: E402


TEST_DB_URL = os.environ.get("STYX_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
IS_PG = TEST_DB_URL.startswith("postgresql")


def pytest_collection_modifyitems(config, items):
    skip = "pg_only" if not IS_PG else "sqlite_only"
    marker = pytest.mark.skip(reason=f"{skip} test on {'postgres' if IS_PG else 'sqlite'}")
    for item in items:
        if skip in item.keywords:
            item.add_marker(marker)


async def _pg_reset_schema(url: str = TEST_DB_URL) -> None:
    """Drop everything in the public schema (tests own the test database)."""
    eng = create_async_engine(url, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(sqlalchemy.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sqlalchemy.text("CREATE SCHEMA public"))
    await eng.dispose()


@pytest.fixture(scope="session")
def _pg_schema():
    """Postgres: build the schema once via Alembic (the real migration path)."""
    if not IS_PG:
        yield
        return
    from app.db_migrate import migrate

    async def build():
        await _pg_reset_schema()
        eng = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        await migrate(eng)
        await eng.dispose()

    asyncio.run(build())
    yield
    asyncio.run(_pg_reset_schema())


@pytest.fixture(name="session")
async def session_fixture(_pg_schema):
    if not IS_PG:
        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async_session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session_factory() as session:
            yield session
        await engine.dispose()
        return
    # Postgres: one outer transaction per test; session commits become savepoints.
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(conn, expire_on_commit=False,
                                join_transaction_mode="create_savepoint") as session:
            yield session
        await outer.rollback()
    await engine.dispose()


# Scratch DB for migration/startup tests: a SQLite file, or a throwaway PG database.
async def _pg_admin(sql: str) -> None:
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(sqlalchemy.text(sql))
    await eng.dispose()


@pytest.fixture
async def scratch_url(tmp_path):
    if not IS_PG:
        yield f"sqlite+aiosqlite:///{tmp_path / 'styx.db'}"
        return
    url = make_url(TEST_DB_URL)
    name = f"{url.database}_scratch"
    await _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await _pg_admin(f'CREATE DATABASE "{name}"')
    yield url.set(database=name).render_as_string(hide_password=False)
    await _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
async def scratch_engine(scratch_url):
    eng = create_async_engine(scratch_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
def _reset_abuse_state():
    from app.services.abuse import fail_tracker, ban_cache, login_lockout
    from app.services.settings_store import settings as _settings_store
    fail_tracker.reset()
    login_lockout.reset()
    ban_cache._bans.clear()
    ban_cache._loaded_at = None
    _settings_store.reset_cache()
    yield


@pytest.fixture(name="client")
async def client_fixture(session):
    from tests import helpers_setup
    helpers_setup.SESSION = session
    async def get_session_override():
        yield session

    def get_docker_manager_override():
        manager = MagicMock()
        manager.create_volume.side_effect = lambda name, size=None: name
        manager.create_container.return_value = "container-abc123"
        manager.get_container_status.return_value = {"status": "running"}
        return manager

    def get_screenshot_service_override():
        # Avoid real ScreenshotService (mkdir of host cache dir + Playwright).
        svc = MagicMock()
        svc.capture = AsyncMock(return_value=True)
        svc.close = AsyncMock()
        return svc

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_docker_manager] = get_docker_manager_override
    app.dependency_overrides[get_screenshot_service] = get_screenshot_service_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def admin_client(client):
    """An AsyncClient that has completed first-run setup and holds admin cookies + CSRF header."""
    r = await client.post("/api/auth/setup", json={**await st(), 
        "username": "admin", "password": "correct horse battery staple"})
    assert r.status_code == 201, r.text
    csrf = client.cookies.get("csrf_token")
    client.headers.update({"X-CSRF-Token": csrf})
    return client


@pytest.fixture
async def member_client(client, session):
    """An AsyncClient for a non-admin member user with auth cookies + CSRF header."""
    from app.models import User
    from app.security.passwords import hash_password
    session.add(User(
        username="member",
        password_hash=hash_password("correct horse battery staple"),
        role="member",
        is_active=True,
    ))
    await session.commit()
    r = await client.post("/api/auth/login", json={
        "username": "member", "password": "correct horse battery staple"})
    assert r.status_code == 200, r.text
    client.headers.update({"X-CSRF-Token": client.cookies.get("csrf_token")})
    return client


@pytest.fixture
async def second_member_client(session):
    """An AsyncClient for a second non-admin member user with auth cookies + CSRF header."""
    from app.models import User
    from app.security.passwords import hash_password

    def get_session_override():
        yield session

    def get_docker_manager_override():
        manager = MagicMock()
        manager.create_volume.side_effect = lambda name, size=None: name
        manager.create_container.return_value = "container-abc123"
        manager.get_container_status.return_value = {"status": "running"}
        return manager

    def get_screenshot_service_override():
        svc = MagicMock()
        svc.capture = AsyncMock(return_value=True)
        svc.close = AsyncMock()
        return svc

    app.dependency_overrides[get_session] = get_session_override
    app.dependency_overrides[get_docker_manager] = get_docker_manager_override
    app.dependency_overrides[get_screenshot_service] = get_screenshot_service_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create the second member user
        session.add(User(
            username="member2",
            password_hash=hash_password("correct horse battery staple"),
            role="member",
            is_active=True,
        ))
        await session.commit()

        # Log in
        r = await client.post("/api/auth/login", json={
            "username": "member2", "password": "correct horse battery staple"})
        assert r.status_code == 200, r.text
        client.headers.update({"X-CSRF-Token": client.cookies.get("csrf_token")})
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_background_favicon(monkeypatch):
    """Service create/mount jobs would otherwise fetch favicons on the app's real DB sessions."""
    monkeypatch.setattr("app.services.service_favicon.schedule_favicon", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_host_interface_trust(monkeypatch):
    """The dev/CI host's own subnets must not leak into proxy-trust tests."""
    from app.middleware import rate_limit
    monkeypatch.setattr(rate_limit, "_startup_networks", ())
    monkeypatch.setattr(rate_limit, "_snapshot_taken", False)
