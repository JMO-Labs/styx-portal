"""gateway_cfg.parse_env carries the enterprise lock/DLP settings (styx-portal#212)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gateway_cfg import parse_env  # noqa: E402


def test_parse_env_enterprise_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("STYX_GW_USER", "u")
    monkeypatch.setenv("STYX_GW_PASSWORD", "p")
    monkeypatch.setenv("STYX_GW_LOCK_IDLE_S", "300")
    monkeypatch.setenv("STYX_GW_UNLOCK_URL", "https://portal/unlock")
    monkeypatch.setenv("STYX_GW_UNLOCK_KEY", "k")
    monkeypatch.setenv("STYX_GW_INSTANCE_ID", "ws-1")
    monkeypatch.setenv("STYX_AGENT_CONFIG", str(tmp_path / "missing.json"))
    listen, upstream, user, password, kw = parse_env(["gw", "8080", "9090"])
    assert (listen, upstream, user, password) == (8080, 9090, "u", "p")
    assert kw["lock_idle_s"] == 300
    assert kw["unlock_url"] == "https://portal/unlock"
    assert kw["unlock_key"] == "k"
    assert kw["instance_id"] == "ws-1"
    assert kw["dlp_reporter"] is None


def test_parse_env_lock_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("STYX_GW_USER", "u")
    monkeypatch.setenv("STYX_GW_PASSWORD", "p")
    for k in ("STYX_GW_LOCK_IDLE_S", "STYX_GW_UNLOCK_URL", "STYX_GW_UNLOCK_KEY",
              "STYX_GW_INSTANCE_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STYX_AGENT_CONFIG", str(tmp_path / "missing.json"))
    kw = parse_env(["gw", "1", "2"])[4]
    assert kw["lock_idle_s"] == 0 and kw["unlock_url"] == "" and kw["instance_id"] == ""
