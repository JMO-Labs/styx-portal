import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

import pytest
from sqlmodel import select

from app.models import Instance, ServiceTemplate, User
from app.services.k8s_instance_objects import build_objects
from app.services.unlock_token import mint_token, unlock_key
from tests import dmz_haproxy_checks as dmz

CARD = {"Client-Cert": "MIIBfake"}


def test_key_is_per_instance():
    assert unlock_key("a") != unlock_key("b")
    assert unlock_key("a") == unlock_key("a")
    assert len(unlock_key("a")) == 32


def test_token_format_and_expiry():
    tok = mint_token("a", now=1000)
    exp, mac = tok.split(".")
    assert exp == "1060"
    assert mac == hmac.new(unlock_key("a"), b"a:1060", hashlib.sha256).hexdigest()


def test_pod_env_has_unlock_key():
    dep, _ = build_objects("selkies-abc", "img", {"STYX_INSTANCE_ID": "inst-1"},
                           {}, 3000, "ns", "u1")
    env = {e["name"]: e["value"]
           for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["STYX_UNLOCK_KEY"] == unlock_key("inst-1").hex()


async def _inst(session, owner_name="member"):
    owner = (await session.exec(select(User).where(User.username == owner_name))).one()
    t = ServiceTemplate(name="t", display_name="T", image="i", default_port=3000)
    session.add(t)
    await session.commit()
    i = Instance(template_id=t.id, owner_id=owner.id, name="n", subdomain="abc")
    session.add(i)
    await session.commit()
    return i


@pytest.mark.asyncio
async def test_403_without_card_header(member_client, session):
    i = await _inst(session)
    r = await member_client.get(f"/api/instances/{i.id}/unlock", follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_403_for_non_owner(second_member_client, session):
    i = await _inst(session, "member2")
    other = User(username="someone-else", password_hash="x")
    session.add(other)
    await session.flush()
    i.owner_id = other.id
    session.add(i)
    await session.commit()
    r = await second_member_client.get(f"/api/instances/{i.id}/unlock",
                                       headers=CARD, follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_valid_token_in_redirect(member_client, session):
    i = await _inst(session)
    r = await member_client.get(f"/api/instances/{i.id}/unlock",
                                headers=CARD, follow_redirects=False)
    assert r.status_code == 302
    u = urlparse(r.headers["location"])
    assert u.scheme == "https" and u.path == "/styx/unlock"
    assert u.hostname.startswith("abc.")
    tok = parse_qs(u.query)["token"][0]
    exp, mac = tok.split(".")
    assert mac == hmac.new(unlock_key(i.id), f"{i.id}:{exp}".encode(),
                           hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_404_unknown_instance(member_client):
    r = await member_client.get("/api/instances/nope/unlock", headers=CARD,
                                follow_redirects=False)
    assert r.status_code == 404


def test_haproxy_keeps_resumption_off():
    cfg = dmz.strip_comments(dmz.render("haproxy.cfg.j2"))
    assert "tune.ssl.cachesize 0" in dmz.directives(dmz.section(cfg, "global"), "tune.ssl")
    glob = dmz.section(cfg, "global")
    assert "no-tls-tickets" in " ".join(dmz.directives(glob, "ssl-default-bind-options"))
    for ln in dmz.directives(cfg, "bind"):
        assert "tls-tickets" not in ln or "no-tls-tickets" in ln
