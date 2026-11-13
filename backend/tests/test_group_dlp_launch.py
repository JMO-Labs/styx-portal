from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app.models import Group, User, UserGroup
from app.services.group_dlp import DLP_DEFAULTS, DLP_ENV_KEYS, dlp_env


def test_d38_defaults():
    env = dlp_env(dict(DLP_DEFAULTS), username="alice")
    assert env["SELKIES_FILE_TRANSFERS"] == "upload"
    assert env["STYX_WATERMARK_USER"] == "alice"
    assert env["SELKIES_CLIPBOARD_ENABLED"] == "true"
    assert "SELKIES_PRINTING_ENABLED" not in env


@pytest.mark.parametrize("cin,cout,want", [
    (True, True, "true"), (True, False, "false"), (False, True, "false"),
    (False, False, "false")])
def test_clipboard_fails_closed_unless_both(cin, cout, want):
    env = dlp_env({**DLP_DEFAULTS, "clipboard_in": cin, "clipboard_out": cout,
                   "watermark": False})
    assert env["SELKIES_CLIPBOARD_ENABLED"] == want
    assert "SELKIES_ENABLE_CLIPBOARD" not in env


def test_watermark_requires_username():
    for u in (None, ""):
        with pytest.raises(ValueError):
            dlp_env(DLP_DEFAULTS, username=u)


def test_file_transfers_and_watermark_off():
    p = {**DLP_DEFAULTS, "upload": True, "download": True, "watermark": False}
    env = dlp_env(p, username="a")
    assert env["SELKIES_FILE_TRANSFERS"] == "upload,download"
    assert "STYX_WATERMARK_USER" not in env
    assert dlp_env({**DLP_DEFAULTS, "upload": False})["SELKIES_FILE_TRANSFERS"] == "none"


def test_watermark_is_bare_username():
    env = dlp_env(DLP_DEFAULTS, username="bob")
    assert env["STYX_WATERMARK_USER"] == "bob"
    assert set(env) <= DLP_ENV_KEYS


@pytest.mark.asyncio
async def test_launch_overrides_dlp_wins_over_template(session):
    from app.services.group_tier import launch_overrides, merge_launch_env
    from app.services.k8s_instances import K8sInstanceRuntime

    u = User(email="d@x.io", username="dave", password_hash="x")
    g = Group(name="dg", tier_fps=30, dlp_approval_ref="CHG-1", dlp_clipboard_in=False,
              dlp_clipboard_out=False)
    session.add_all([u, g])
    await session.commit()
    session.add(UserGroup(user_id=u.id, group_id=g.id))
    await session.commit()
    inst = NS(owner_id=u.id)
    tpl = NS(memory_limit=None, cpu_limit=None,
             env_vars={"SELKIES_ENABLE_CLIPBOARD": "true", "SELKIES_CLIPBOARD_ENABLED": "true",
                       "SELKIES_FILE_TRANSFERS": "upload,download",
                       "SELKIES_PRINTING_ENABLED": "true", "SELKIES_FRAMERATE": "144"})
    env, _, _ = await launch_overrides(session, MagicMock(spec=K8sInstanceRuntime), inst, tpl)
    assert env["STYX_WATERMARK_USER"] == "dave"
    merged = merge_launch_env(env, tpl.env_vars, {"SELKIES_FILE_TRANSFERS": "upload,download"})
    assert merged["SELKIES_CLIPBOARD_ENABLED"] == "false"
    assert merged["SELKIES_FILE_TRANSFERS"] == "upload"
    assert merged["SELKIES_FRAMERATE"] == "144"  # tier keys: template wins
