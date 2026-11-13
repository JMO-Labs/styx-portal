import pytest
from sqlmodel import select

from app.models import AuditLog


async def _gid(c):
    r = await c.post("/api/groups", json={"name": "g1"})
    return r.json()["id"]


async def _audits(session, action):
    return (await session.exec(select(AuditLog).where(AuditLog.action == action))).all()


@pytest.mark.asyncio
async def test_get_defaults(admin_client):
    gid = await _gid(admin_client)
    r = await admin_client.get(f"/api/groups/{gid}/dlp")
    assert r.status_code == 200
    j = r.json()
    assert j["approval_ref"] is None and j["approved_at"] is None
    assert j["override"]["upload"] is None
    assert j["effective"] == {"clipboard_in": True, "clipboard_out": True, "upload": True,
                              "download": False, "printing": False, "watermark": True}


@pytest.mark.asyncio
async def test_get_404(admin_client):
    assert (await admin_client.get("/api/groups/nope/dlp")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"upload": False}, {"upload": False, "approval_ref": ""},
                                  {"upload": False, "approval_ref": "  "}])
async def test_put_requires_ref(admin_client, body):
    gid = await _gid(admin_client)
    assert (await admin_client.put(f"/api/groups/{gid}/dlp", json=body)).status_code == 422


@pytest.mark.asyncio
async def test_put_stores_and_audits(admin_client, session):
    gid = await _gid(admin_client)
    r = await admin_client.put(f"/api/groups/{gid}/dlp",
                               json={"upload": False, "download": True, "approval_ref": "SEC-1"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["approval_ref"] == "SEC-1" and j["approved_at"]
    assert j["override"]["upload"] is False and j["effective"]["download"] is True
    [a] = await _audits(session, "group.dlp_override")
    assert a.resource == gid
    assert a.detail["approval_ref"] == "SEC-1"
    assert a.detail["old"]["upload"] is None and a.detail["new"]["upload"] is False
    # second PUT records previous values
    await admin_client.put(f"/api/groups/{gid}/dlp", json={"upload": True, "approval_ref": "SEC-2"})
    last = (await _audits(session, "group.dlp_override"))[-1]
    assert last.detail["old"]["upload"] is False and last.detail["old"]["download"] is True
    assert last.detail["new"]["download"] is None


@pytest.mark.asyncio
async def test_delete_clears_and_audits(admin_client, session):
    gid = await _gid(admin_client)
    await admin_client.put(f"/api/groups/{gid}/dlp", json={"upload": False, "approval_ref": "S"})
    r = await admin_client.delete(f"/api/groups/{gid}/dlp")
    assert r.status_code == 200
    j = r.json()
    assert j["approval_ref"] is None and j["approved_at"] is None
    assert all(v is None for v in j["override"].values())
    [a] = await _audits(session, "group.dlp_override_remove")
    assert a.detail["old"]["upload"] is False


@pytest.mark.asyncio
async def test_non_admin_403(member_client):
    for m, kw in (("get", {}), ("put", {"json": {"upload": False, "approval_ref": "x"}}),
                  ("delete", {})):
        r = await getattr(member_client, m)("/api/groups/x/dlp", **kw)
        assert r.status_code == 403
