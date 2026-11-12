"""ADR-0053 / CM-7: the enterprise profile hard-disables homelab features."""
import pytest

from app import main
from app.config import Settings
from app.services import profile

# One probe per disabled feature: (feature, method, path)
PROBES = [
    ("password_login", "POST", "/api/auth/login"),
    ("matrix_2fa", "POST", "/api/auth/login/matrix"),
    ("matrix_2fa", "GET", "/api/auth/matrix"),
    ("generic_oidc", "GET", "/api/auth/oauth/providers"),
    ("generic_oidc", "GET", "/api/oauth-providers"),
    ("workstation_enrollment", "POST", "/api/enroll/register"),
    ("workstation_enrollment", "POST", "/api/agent/heartbeat"),
    ("workstation_enrollment", "GET", "/api/workstations"),
    ("docker_routers", "GET", "/api/images"),
    ("docker_routers", "GET", "/api/registry/images"),
    ("docker_routers", "POST", "/api/services/x/mount/plan"),
]


def test_default_profile_is_homelab():
    assert Settings().STYX_PROFILE == "homelab"
    assert profile.disabled_features(Settings()) == []


def test_every_disabled_feature_has_a_probe():
    assert {f for f, _, _ in PROBES} == set(profile.ENTERPRISE_DISABLED)


@pytest.mark.parametrize("feature,method,path", PROBES)
@pytest.mark.asyncio
async def test_enterprise_blocks(client, monkeypatch, feature, method, path):
    monkeypatch.setattr(main._settings, "STYX_PROFILE", "enterprise")
    r = await client.request(method, path)
    assert r.status_code == 404
    assert r.json()["detail"] == f"feature disabled: {feature}"


@pytest.mark.parametrize("feature,method,path", PROBES)
@pytest.mark.asyncio
async def test_homelab_unchanged(client, feature, method, path):
    r = await client.request(method, path)
    assert r.json().get("detail") != f"feature disabled: {feature}"


def test_startup_refuses_conflicting_config(tmp_path):
    sock = tmp_path / "docker.sock"
    sock.touch()
    s = Settings(STYX_PROFILE="enterprise", ROUTE_BACKEND="k8s",
                 DOCKER_SOCKET=f"unix://{sock}")
    with pytest.raises(RuntimeError, match="Docker socket"):
        profile.validate_profile(s)
    with pytest.raises(RuntimeError, match="ROUTE_BACKEND"):
        profile.validate_profile(Settings(STYX_PROFILE="enterprise",
                                          ROUTE_BACKEND="file",
                                          DOCKER_SOCKET="unix:///nonexistent"))
    profile.validate_profile(Settings(STYX_PROFILE="enterprise", ROUTE_BACKEND="k8s",
                                      DOCKER_SOCKET="unix:///nonexistent"))
    profile.validate_profile(Settings())   # homelab always fine


def test_unknown_profile_rejected():
    with pytest.raises(RuntimeError, match="STYX_PROFILE"):
        profile.validate_profile(Settings(STYX_PROFILE="bogus"))


@pytest.mark.asyncio
async def test_features_endpoint(client, admin_client, monkeypatch):
    assert (await client.get("/api/diagnostics/features")).status_code == 401
    r = await admin_client.get("/api/diagnostics/features")
    body = r.json()
    assert body["profile"] == "homelab"
    assert set(body["disabled"]) == set()
    assert set(body["enabled"]) == set(profile.ALL_FEATURES)
    monkeypatch.setattr(main._settings, "STYX_PROFILE", "enterprise")
    body = (await admin_client.get("/api/diagnostics/features")).json()
    assert set(body["disabled"]) == set(profile.ENTERPRISE_DISABLED)
    assert body["enabled"] == []
