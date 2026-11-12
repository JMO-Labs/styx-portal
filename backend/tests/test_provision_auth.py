import base64
import hashlib
import logging

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.security import provision_auth as pa

DER = b"\x30\x82fake-der-bytes"
CERT = base64.b64encode(DER).decode()
FP = hashlib.sha256(DER).hexdigest()
TOKEN = "s3cret-bearer-token-value"
HOST = "provision.example.test"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pa._settings, "PROVISION_HOST", HOST)
    monkeypatch.setattr(pa._settings, "PROVISION_BEARER_TOKEN", TOKEN)
    monkeypatch.setattr(pa._settings, "PROVISION_CLIENT_CERT_FINGERPRINTS", f"aa11, {FP.upper()}")
    app = FastAPI()

    @app.get("/p")
    async def p(_=Depends(pa.require_provision_caller)):
        return {"ok": True}

    return AsyncClient(transport=ASGITransport(app=app), base_url=f"http://{HOST}")


def _h(**kw):
    h = {"Client-Cert": CERT, "Authorization": f"Bearer {TOKEN}"}
    h.update(kw)
    return {k: v for k, v in h.items() if v is not None}


async def test_success(client):
    assert (await client.get("/p", headers=_h())).status_code == 200


async def test_wrong_host_404(client):
    r = await client.get("/p", headers=_h(Host="other.example.test"))
    assert r.status_code == 404
    assert r.json()["detail"] == "bad_host"


async def test_host_with_port_ok(client):
    r = await client.get("/p", headers=_h(Host=f"{HOST}:443"))
    assert r.status_code == 200


async def test_unset_host_404(client, monkeypatch):
    monkeypatch.setattr(pa._settings, "PROVISION_HOST", "")
    assert (await client.get("/p", headers=_h())).status_code == 404


async def test_missing_cert(client):
    r = await client.get("/p", headers=_h(**{"Client-Cert": None}))
    assert (r.status_code, r.json()["detail"]) == (401, "cert_missing")


async def test_bad_cert_encoding(client):
    r = await client.get("/p", headers=_h(**{"Client-Cert": "!!notb64"}))
    assert (r.status_code, r.json()["detail"]) == (401, "cert_invalid")


async def test_unknown_fingerprint(client):
    other = base64.b64encode(b"other").decode()
    r = await client.get("/p", headers=_h(**{"Client-Cert": other}))
    assert (r.status_code, r.json()["detail"]) == (401, "cert_not_allowed")


async def test_no_fingerprints_configured_rejects(client, monkeypatch):
    monkeypatch.setattr(pa._settings, "PROVISION_CLIENT_CERT_FINGERPRINTS", "")
    r = await client.get("/p", headers=_h())
    assert r.status_code == 401


async def test_missing_bearer(client):
    r = await client.get("/p", headers=_h(Authorization=None))
    assert (r.status_code, r.json()["detail"]) == (401, "bearer_missing")


async def test_wrong_bearer(client):
    r = await client.get("/p", headers=_h(Authorization="Bearer nope"))
    assert (r.status_code, r.json()["detail"]) == (401, "bearer_invalid")


async def test_unset_token_rejects(client, monkeypatch):
    monkeypatch.setattr(pa._settings, "PROVISION_BEARER_TOKEN", "")
    r = await client.get("/p", headers=_h(Authorization="Bearer "))
    assert r.status_code == 401


async def test_secrets_never_logged_or_returned(client, caplog):
    caplog.set_level(logging.DEBUG)
    rs = [
        await client.get("/p", headers=_h()),
        await client.get("/p", headers=_h(Authorization="Bearer wrong-token-xyz")),
        await client.get("/p", headers=_h(**{"Client-Cert": base64.b64encode(b"zz").decode()})),
    ]
    blob = caplog.text + "".join(r.text for r in rs)
    for secret in (TOKEN, FP, FP.upper(), CERT, "wrong-token-xyz"):
        assert secret not in blob
