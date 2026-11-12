import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.config import Settings
from app.models import PosixUid, User
from app.services.offboarding import disable_account
from app.services.posix_uid import allocate_uid


async def test_starts_at_min_and_is_idempotent(session):
    a = await allocate_uid(session, "alice")
    assert a == Settings().POSIX_UID_MIN == 100000
    assert await allocate_uid(session, "alice") == a


async def test_distinct_users_get_distinct_uids(session):
    a = await allocate_uid(session, "alice")
    b = await allocate_uid(session, "bob")
    assert a != b and b == a + 1


async def test_uid_not_reused_after_user_disabled(session):
    alice = User(username="alice", password_hash="x")
    session.add(alice)
    await session.commit()
    a = await allocate_uid(session, str(alice.id))
    before = (await session.exec(select(PosixUid).where(PosixUid.uid == a))).one()
    snap = (before.uid, before.user_key, before.allocated_at)
    assert await disable_account(session, alice, "left", actor=None)
    c = await allocate_uid(session, "carol")
    assert c > a
    rows = (await session.exec(select(PosixUid).where(PosixUid.user_key == str(alice.id)))).all()
    assert [(r.uid, r.user_key, r.allocated_at) for r in rows] == [snap]


async def test_duplicate_uid_rejected(session):
    await allocate_uid(session, "alice")
    session.add(PosixUid(uid=Settings().POSIX_UID_MIN, user_key="mallory"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


def test_no_delete_or_update_path():
    import inspect
    from app.services import posix_uid
    src = inspect.getsource(posix_uid).lower()
    assert "delete(" not in src and "update(" not in src
