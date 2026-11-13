from datetime import datetime, timedelta, timezone

import pytest

A = "/api/admin/announcements"


def _iso(delta_h: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=delta_h)).isoformat()


def _body(**kw):
    return {"title": "Hello", "body": "World", "kind": "info",
            "starts_at": _iso(-1), **kw}


@pytest.mark.asyncio
async def test_admin_crud(admin_client):
    r = await admin_client.post(A, json=_body())
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["created_by"]
    assert r.json()["ends_at"] is None
    assert [a["id"] for a in (await admin_client.get(A)).json()] == [aid]
    r = await admin_client.patch(f"{A}/{aid}", json={"title": "New", "kind": "maintenance"})
    assert r.status_code == 200
    assert r.json()["title"] == "New" and r.json()["kind"] == "maintenance"
    assert (await admin_client.delete(f"{A}/{aid}")).status_code == 204
    assert (await admin_client.get(A)).json() == []
    assert (await admin_client.delete(f"{A}/{aid}")).status_code == 404
    assert (await admin_client.patch(f"{A}/{aid}", json={"title": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_validation(admin_client):
    assert (await admin_client.post(A, json=_body(title="x" * 121))).status_code == 422
    assert (await admin_client.post(A, json=_body(body="x" * 2001))).status_code == 422
    assert (await admin_client.post(A, json=_body(title=""))).status_code == 422
    assert (await admin_client.post(A, json=_body(kind="bogus"))).status_code == 422
    ok = await admin_client.post(A, json=_body(title="x" * 120, body="x" * 2000))
    assert ok.status_code == 201
    r = await admin_client.post(A, json=_body(ends_at=_iso(-2)))
    assert r.status_code == 422
    r = await admin_client.patch(f"{A}/{ok.json()['id']}", json={"title": "x" * 121})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_active_window_and_order(admin_client):
    await admin_client.post(A, json=_body(title="info-now"))
    await admin_client.post(A, json=_body(title="maint", kind="maintenance"))
    await admin_client.post(A, json=_body(title="future", starts_at=_iso(1)))
    await admin_client.post(A, json=_body(title="expired", starts_at=_iso(-3), ends_at=_iso(-1)))
    await admin_client.post(A, json=_body(title="bounded", ends_at=_iso(2)))
    r = await admin_client.get("/api/announcements/active")
    assert r.status_code == 200
    titles = [a["title"] for a in r.json()]
    assert titles[0] == "maint"
    assert set(titles) == {"maint", "info-now", "bounded"}


@pytest.mark.asyncio
async def test_member_forbidden_admin_but_reads_active(member_client):
    assert (await member_client.get(A)).status_code == 403
    assert (await member_client.post(A, json=_body())).status_code == 403
    assert (await member_client.patch(f"{A}/x", json={"title": "x"})).status_code == 403
    assert (await member_client.delete(f"{A}/x")).status_code == 403
    r = await member_client.get("/api/announcements/active")
    assert r.status_code == 200 and r.json() == []


@pytest.mark.asyncio
async def test_active_requires_login(client):
    assert (await client.get("/api/announcements/active")).status_code == 401


@pytest.mark.asyncio
async def test_naive_datetimes_pass_through(admin_client):
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    r = await admin_client.post(A, json=_body(starts_at=start.isoformat()))
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_patch_null_field_is_ignored(admin_client):
    r = await admin_client.post(A, json=_body())
    aid = r.json()["id"]
    r = await admin_client.patch(f"{A}/{aid}", json={"title": None})
    assert r.status_code == 200
    assert r.json()["title"] == "Hello"


@pytest.mark.asyncio
async def test_patch_ends_before_starts_rejected(admin_client):
    r = await admin_client.post(A, json=_body())
    aid = r.json()["id"]
    r = await admin_client.patch(f"{A}/{aid}", json={"ends_at": _iso(-2)})
    assert r.status_code == 422
