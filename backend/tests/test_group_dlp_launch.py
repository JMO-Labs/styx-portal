from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app.models import Group, User, UserGroup
from app.services.group_dlp import DLP_DEFAULTS, DLP_ENV_KEYS, dlp_env


def test_d38_defaults():
    env = dlp_env(dict(DLP_DEFAULTS), username="alice")
    assert env["SELKIES_ENABLE_CLIPBOARD"] == "true"
    assert env["SELKIES_FILE_TRANSFERS"] == "upload"
    assert env["SELKIES_PRINTING_ENABLED"] == "false"
    assert env["SELKIES_WATERMARK_TEXT"] == "alice {time}"


@pytest.mark.parametrize("cin,cout,want", [
    (True, True, "true"), (True, False, "in"), (False, True, "out"), (False, False, "false")])
def test_clipboard_directions(cin, cout, want):
    env = dlp_env({**DLP_DEFAULTS, "clipboard_in": cin, "clipboard_out": cout})
    assert env["SELKIES_ENABLE_CLIPBOARD"] == want


def test_file_transfers_and_watermark_off():
    p = {**DLP_DEFAULTS, "upload": True, "download": True, "watermark": False}
    env = dlp_env(p, username="a")
    assert env["SELKIES_FILE_TRANSFERS"] == "upload,download"
    assert "SELKIES_WATERMARK_TEXT" not in env
    assert dlp_env({**DLP_DEFAULTS, "upload": False})["SELKIES_FILE_TRANSFERS"] == "none"


def test_printing_on_omits_disable_key():
    env = dlp_env({**DLP_DEFAULTS, "printing": True})
    assert "SELKIES_PRINTING_ENABLED" not in env


def test_watermark_only_username_and_time_placeholder():
    env = dlp_env(DLP_DEFAULTS, username="bob")
    assert env["SELKIES_WATERMARK_TEXT"] == "bob {time}"
    assert set(env) <= DLP_ENV_KEYS


@pytest.mark.asyncio
async def test_launch_overrides_dlp_wins_over_template(session):
    from app.services.group_tier import launch_overrides, merge_launch_env
    from app.services.k8s_instances import K8sInstanceRuntime

    u = User(email="d@x.io", username="dave", password_hash="x")
    g = Group(name="dg", tier_fps=30)
    session.add_all([u, g])
    await session.commit()
    session.add(UserGroup(user_id=u.id, group_id=g.id))
    await session.commit()
    inst = NS(owner_id=u.id)
    tpl = NS(memory_limit=None, cpu_limit=None,
             env_vars={"SELKIES_ENABLE_CLIPBOARD": "true", "SELKIES_FILE_TRANSFERS": "upload,download",
                       "SELKIES_PRINTING_ENABLED": "true", "SELKIES_FRAMERATE": "144"})
    env, _, _ = await launch_overrides(session, MagicMock(spec=K8sInstanceRuntime), inst, tpl)
    assert env["SELKIES_WATERMARK_TEXT"] == "dave {time}"
    assert "Secret" not in env["SELKIES_WATERMARK_TEXT"]
    merged = merge_launch_env(env, tpl.env_vars, {"SELKIES_FILE_TRANSFERS": "upload,download"})
    assert merged["SELKIES_ENABLE_CLIPBOARD"] == "true"
    assert merged["SELKIES_FILE_TRANSFERS"] == "upload"
    assert merged["SELKIES_PRINTING_ENABLED"] == "false"
    assert merged["SELKIES_FRAMERATE"] == "144"  # tier keys: template wins
