import os

import pytest
from sqlmodel import select

from app.models import AuditLog
from app.routers import archive as ar
from app.services.posix_uid import allocate_uid


class FakeStore:
    def __init__(self):
        self.objs = {}  # (uid, rel) -> (bytes, mtime)

    def list_with_size(self, uid):
        return [(r, len(d), m) for (u, r), (d, m) in self.objs.items() if u == uid]

    def exists(self, uid, rel):
        return (uid, rel) in self.objs

    def get(self, uid, rel, fh):
        d, m = self.objs[(uid, rel)]
        fh.write(d)
        return m

    def put(self, uid, rel, fh, mtime):
        self.objs[(uid, rel)] = (fh.read(), mtime)


@pytest.fixture
def env(member_client, tmp_path, monkeypatch):
    from app.main import app

    store = FakeStore()
    chowns = []
    monkeypatch.setattr(ar, "_chown", lambda p, uid, **kw: chowns.append((p, uid)))
    app.dependency_overrides[ar.get_archive_store] = lambda: store
    app.dependency_overrides[ar.get_homes_root] = lambda: str(tmp_path)
    yield member_client, store, tmp_path, chowns
    app.dependency_overrides.pop(ar.get_archive_store, None)
    app.dependency_overrides.pop(ar.get_homes_root, None)


async def _uid(session):
    from app.models import User
    u = (await session.exec(select(User).where(User.username == "member"))).one()
    return await allocate_uid(session, u.id)


async def test_list_disabled_404(member_client):
    r = await member_client.get("/api/archive")
    assert r.status_code == 404 and r.json()["detail"] == "archive disabled"


async def test_list(env, session):
    c, store, _, _ = env
    uid = str(await _uid(session))
    store.objs[(uid, "a/b.txt")] = (b"hello", 123.0)
    store.objs[("other", "x")] = (b"z", 1.0)
    r = await c.get("/api/archive")
    assert r.status_code == 200
    assert r.json() == [{"relpath": "a/b.txt", "size": 5, "mtime": 123.0}]


async def test_requires_auth(client):
    assert (await client.get("/api/archive")).status_code == 401


async def test_restore(env, session):
    c, store, home, chowns = env
    uid = await _uid(session)
    store.objs[(str(uid), "d/f.txt")] = (b"data", 1000.0)
    r = await c.post("/api/archive/restore", json={"relpath": "d/f.txt"})
    assert r.status_code == 200, r.text
    p = home / str(uid) / "d" / "f.txt"
    assert p.read_bytes() == b"data"
    assert int(p.stat().st_mtime) == 1000
    # new dirs chowned by name relative to a dir fd; file via its open fd
    assert ("d", uid) in chowns
    assert isinstance(chowns[-1][0], int) and chowns[-1][1] == uid
    log = (await session.exec(select(AuditLog).where(AuditLog.action == "archive.restore"))).all()
    assert len(log) == 1


async def test_restore_conflict(env, session):
    c, store, home, _ = env
    uid = await _uid(session)
    store.objs[(str(uid), "f")] = (b"new", 1.0)
    (home / str(uid)).mkdir()
    (home / str(uid) / "f").write_bytes(b"old")
    r = await c.post("/api/archive/restore", json={"relpath": "f"})
    assert r.status_code == 409
    assert (home / str(uid) / "f").read_bytes() == b"old"


async def test_restore_missing_404(env):
    c, *_ = env
    r = await c.post("/api/archive/restore", json={"relpath": "nope"})
    assert r.status_code == 404


async def test_send(env, session):
    c, store, home, _ = env
    uid = await _uid(session)
    f = home / str(uid) / "s" / "f.txt"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"bye")
    os.utime(f, (500, 500))
    r = await c.post("/api/archive/send", json={"relpath": "s/f.txt"})
    assert r.status_code == 200, r.text
    assert store.objs[(str(uid), "s/f.txt")] == (b"bye", 500.0)
    assert not f.exists()
    log = (await session.exec(select(AuditLog).where(AuditLog.action == "archive.send"))).all()
    assert len(log) == 1


