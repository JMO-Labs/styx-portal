"""Task B: proxied-service thumbnails (capture_url jail, GET route, capture pass, cleanup)."""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import ProxiedService
from app.services import service_thumbs
from app.services.screenshot import ScreenshotService
from tests import test_services_api as _api

docker_mock = _api.docker_mock
no_route_write = _api.no_route_write
PNG = b"\x89PNG" + b"x" * 50


def _svc(d, page=None):
    context = AsyncMock()
    context.new_page.return_value = page or AsyncMock()
    browser = AsyncMock()
    browser.new_context.return_value = context
    s = ScreenshotService(cache_dir=d, docker_manager=MagicMock())
    s._browser = browser
    s._ensure_browser = AsyncMock()
    return s, browser, context


async def test_capture_url_jails_to_target_and_saves():
    page = AsyncMock()
    page.screenshot.return_value = PNG
    with tempfile.TemporaryDirectory() as d:
        s, browser, context = _svc(d, page)
        got = []

        async def sink(b):
            got.append(b)
        assert await s.capture_url("abc", "http://sonarr.lan:8989/ui", sink) is True
        assert got == [PNG]
        assert not (Path(d) / "svc-abc.png").exists()
        kw = browser.new_context.await_args.kwargs
        assert kw["service_workers"] == "block"
        assert kw["viewport"] == {"width": 1280, "height": 800}
        assert kw["proxy"] == {"server": "http://127.0.0.1:9", "bypass": "sonarr.lan:8989"}
        assert page.goto.await_args.args[0] == "http://sonarr.lan:8989/ui"
        _, handler = context.route.await_args.args
        foreign, own = AsyncMock(), AsyncMock()
        foreign.request.url = "http://docker-proxy:2375/x"
        own.request.url = "http://sonarr.lan:8989/app.js"
        await handler(foreign)
        await handler(own)
        foreign.abort.assert_awaited()
        own.fulfill.assert_awaited()
        context.close.assert_awaited()


async def test_capture_url_default_port_and_failure():
    with tempfile.TemporaryDirectory() as d:
        s, browser, _ = _svc(d)
        s._browser.new_context.side_effect = RuntimeError("boom")
        assert await s.capture_url("x", "https://app.example.com", AsyncMock()) is False
        s2, browser2, _ = _svc(d)
        await s2.capture_url("y", "https://app.example.com", AsyncMock())
        assert browser2.new_context.await_args.kwargs["proxy"]["bypass"] == "app.example.com:443"


async def test_capture_services_pass_skips_disabled(session):
    from app.services.screenshot_url import capture_services_pass
    session.add(ProxiedService(slug="a", name="A", upstream_url="http://10.0.0.2:80/"))
    session.add(ProxiedService(slug="b", name="B", upstream_url="http://10.0.0.3", enabled=False))
    session.add(ProxiedService(slug="c", name="C", kind="docker-local", container="c1",
                               container_port=80))
    await session.commit()
    shots = MagicMock()
    shots.capture_url = AsyncMock(return_value=True)
    await capture_services_pass(session, shots)
    urls = sorted(c.args[1] for c in shots.capture_url.await_args_list)
    assert urls == ["http://10.0.0.2:80", "http://c1:80"]


@pytest.fixture
def thumb_dir(client):
    yield None


async def _mk(session, **kw):
    s = ProxiedService(slug="sonarr", name="S", upstream_url="http://10.0.0.2", **kw)
    session.add(s)
    await session.commit()
    return s


async def test_thumbnail_route_ok_and_404(admin_client, session, thumb_dir):
    s = await _mk(session)
    r = await admin_client.get(f"/api/services/{s.id}/thumbnail")
    assert r.status_code == 404
    await service_thumbs.put(session, s.id, PNG)
    r = await admin_client.get(f"/api/services/{s.id}/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == PNG
    assert (await admin_client.get("/api/services/nope/thumbnail")).status_code == 404


async def test_thumbnail_route_group_acl(member_client, session, thumb_dir):
    s = await _mk(session, allowed_groups=["media"])
    await service_thumbs.put(session, s.id, PNG)
    assert (await member_client.get(f"/api/services/{s.id}/thumbnail")).status_code == 404
    open_s = ProxiedService(slug="open", name="O", upstream_url="http://10.0.0.4")
    session.add(open_s)
    await session.commit()
    await service_thumbs.put(session, open_s.id, PNG)
    assert (await member_client.get(f"/api/services/{open_s.id}/thumbnail")).status_code == 200


async def test_thumbnail_requires_login(client, session, thumb_dir):
    s = await _mk(session)
    assert (await client.get(f"/api/services/{s.id}/thumbnail")).status_code in (401, 403)


async def test_delete_service_removes_thumbnail(admin_client, session, thumb_dir, docker_mock,
                                                no_route_write):
    s = await _mk(session)
    await service_thumbs.put(session, s.id, PNG)
    assert (await admin_client.delete(f"/api/services/{s.id}")).status_code == 204
    assert await service_thumbs.get(session, s.id) is None


async def test_put_get_replace_and_size_cap(session, monkeypatch):
    s = await _mk(session)
    await service_thumbs.put(session, s.id, PNG)
    await service_thumbs.put(session, s.id, PNG + b"2")
    assert await service_thumbs.get(session, s.id) == PNG + b"2"
    monkeypatch.setattr(service_thumbs, "max_bytes", lambda: 10)
    with pytest.raises(service_thumbs.ThumbnailTooLarge):
        await service_thumbs.put(session, s.id, PNG)
    assert await service_thumbs.get(session, s.id) == PNG + b"2"


async def test_write_on_one_replica_served_by_another(session, admin_client, monkeypatch):
    """Replica A's capture pass writes via its own DB session; replica B (empty cache dir) serves it."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.screenshot_url import capture_services_pass
    s = await _mk(session)
    shots = MagicMock()

    async def cap(key, url, on_png):
        await on_png(PNG)
        return True
    shots.capture_url = cap
    async with AsyncSession(session.bind, expire_on_commit=False,
                            join_transaction_mode="create_savepoint") as replica_a:
        await capture_services_pass(replica_a, shots)
    with tempfile.TemporaryDirectory() as empty:
        monkeypatch.setenv("SCREENSHOT_CACHE_DIR", empty)
        r = await admin_client.get(f"/api/services/{s.id}/thumbnail")
        assert r.status_code == 200 and r.content == PNG
        assert list(Path(empty).iterdir()) == []


async def test_put_rolls_back_on_commit_failure():
    sess = MagicMock()
    sess.get = AsyncMock(return_value=None)
    sess.commit = AsyncMock(side_effect=RuntimeError("boom"))
    sess.rollback = AsyncMock()
    with pytest.raises(RuntimeError):
        await service_thumbs.put(sess, "sid", PNG)
    sess.rollback.assert_awaited_once()


async def test_oversize_capture_is_dropped(session, monkeypatch):
    from app.services.screenshot_url import capture_services_pass
    s = await _mk(session)
    monkeypatch.setattr(service_thumbs, "max_bytes", lambda: 10)
    shots = MagicMock()

    async def cap(key, url, on_png):
        await on_png(PNG)
        return True
    shots.capture_url = cap
    await capture_services_pass(session, shots)
    assert await service_thumbs.get(session, s.id) is None
