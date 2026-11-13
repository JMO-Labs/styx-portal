"""Home archive API: list, restore, send (ADR-0052 POSIX uid, S3 store)."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import User
from app.schemas import ArchiveEntry, ArchivePath
from app.security.deps import get_current_user
from app.services.archive_store import ArchiveStore
from app.services.audit import audit_request
from app.services.posix_uid import allocate_uid

router = APIRouter()


def get_archive_store() -> ArchiveStore:
    if not Settings().archive_s3_endpoint:
        raise HTTPException(404, "archive disabled")
    return ArchiveStore()


def get_homes_root() -> str:
    return Settings().homes_root


def _chown(path, uid: int) -> None:
    os.chown(path, uid, -1)


def _safe_target(homes_root: str, uid: int, relpath: str) -> tuple[str, str]:
    """Return (home, target) with target confined to home, symlinks resolved."""
    parts = relpath.split("/")
    if relpath.startswith("/") or "\x00" in relpath or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(400, "invalid path")
    home = os.path.realpath(os.path.join(homes_root, str(uid)))
    target = os.path.join(home, *parts)
    parent = os.path.realpath(os.path.dirname(target))
    if parent != home and not parent.startswith(home + os.sep):
        raise HTTPException(400, "invalid path")
    return home, target


def _restore(store, key: str, homes_root: str, uid: int, relpath: str) -> None:
    home, target = _safe_target(homes_root, uid, relpath)
    if not any(r == relpath for r, _, _ in store.list_with_size(key)):
        raise HTTPException(404, "not in archive")
    if os.path.lexists(target):
        raise HTTPException(409, "file exists")
    # create missing parent dirs, owned by the user
    missing, d = [], os.path.dirname(target)
    while not os.path.isdir(d):
        missing.append(d)
        d = os.path.dirname(d)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    for m in reversed(missing):
        _chown(m, uid)
    try:
        with open(target, "xb") as fh:
            mtime = store.get(key, relpath, fh)
    except FileExistsError:
        raise HTTPException(409, "file exists") from None
    except BaseException:
        if os.path.exists(target):
            os.unlink(target)
        raise
    os.utime(target, (mtime, mtime))
    _chown(target, uid)


def _send(store, key: str, homes_root: str, uid: int, relpath: str) -> None:
    _, target = _safe_target(homes_root, uid, relpath)
    if os.path.islink(target) or not os.path.isfile(target):
        raise HTTPException(404, "file not found")
    mtime = os.stat(target).st_mtime
    with open(target, "rb") as fh:
        store.put(key, relpath, fh, mtime)
    os.unlink(target)


@router.get("", response_model=list[ArchiveEntry])
async def list_archive(user: User = Depends(get_current_user),
                       store: ArchiveStore = Depends(get_archive_store),
                       session: AsyncSession = Depends(get_session)):
    key = str(await allocate_uid(session, user.id))
    rows = await run_in_threadpool(store.list_with_size, key)
    return [ArchiveEntry(relpath=r, size=s, mtime=m) for r, s, m in rows]


async def _act(fn, name, body, request, user, store, homes_root, session):
    uid = await allocate_uid(session, user.id)
    await run_in_threadpool(fn, store, str(uid), homes_root, uid, body.relpath)
    await audit_request(session, request, f"archive.{name}", user_id=user.id,
                        resource=body.relpath)
    await session.commit()
    return {"ok": True}


@router.post("/restore")
async def restore(body: ArchivePath, request: Request,
                  user: User = Depends(get_current_user),
                  store: ArchiveStore = Depends(get_archive_store),
                  homes_root: str = Depends(get_homes_root),
                  session: AsyncSession = Depends(get_session)):
    return await _act(_restore, "restore", body, request, user, store, homes_root, session)


@router.post("/send")
async def send(body: ArchivePath, request: Request,
               user: User = Depends(get_current_user),
               store: ArchiveStore = Depends(get_archive_store),
               homes_root: str = Depends(get_homes_root),
               session: AsyncSession = Depends(get_session)):
    return await _act(_send, "send", body, request, user, store, homes_root, session)
