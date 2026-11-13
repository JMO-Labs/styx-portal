"""Home archive API: list, restore, send (ADR-0052 POSIX uid, S3 store)."""
import errno
import os
import stat

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


def _chown(path_or_fd, uid: int, **kw) -> None:
    os.chown(path_or_fd, uid, -1, **kw)


_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _parts(uid: int, relpath: str) -> list[str]:
    parts = relpath.split("/")
    if relpath.startswith("/") or "\x00" in relpath or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(400, "invalid path")
    return [str(uid), *parts]


def _walk(homes_root: str, uid: int, relpath: str, create: bool) -> tuple[int, str]:
    """Open the leaf's parent dir via dir fds, never following symlinks.

    Returns (parent_fd, leaf); the caller closes parent_fd. Missing dirs are
    created and chowned to uid only when ``create``.
    """
    *dirs, leaf = _parts(uid, relpath)
    fd = os.open(homes_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in dirs:
            try:
                nfd = os.open(part, _DIR, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise HTTPException(404, "file not found") from None
                os.mkdir(part, 0o755, dir_fd=fd)
                _chown(part, uid, dir_fd=fd, follow_symlinks=False)
                nfd = os.open(part, _DIR, dir_fd=fd)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise HTTPException(400, "invalid path") from None
                raise
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd, leaf


def _restore(store, key: str, homes_root: str, uid: int, relpath: str) -> None:
    _parts(uid, relpath)
    if not store.exists(key, relpath):
        raise HTTPException(404, "not in archive")
    dfd, leaf = _walk(homes_root, uid, relpath, create=True)
    try:
        try:
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o644, dir_fd=dfd)
        except FileExistsError:
            raise HTTPException(409, "file exists") from None
        try:
            with os.fdopen(fd, "wb") as fh:
                mtime = store.get(key, relpath, fh)
                fh.flush()
                os.utime(fh.fileno(), (mtime, mtime))
                _chown(fh.fileno(), uid)
        except BaseException:
            os.unlink(leaf, dir_fd=dfd)
            raise
    finally:
        os.close(dfd)


def _send(store, key: str, homes_root: str, uid: int, relpath: str) -> None:
    dfd, leaf = _walk(homes_root, uid, relpath, create=False)
    try:
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        except OSError:
            raise HTTPException(404, "file not found") from None
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise HTTPException(404, "file not found")
            store.put(key, relpath, fh, st.st_mtime)
        os.unlink(leaf, dir_fd=dfd)
    finally:
        os.close(dfd)


@router.get("", response_model=list[ArchiveEntry])
async def list_archive(request: Request,
                       user: User = Depends(get_current_user),
                       store: ArchiveStore = Depends(get_archive_store),
                       session: AsyncSession = Depends(get_session)):
    key = str(await allocate_uid(session, user.id))
    rows = await run_in_threadpool(store.list_with_size, key)
    await audit_request(session, request, "archive.list", user_id=user.id)
    await session.commit()
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
