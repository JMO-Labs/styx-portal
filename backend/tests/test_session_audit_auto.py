"""Automatic stop paths emit session.stop with a reason (#236)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from app.models import Instance, ServiceTemplate, SessionEvent, User
from app.services import cve_recycle
from app.services.background_loops import _run_monitor_pass
from app.services.offboarding import disable_account
from app.services.session_monitor import SessionMonitor
from tests.test_cve_recycle import NOW, cfg, harbor
from tests.test_session_audit import lines  # noqa: F401  fixture


async def _inst(session, **kw):
    user = User(username="ann", email="ann@example.com", password_hash="x")
    tmpl = ServiceTemplate(name="t", display_name="t", image="harbor.example/styx/desktop:latest")
    session.add_all([user, tmpl])
    await session.flush()
    inst = Instance(owner_id=user.id, template_id=tmpl.id, name="i", subdomain="s",
                    container_id="c1", image_digest="sha256:abc", **kw)
    session.add(inst)
    await session.commit()
    return user, inst


def _stops(evs):
    return [e for e in evs if e["event"]["action"] == "session.stop"]


@pytest.mark.asyncio
async def test_idle_stop_emits_reason_idle(session, lines):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    user, inst = await _inst(session, status="idle", last_activity=old, started_at=old,
                             session_config={"idle_timeout": "30m", "grace_period": "5m"})
    docker = MagicMock()
    docker.get_container_status.return_value = {"status": "running"}
    assert await _run_monitor_pass(session, SessionMonitor(docker), docker) is True
    await session.commit()
    (ev,) = _stops(lines())
    assert ev["styx"]["session"]["reason"] == "idle"
    assert ev["styx"]["session"]["id"] == inst.id
    assert ev["user"]["name"] == "ann"
    rows = (await session.exec(select(SessionEvent).where(
        SessionEvent.event_type == "auto_stopped"))).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_idle_warning_emits_no_line(session, lines):
    old = datetime.now(timezone.utc) - timedelta(minutes=35)
    await _inst(session, status="running", last_activity=old, started_at=old)
    docker = MagicMock()
    docker.get_container_status.return_value = {"status": "running"}
    await _run_monitor_pass(session, SessionMonitor(docker), docker)
    assert lines() == []


@pytest.mark.asyncio
async def test_offboarding_stop_emits_reason_offboarded(session, lines):
    user, inst = await _inst(session, status="running")
    await disable_account(session, user, "left", None, runtime=MagicMock())
    (ev,) = _stops(lines())
    assert ev["styx"]["session"]["reason"] == "offboarded"
    assert ev["styx"]["session"]["id"] == inst.id


@pytest.mark.asyncio
async def test_cve_recycle_emits_reason_and_warn_is_silent(session, lines):
    _, inst = await _inst(session, status="running")
    client, _ = harbor(["CRITICAL"])
    await cve_recycle.recycle_pass(session, lambda i: None, cfg(), client, now=NOW)
    assert lines() == []  # cve_warned: no ECS line
    await session.refresh(inst)
    later = inst.recycle_deadline + timedelta(minutes=1)
    assert await cve_recycle.recycle_pass(session, lambda i: None, cfg(), client, now=later) == 1
    (ev,) = _stops(lines())
    assert ev["styx"]["session"]["reason"] == "cve_recycle"
    assert ev["styx"]["session"]["id"] == inst.id
