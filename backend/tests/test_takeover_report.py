import csv
import io
from datetime import datetime

import pytest
from sqlmodel import select

from app.models import AuditLog, SessionTakeover, User

URL = "/api/admin/takeovers/report"
HEADER = ["actor", "user", "instance", "mode", "reason", "start", "end", "duration"]


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


async def _seed(session):
    a = User(username="alice", password_hash="x", role="member")
    o = User(username="owen", password_hash="x", role="member")
    session.add_all([a, o])
    await session.commit()
    session.add_all([
        SessionTakeover(instance_id="i-1", actor_id=a.id, user_id=o.id, mode="control",
                        reason="fix, \"urgent\"", started_at=datetime(2026, 10, 5, 10, 0, 0),
                        ended_at=datetime(2026, 10, 5, 10, 30, 30)),
        SessionTakeover(instance_id="i-2", actor_id=a.id, user_id=o.id, mode="view",
                        reason="open", started_at=datetime(2026, 10, 6, 9, 0, 0)),
        SessionTakeover(instance_id="i-3", actor_id=a.id, user_id=o.id, mode="view",
                        reason="other month", started_at=datetime(2026, 11, 1, 0, 0, 0)),
    ])
    await session.commit()


async def test_report_content(admin_client, session):
    await _seed(session)
    r = await admin_client.get(URL, params={"month": "2026-10"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    rows = _rows(r.text)
    assert rows[0] == HEADER and len(rows) == 3
    assert rows[1] == ["alice", "owen", "i-1", "control", 'fix, "urgent"',
                       "2026-10-05T10:00:00", "2026-10-05T10:30:30", "1830"]
    assert rows[2][5:] == ["2026-10-06T09:00:00", "", ""]


async def test_report_empty_month(admin_client):
    r = await admin_client.get(URL, params={"month": "2020-01"})
    assert r.status_code == 200
    assert _rows(r.text) == [HEADER]


@pytest.mark.parametrize("m", ["2026-13", "2026-1", "garbage", "2026-10-01", "0000-00"])
async def test_report_bad_month(admin_client, m):
    assert (await admin_client.get(URL, params={"month": m})).status_code == 422


async def test_report_month_required(admin_client):
    assert (await admin_client.get(URL)).status_code == 422


async def test_report_audited(admin_client, session):
    await admin_client.get(URL, params={"month": "2026-10"})
    a = (await session.exec(select(AuditLog).where(AuditLog.action == "takeover.report"))).one()
    assert a.detail["month"] == "2026-10"


async def _set_staff(session, staff):
    u = (await session.exec(select(User).where(User.username == "member"))).one()
    u.staff_role = staff
    session.add(u)
    await session.commit()


async def test_report_auditor_allowed(member_client, session):
    await _set_staff(session, "auditor")
    assert (await member_client.get(URL, params={"month": "2026-10"})).status_code == 200


@pytest.mark.parametrize("staff", ["help-desk", "group-manager", ""])
async def test_report_denied(member_client, session, staff):
    await _set_staff(session, staff)
    r = await member_client.get(URL, params={"month": "2026-10"})
    assert r.status_code == 403
    assert (await session.exec(select(AuditLog).where(AuditLog.action == "takeover.report"))).first() is None
