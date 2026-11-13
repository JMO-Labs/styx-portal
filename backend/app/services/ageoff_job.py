"""Leader-only age-off: notice stale home files, then archive them (S3) and delete."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import select

from app.config import Settings
from app.models import Notice, User
from app.services.ageoff import Plan, plan, stale_files
from app.services.audit import audit
from app.services.notices import post_notice

log = logging.getLogger("styx.ageoff")
NOTICE_DAYS = 14


async def ageoff_tick(session, store, now: datetime, is_leader, dry_run: bool,
                      homes_root: str | None = None) -> dict[str, Plan]:
    """One pass. Returns {uid: Plan} for users with an actionable plan."""
    if not is_leader():
        return {}
    root = Path(homes_root if homes_root is not None else Settings().homes_root)
    if not root.is_dir():
        return {}
    ids = set((await session.exec(select(User.id))).all())
    out: dict[str, Plan] = {}
    for home in sorted(p for p in root.iterdir() if p.is_dir() and p.name in ids):
        uid = home.name
        stale = stale_files(home, now)
        notice = (await session.exec(
            select(Notice).where(Notice.user_id == uid, Notice.kind == "ageoff")
            .order_by(Notice.created_at.desc()))).first()
        sent = notice.created_at if notice else None
        if sent is not None:  # only files that were already stale when notified
            was = set(stale_files(home, sent))
            noticed = [s for s in stale if s in was]
            if noticed or now - sent < timedelta(days=NOTICE_DAYS):
                stale = noticed
            else:  # period elapsed, only newly-stale files remain: start a new cycle
                sent = None
        p = plan(stale, sent, now, NOTICE_DAYS, home)
        if p.action in ("none", "wait"):
            continue
        out[uid] = p
        if dry_run:
            log.info("ageoff dry-run uid=%s action=%s files=%d", uid, p.action, len(p.files))
            continue
        if p.action == "notice":
            await post_notice(
                session, uid, "ageoff", f"{now:%Y-%m-%d}",
                f"{len(p.files)} unused file(s) in your home will be archived after "
                f"{NOTICE_DAYS} days unless you open or modify them.",
                now + timedelta(days=NOTICE_DAYS))
        else:
            moved = _move(store, uid, home, p.files)
            if moved:
                await audit(session, "ageoff.move", user_id=uid, resource=uid,
                            detail={"files": moved})
                await session.commit()
    return out


def _move(store, uid: str, home: Path, files: list[str]) -> list[str]:
    moved = []
    for rel in files:
        path = home / rel
        try:
            with open(path, "rb") as fh:
                store.put(uid, rel, fh, os.fstat(fh.fileno()).st_mtime)
        except Exception:  # noqa: BLE001 - keep file on any upload/read error
            log.warning("ageoff upload failed uid=%s rel=%s", uid, rel, exc_info=True)
            continue
        try:
            path.unlink()
            moved.append(rel)
        except OSError:
            log.warning("ageoff local delete failed uid=%s rel=%s", uid, rel)
    return moved


async def ageoff_loop() -> None:
    from app.database import async_session
    from app.services.archive_store import ArchiveStore
    from app.services.leader import get_elector
    cfg = Settings()
    store, elector = ArchiveStore(settings=cfg), get_elector()
    while True:
        try:
            async with async_session() as session:
                await ageoff_tick(session, store, datetime.now(timezone.utc).replace(tzinfo=None),
                                  lambda: elector.is_leader, cfg.ageoff_dry_run)
        except Exception:  # noqa: BLE001
            log.warning("ageoff tick failed", exc_info=True)
        await asyncio.sleep(cfg.ageoff_interval_s)
