import pytest
from prometheus_client import REGISTRY
from sqlmodel import select

from app.models import StreamSession, User
from app.routers import stream_rtt

URL = "/api/stream/rtt"


def _count(transport="webrtc"):
    return REGISTRY.get_sample_value("styx_stream_rtt_seconds_count", {"transport": transport}) or 0.0


def _body(**over):
    b = {"transport": "webrtc", "buckets": {".04": 3, ".08": 2}, "sum": 0.3}
    b.update(over)
    return b


@pytest.fixture(autouse=True)
def _reset():
    stream_rtt.reset_limiter()


async def _open(session, username="member", ended=False):
    from datetime import datetime
    u = (await session.exec(select(User).where(User.username == username))).one()
    session.add(StreamSession(target_kind="workstation", target_id="w1", user_id=u.id,
                              ended_at=datetime(2026, 1, 1) if ended else None))
    await session.commit()


async def test_rtt_valid_report_increments_histogram(member_client, session):
    await _open(session)
    before = _count()
    r = await member_client.post(URL, json=_body())
    assert r.status_code == 204, r.text
    assert _count() == before + 5
    assert REGISTRY.get_sample_value("styx_stream_rtt_seconds_bucket",
                                     {"transport": "webrtc", "le": "0.04"}) >= 3


async def test_rtt_requires_auth(client):
    client.cookies.set("csrf_token", "t")  # pass CSRF so the auth check is what answers
    r = await client.post(URL, json=_body(), headers={"X-CSRF-Token": "t"})
    assert r.status_code == 401


async def test_rtt_requires_open_stream_session(member_client, session):
    assert (await member_client.post(URL, json=_body())).status_code == 403
    await _open(session, ended=True)
    assert (await member_client.post(URL, json=_body())).status_code == 403
    session.add(StreamSession(target_kind="workstation", target_id="w2", user_id="someone-else"))
    await session.commit()
    assert (await member_client.post(URL, json=_body())).status_code == 403


@pytest.mark.parametrize("body", [
    _body(buckets={".05": 1}),
    _body(buckets={".04": -1}),
    _body(buckets={".04": 1.5}),
    _body(buckets={".04": True}),
    _body(buckets={".04": 16}, sum=0.1),
    _body(buckets={".04": 8, ".08": 8}),
    _body(transport="udp"),
    _body(sum=-1),
    _body(sum=151),
    _body(sum=1e308),
])
async def test_rtt_adversarial_422(member_client, session, body):
    await _open(session)
    r = await member_client.post(URL, json=body)
    assert r.status_code == 422, r.text


async def test_rtt_nan_sum_422(member_client, session):
    await _open(session)
    raw = '{"transport":"webrtc","buckets":{".04":1},"sum":NaN}'
    r = await member_client.post(URL, content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422


async def test_rtt_max_samples_ok(member_client, session):
    await _open(session)
    r = await member_client.post(URL, json=_body(buckets={"+Inf": 15}, sum=150))
    assert r.status_code == 204


async def test_rtt_rate_limited(member_client, session):
    await _open(session)
    assert (await member_client.post(URL, json=_body())).status_code == 204
    assert (await member_client.post(URL, json=_body())).status_code == 204
    assert (await member_client.post(URL, json=_body())).status_code == 429


def _samples():
    return [s for m in REGISTRY.collect() if m.name == "styx_stream_rtt_seconds" for s in m.samples]


async def test_rtt_no_extra_labels(member_client, session):
    from app.security.passwords import hash_password
    pw = "correct horse battery staple"
    session.add(User(username="member2", password_hash=hash_password(pw), role="member", is_active=True))
    await session.commit()
    await _open(session, "member")
    await _open(session, "member2")
    assert (await member_client.post(URL, json=_body())).status_code == 204
    one = len(_samples())
    assert one > 0
    r = await member_client.post("/api/auth/login", json={"username": "member2", "password": pw})
    assert r.status_code == 200, r.text
    member_client.headers.update({"X-CSRF-Token": member_client.cookies.get("csrf_token")})
    assert (await member_client.post(URL, json=_body())).status_code == 204
    assert len(_samples()) == one
    assert {frozenset(set(s.labels) - {"le"}) for s in _samples()} == {frozenset({"transport"})}


async def test_rtt_rate_limit_window_expires(member_client, session, monkeypatch):
    await _open(session)
    t = [1000.0]
    from types import SimpleNamespace
    monkeypatch.setattr(stream_rtt, "time", SimpleNamespace(monotonic=lambda: t[0]))
    for _ in range(2):
        assert (await member_client.post(URL, json=_body())).status_code == 204
    assert (await member_client.post(URL, json=_body())).status_code == 429
    t[0] += stream_rtt.WINDOW
    assert (await member_client.post(URL, json=_body())).status_code == 204
    assert len(next(iter(stream_rtt._hits.values()))) == 1
