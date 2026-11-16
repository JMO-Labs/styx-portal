from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models_ops import OpsAlert, OpsState

URL = "/internal/alerts/alertmanager"


def _alert(fp="fp1", status="firing", name="HighCPU"):
    return {"status": status, "fingerprint": fp,
            "labels": {"alertname": name, "severity": "warning"},
            "annotations": {"summary": "s"},
            "startsAt": "2026-11-11T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z" if status == "firing" else "2026-11-11T10:05:00Z"}


def _payload(*alerts):
    return {"version": "4", "status": "firing", "alerts": list(alerts)}


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "tok-123")


def _auth(t="tok-123"):
    return {"Authorization": f"Bearer {t}"}


async def test_webhook_not_under_api_prefix(admin_client):
    r = await admin_client.post("/api/internal/alerts/alertmanager", json=_payload(),
                          headers=_auth())
    assert r.status_code == 404


async def test_webhook_rejects_missing_token(client):
    assert (await client.post(URL, json=_payload(_alert()))).status_code == 401


async def test_webhook_rejects_wrong_token(client):
    r = await client.post(URL, json=_payload(_alert()), headers=_auth("nope"))
    assert r.status_code == 401


async def test_webhook_disabled_when_token_unset(client, session, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", "")
    r = await client.post(URL, json=_payload(_alert()), headers=_auth(""))
    assert r.status_code == 503
    assert (await session.exec(select(OpsAlert))).all() == []


async def test_webhook_upserts_by_fingerprint(client, session):
    assert (await client.post(URL, json=_payload(_alert()), headers=_auth())).status_code == 200
    r = await client.post(URL, json=_payload(_alert(status="resolved")), headers=_auth())
    assert r.status_code == 200
    rows = (await session.exec(select(OpsAlert))).all()
    assert len(rows) == 1 and rows[0].status == "resolved"
    assert rows[0].labels["alertname"] == "HighCPU"


async def test_watchdog_updates_last_seen(client, session):
    await client.post(URL, json=_payload(_alert("w", name="Watchdog")), headers=_auth())
    st = (await session.exec(select(OpsState))).first()
    assert st and st.last_watchdog_at is not None


async def test_ops_alerts_lists_firing_only(admin_client):
    await admin_client.post(URL, json=_payload(_alert("a"), _alert("b", "resolved")),
                            headers=_auth())
    r = await admin_client.get("/api/admin/ops-alerts")
    assert r.status_code == 200
    assert [a["fingerprint"] for a in r.json()["alerts"]] == ["a"]


async def test_ops_alerts_monitoring_silent_after_10min(admin_client, session):
    r = await admin_client.get("/api/admin/ops-alerts")
    assert r.json()["monitoring_silent"] is True  # never seen
    await admin_client.post(URL, json=_payload(_alert("w", name="Watchdog")), headers=_auth())
    assert (await admin_client.get("/api/admin/ops-alerts")).json()["monitoring_silent"] is False
    st = (await session.exec(select(OpsState))).first()
    st.last_watchdog_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=11)
    session.add(st)
    await session.commit()
    assert (await admin_client.get("/api/admin/ops-alerts")).json()["monitoring_silent"] is True


async def test_ops_alerts_admin_only(member_client):
    assert (await member_client.get("/api/admin/ops-alerts")).status_code == 403


@pytest.mark.parametrize("body", [
    {"alerts": "nope"},
    {"no": "alerts"},
    [],
])
async def test_webhook_rejects_invalid_payload(client, body):
    r = await client.post(URL, json=body, headers=_auth())
    assert r.status_code == 422


async def test_webhook_rejects_non_json_body(client):
    r = await client.post(URL, content=b"not json", headers=_auth())
    assert r.status_code == 422


async def test_webhook_skips_alert_without_fingerprint(client, session):
    bad = _alert()
    del bad["fingerprint"]
    r = await client.post(URL, json=_payload(bad, _alert("ok")), headers=_auth())
    assert r.status_code == 200 and r.json() == {"received": 2}
    rows = (await session.exec(select(OpsAlert))).all()
    assert [x.fingerprint for x in rows] == ["ok"]


async def test_webhook_tolerates_missing_and_bad_timestamps(client, session):
    a = _alert("t1")
    del a["startsAt"]
    a["endsAt"] = "not-a-date"
    r = await client.post(URL, json=_payload(a), headers=_auth())
    assert r.status_code == 200
    row = (await session.exec(select(OpsAlert))).one()
    assert row.starts_at is None and row.ends_at is None
