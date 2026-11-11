"""login_flow lockout gate fails closed; record_failure survives a broken store."""
import pytest
from sqlmodel import select
from starlette.requests import Request

from app.models import AuditLog
from app.services import abuse_store, login_flow


class _Boom:
    async def _raise(self, *a, **k):
        raise RuntimeError("store down")

    is_locked = device_blocked = throttled = device_fail = record_fail = ip_fail = _raise


@pytest.fixture
def broken_store(monkeypatch):
    monkeypatch.setattr(abuse_store, "get_abuse_store", lambda: _Boom())


@pytest.mark.parametrize("rnd", [None, "rnd-1"])
async def test_blocked_fails_closed(broken_store, rnd):
    assert await login_flow.blocked("u", "1.2.3.4", rnd) is True


@pytest.mark.parametrize("rnd", [None, "rnd-1"])
async def test_locked_fails_closed(broken_store, rnd):
    assert await login_flow.locked("u", "1.2.3.4", rnd) is True


@pytest.mark.parametrize("fn", ["is_locked", "throttled"])
async def test_blocked_fails_closed_per_method(monkeypatch, fn):
    class S:
        async def device_blocked(self, rnd):
            return True

        async def is_locked(self, *a):
            if fn == "is_locked":
                raise RuntimeError
            return False

        async def throttled(self, *a):
            raise RuntimeError

    monkeypatch.setattr(abuse_store, "get_abuse_store", lambda: S())
    assert await login_flow.blocked("u", "1.2.3.4", "r") is True


async def test_record_failure_with_broken_store_still_audits(broken_store, session):
    req = Request({"type": "http", "method": "POST", "path": "/api/auth/login",
                   "headers": [], "client": ("1.2.3.4", 1), "query_string": b""})
    await login_flow.record_failure(session, req, username="u", ip="1.2.3.4",
                                    resolved=True, rnd="r", track_user=True,
                                    action="auth.login_failed")
    rows = (await session.exec(select(AuditLog))).all()
    assert any(r.action == "auth.login_failed" for r in rows)
