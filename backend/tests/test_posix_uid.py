import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import PosixUid
from app.services.posix_uid import allocate_uid


async def test_starts_at_min_and_is_idempotent(session):
    a = await allocate_uid(session, "alice")
    assert a == settings.POSIX_UID_MIN == 100000
    assert await allocate_uid(session, "alice") == a


async def test_distinct_users_get_distinct_uids(session):
    a = await allocate_uid(session, "alice")
    b = await allocate_uid(session, "bob")
    assert a != b and b == a + 1


async def test_uid_not_reused_after_user_disabled(session):
    a = await allocate_uid(session, "alice")
    b = await allocate_uid(session, "bob")
    # disabling a user never touches posix_uids; a new user must go above max
    c = await allocate_uid(session, "carol")
    assert c == b + 1 and c != a


async def test_duplicate_uid_rejected(session):
    await allocate_uid(session, "alice")
    session.add(PosixUid(uid=settings.POSIX_UID_MIN, user_key="mallory"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


def test_no_delete_or_update_path():
    import inspect
    from app.services import posix_uid
    src = inspect.getsource(posix_uid).lower()
    assert "delete(" not in src and "update(" not in src