async def test_send_missing_404(env):
    c, *_ = env
    assert (await c.post("/api/archive/send", json={"relpath": "n"})).status_code == 404


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/etc/passwd", "", "a//b"])
@pytest.mark.parametrize("op", ["restore", "send"])
async def test_traversal_400(env, rel, op):
    c, *_ = env
    r = await c.post(f"/api/archive/{op}", json={"relpath": rel})
    assert r.status_code == 400


async def test_send_symlink_escape_400(env, session, tmp_path_factory):
    c, store, home, _ = env
    uid = await _uid(session)
    outside = tmp_path_factory.mktemp("out")
    (outside / "secret").write_text("s")
    h = home / str(uid)
    h.mkdir()
    (h / "link").symlink_to(outside)
    r = await c.post("/api/archive/send", json={"relpath": "link/secret"})
    assert r.status_code == 400
    assert (outside / "secret").exists() and not store.objs


async def test_restore_symlink_escape_400(env, session, tmp_path_factory):
    c, store, home, _ = env
    uid = await _uid(session)
    outside = tmp_path_factory.mktemp("out")
    h = home / str(uid)
    h.mkdir()
    (h / "link").symlink_to(outside)
    store.objs[(str(uid), "link/f")] = (b"x", 1.0)
    r = await c.post("/api/archive/restore", json={"relpath": "link/f"})
    assert r.status_code == 400
    assert not (outside / "f").exists()


async def test_post_requires_csrf(env):
    c, *_ = env
    r = await c.post("/api/archive/send", json={"relpath": "f"},
                     headers={"X-CSRF-Token": "bad"})
    assert r.status_code == 403


async def test_list_writes_audit(env, session):
    c, *_ = env
    assert (await c.get("/api/archive")).status_code == 200
    rows = (await session.exec(select(AuditLog).where(AuditLog.action == "archive.list"))).all()
    assert len(rows) == 1


async def test_send_refuses_symlink_target(env, session, tmp_path_factory):
    c, store, home, _ = env
    uid = await _uid(session)
    outside = tmp_path_factory.mktemp("out")
    (outside / "secret").write_text("s")
    h = home / str(uid)
    h.mkdir()
    (h / "f").symlink_to(outside / "secret")
    r = await c.post("/api/archive/send", json={"relpath": "f"})
    assert r.status_code == 404 and not store.objs


def _nested_link(home, uid, outside):
    h = home / str(uid) / "a"
    h.mkdir(parents=True)
    (h / "link").symlink_to(outside)


@pytest.mark.parametrize("op", ["restore", "send"])
async def test_intermediate_symlink_400(env, session, tmp_path_factory, op):
    c, store, home, _ = env
    uid = await _uid(session)
    outside = tmp_path_factory.mktemp("out")
    (outside / "sub").mkdir()
    (outside / "sub" / "f").write_text("s")
    _nested_link(home, uid, outside)
    store.objs[(str(uid), "a/link/sub/g")] = (b"x", 1.0)
    rel = "a/link/sub/g" if op == "restore" else "a/link/sub/f"
    r = await c.post(f"/api/archive/{op}", json={"relpath": rel})
    assert r.status_code == 400
    assert not (outside / "sub" / "g").exists() and (outside / "sub" / "f").exists()
    assert not any(k[1] == "a/link/sub/f" for k in store.objs)


@pytest.mark.parametrize("op", ["restore", "send"])
async def test_symlink_rejected_without_realpath(env, session, tmp_path_factory,
                                                 monkeypatch, op):
    """Simulate the check/use race: realpath sees no symlink, the walk must."""
    c, store, home, _ = env
    monkeypatch.setattr(os.path, "realpath", lambda p, *a, **k: p)
    uid = await _uid(session)
    outside = tmp_path_factory.mktemp("out")
    (outside / "f").write_text("s")
    h = home / str(uid)
    h.mkdir()
    (h / "link").symlink_to(outside)
    store.objs[(str(uid), "link/g")] = (b"x", 1.0)
    rel = "link/g" if op == "restore" else "link/f"
    r = await c.post(f"/api/archive/{op}", json={"relpath": rel})
    assert r.status_code == 400
    assert not (outside / "g").exists() and (outside / "f").exists()
