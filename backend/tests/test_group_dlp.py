import pytest

from app.models import Group, User, UserGroup
from app.services.group_dlp import DLP_DEFAULTS, resolve_group_dlp, user_group_dlp


def test_defaults_values():
    assert DLP_DEFAULTS == {
        "clipboard_in": True, "clipboard_out": True, "upload": True,
        "download": False, "printing": False, "watermark": True}


def test_no_groups_or_no_override_returns_defaults():
    assert resolve_group_dlp([]) == DLP_DEFAULTS
    assert resolve_group_dlp([Group(name="a")]) == DLP_DEFAULTS
    # settings without approval ref are ignored
    assert resolve_group_dlp([Group(name="b", dlp_download=True, dlp_approval_ref="")]) == DLP_DEFAULTS
    assert resolve_group_dlp([Group(name="c", dlp_download=True)]) == DLP_DEFAULTS


def test_single_approved_override():
    g = Group(name="a", dlp_approval_ref="CHG-1", dlp_download=True, dlp_clipboard_in=False)
    r = resolve_group_dlp([g])
    assert r["download"] is True and r["clipboard_in"] is False
    assert r["upload"] is True and r["printing"] is False


def test_most_restrictive_wins():
    g1 = Group(name="a", dlp_approval_ref="X", dlp_download=True, dlp_printing=True,
               dlp_watermark=False)
    g2 = Group(name="b", dlp_approval_ref="Y", dlp_download=False, dlp_printing=True,
               dlp_watermark=True)
    g3 = Group(name="c", dlp_download=False)  # unapproved: ignored
    r = resolve_group_dlp([g1, g2, g3])
    assert r["download"] is False
    assert r["printing"] is True
    assert r["watermark"] is True
    g4 = Group(name="d", dlp_approval_ref="Z", dlp_watermark=False)
    assert resolve_group_dlp([g1, g4])["watermark"] is False


@pytest.mark.asyncio
async def test_user_group_dlp(session):
    u = User(username="dlp", password_hash="x", role="member")
    session.add(u)
    g1 = Group(name="g1", dlp_approval_ref="R", dlp_download=True)
    g2 = Group(name="g2", dlp_approval_ref="R2", dlp_download=True, dlp_upload=False)
    g3 = Group(name="g3", dlp_approval_ref="R3", dlp_download=False)  # not a member
    session.add_all([g1, g2, g3])
    await session.commit()
    session.add_all([UserGroup(user_id=u.id, group_id=g1.id),
                     UserGroup(user_id=u.id, group_id=g2.id)])
    await session.commit()
    r = await user_group_dlp(session, u.id)
    assert r["download"] is True and r["upload"] is False
    assert await user_group_dlp(session, "nobody") == DLP_DEFAULTS
