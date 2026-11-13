import json
from pathlib import Path

from sqlmodel import select

from app.config import settings
from app.database import seed_service_presets
from app.models import ProxiedService, ServicePreset
from app.services.enterprise_services import seed_enterprise_services

PRESETS = Path(__file__).resolve().parents[2] / "templates" / "services"


async def _rows(session):
    return (await session.exec(select(ProxiedService))).all()


async def test_creates_rows_for_set_urls(session, monkeypatch):
    monkeypatch.setattr(settings, "WIKI_URL", "https://wiki.example.com")
    monkeypatch.setattr(settings, "ELEMENT_URL", "https://chat.example.com")
    await seed_enterprise_services(session)
    rows = {r.slug: r for r in await _rows(session)}
    assert set(rows) == {"wikijs", "element"}
    w = rows["wikijs"]
    assert w.upstream_url == "https://wiki.example.com"
    assert w.auth_mode == "app-native" and w.allowed_groups == [] and w.enabled
    assert w.preset_id == "wikijs" and w.kind == "url"
    assert rows["element"].upstream_url == "https://chat.example.com"


async def test_idempotent(session, monkeypatch):
    monkeypatch.setattr(settings, "WIKI_URL", "https://wiki.example.com")
    monkeypatch.setattr(settings, "ELEMENT_URL", "https://chat.example.com")
    await seed_enterprise_services(session)
    await seed_enterprise_services(session)
    assert len(await _rows(session)) == 2


async def test_existing_row_not_overwritten(session, monkeypatch):
    monkeypatch.setattr(settings, "WIKI_URL", "https://wiki.example.com")
    monkeypatch.setattr(settings, "ELEMENT_URL", "")
    await seed_enterprise_services(session)
    row = (await _rows(session))[0]
    row.name = "Renamed"
    session.add(row)
    await session.commit()
    monkeypatch.setattr(settings, "WIKI_URL", "https://other.example.com")
    await seed_enterprise_services(session)
    rows = await _rows(session)
    assert len(rows) == 1 and rows[0].name == "Renamed"
    assert rows[0].upstream_url == "https://wiki.example.com"


async def test_unset_creates_nothing(session, monkeypatch):
    monkeypatch.setattr(settings, "WIKI_URL", "")
    monkeypatch.setattr(settings, "ELEMENT_URL", "")
    await seed_enterprise_services(session)
    assert await _rows(session) == []


async def test_only_one_set(session, monkeypatch):
    monkeypatch.setattr(settings, "WIKI_URL", "")
    monkeypatch.setattr(settings, "ELEMENT_URL", "https://chat.example.com")
    await seed_enterprise_services(session)
    assert [r.slug for r in await _rows(session)] == ["element"]


async def test_presets_seed(session):
    await seed_service_presets(session, str(PRESETS))
    for pid in ("wikijs", "element"):
        p = await session.get(ServicePreset, pid)
        assert p is not None and p.auth_mode == "app-native"
        assert json.loads((PRESETS / f"{pid}.json").read_text())["id"] == pid
