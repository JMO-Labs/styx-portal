"""Keycloak break-glass bootstrap (issue #131): mocked admin REST API."""

import importlib.util
from pathlib import Path

import pytest
import yaml

BG = Path(__file__).resolve().parents[2] / "deploy/enterprise/keycloak/breakglass"
SCRIPT = BG / "breakglass_bootstrap.py"
PW1, PW2, ADMIN_PW = "pw-one-S3CRET", "pw-two-S3CRET", "admin-S3CRET"


def load():
    spec = importlib.util.spec_from_file_location("breakglass_bootstrap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeKC:
    """In-memory master realm: users, auth flows, executions."""

    def __init__(self, users=(), flows=()):
        self.users = {u: {"id": f"id-{u}", "username": u} for u in users}
        self.flows = {f: {"alias": f} for f in flows}
        self.execs = [
            {"id": "e1", "providerId": "auth-cookie", "requirement": "ALTERNATIVE", "level": 0},
            {"id": "e2", "providerId": "identity-provider-redirector", "requirement": "ALTERNATIVE", "level": 0},
            {"id": "e3", "displayName": "forms", "authenticationFlow": True, "requirement": "ALTERNATIVE", "level": 0},
            {"id": "e4", "providerId": "auth-username-password-form", "requirement": "REQUIRED", "level": 1},
            {"id": "e5", "displayName": "Browser - Conditional OTP", "authenticationFlow": True,
             "requirement": "CONDITIONAL", "level": 1},
            {"id": "e6", "providerId": "conditional-user-configured", "requirement": "REQUIRED", "level": 2},
            {"id": "e7", "providerId": "auth-otp-form", "requirement": "REQUIRED", "level": 2},
        ]
        self.realm_events = {"eventsListeners": ["jboss-logging"]}
        self.calls = []
        self.realm = {"browserFlow": "browser"}

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/users?username="):
            name = path.split("=", 1)[1].split("&")[0]
            return [self.users[name]] if name in self.users else []
        if method == "POST" and path == "/users":
            self.users[body["username"]] = {"id": f"id-{body['username']}", **body}
            return {}
        if path == "/roles/admin":
            return {"id": "r1", "name": "admin"}
        if path.endswith("/role-mappings/realm"):
            return {}
        if path.endswith("/reset-password"):
            return {}
        if path == "/authentication/flows" and method == "GET":
            return list(self.flows.values())
        if path.endswith("/copy"):
            self.flows[body["newName"]] = {"alias": body["newName"]}
            return {}
        if path.endswith("/executions") and method == "GET":
            return self.execs
        if path.endswith("/executions") and method == "PUT":
            for e in self.execs:
                if e["id"] == body["id"]:
                    e["requirement"] = body["requirement"]
            return {}
        if path == "/events/config" and method == "GET":
            return self.realm_events
        if path == "/events/config" and method == "PUT":
            self.realm_events.update(body)
            return {}
        if path == "" and method == "GET":
            return self.realm
        if path == "" and method == "PUT":
            self.realm.update(body)
            return {}
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def env(monkeypatch):
    for k, v in {"KC_URL": "http://kc", "KC_ADMIN_USER": "admin", "KC_ADMIN_PASSWORD": ADMIN_PW,
                 "BREAKGLASS_1_USERNAME": "bg-admin-1", "BREAKGLASS_1_PASSWORD": PW1,
                 "BREAKGLASS_2_USERNAME": "bg-admin-2", "BREAKGLASS_2_PASSWORD": PW2}.items():
        monkeypatch.setenv(k, v)


def run(monkeypatch, fake, *argv):
    mod = load()
    monkeypatch.setattr(mod, "Client", lambda *a, **k: fake)
    return mod.main(list(argv))


def posts(fake, path):
    return [c for c in fake.calls if c[0] == "POST" and c[1] == path]


def test_creates_exactly_two_admins_with_totp(env, monkeypatch, capsys):
    kc = FakeKC()
    assert run(monkeypatch, kc) == 0
    created = posts(kc, "/users")
    assert [b["username"] for _, _, b in created] == ["bg-admin-1", "bg-admin-2"]
    for _, _, b in created:
        assert b["requiredActions"] == ["CONFIGURE_TOTP"]
        assert b["enabled"] is True
    resets = [c for c in kc.calls if c[1].endswith("/reset-password")]
    assert [c[2]["value"] for c in resets] == [PW1, PW2]
    assert all(c[2]["temporary"] is False for c in resets)
    out = capsys.readouterr()
    for secret in (PW1, PW2, ADMIN_PW):
        assert secret not in out.out + out.err


def test_already_exists_is_idempotent(env, monkeypatch, capsys):
    kc = FakeKC(users=["bg-admin-1", "bg-admin-2"], flows=["breakglass-browser"])
    kc.realm["browserFlow"] = "breakglass-browser"
    kc.execs[4]["requirement"] = "REQUIRED"
    kc.realm_events["eventsListeners"] = ["jboss-logging", "micrometer-user-event-metrics"]
    assert run(monkeypatch, kc) == 0
    assert not [c for c in kc.calls if c[0] == "POST"]
    assert not [c for c in kc.calls if c[0] == "PUT"]
    assert "nothing to do" in capsys.readouterr().out


def test_otp_is_required_in_master_browser_flow(env, monkeypatch):
    kc = FakeKC()
    assert run(monkeypatch, kc) == 0
    assert kc.realm["browserFlow"] == "breakglass-browser"
    by_id = {e["id"]: e for e in kc.execs}
    assert by_id["e5"]["requirement"] == "REQUIRED"
    assert by_id["e7"]["requirement"] == "REQUIRED"
    # no CONDITIONAL execution may remain on the path to the OTP form
    assert not [e for e in kc.execs if e["requirement"] == "CONDITIONAL"]
    assert by_id["e6"]["requirement"] != "DISABLED"


def test_metrics_listener_added_idempotently(env, monkeypatch):
    kc = FakeKC()
    assert run(monkeypatch, kc) == 0
    assert kc.realm_events["eventsListeners"] == ["jboss-logging", "micrometer-user-event-metrics"]
    assert run(monkeypatch, kc) == 0
    assert kc.realm_events["eventsListeners"].count("micrometer-user-event-metrics") == 1


def test_missing_env_fails_without_leak(env, monkeypatch, capsys):
    monkeypatch.delenv("BREAKGLASS_2_PASSWORD")
    assert run(monkeypatch, FakeKC()) == 2
    assert "BREAKGLASS_2_PASSWORD" in capsys.readouterr().err


def test_same_usernames_rejected(env, monkeypatch):
    monkeypatch.setenv("BREAKGLASS_2_USERNAME", "bg-admin-1")
    assert run(monkeypatch, FakeKC()) == 2


def test_prometheusrule_alerts_on_master_logins():
    doc = yaml.safe_load((BG / "prometheusrule.yaml").read_text())
    rule = doc["spec"]["groups"][0]["rules"][0]
    assert 'realm="master"' in rule["expr"]
    assert 'event="login"' in rule["expr"] and "login_error" not in rule["expr"]
    assert rule["labels"]["team"] == "ops"
    assert rule["labels"]["notify"] == "security-officer"


def test_externalsecret_reads_openbao_only():
    doc = yaml.safe_load((BG / "externalsecret.yaml").read_text())
    keys = {d["secretKey"] for d in doc["spec"]["data"]}
    assert {"BREAKGLASS_1_PASSWORD", "BREAKGLASS_2_PASSWORD"} <= keys
    assert all(d["remoteRef"]["key"].startswith("kv/keycloak/") for d in doc["spec"]["data"])


def test_kustomization_and_metrics_env():
    base = BG.parent
    assert "breakglass" in (base / "kustomization.yaml").read_text()
    dep = (base / "deployment.yaml").read_text()
    assert "KC_EVENT_METRICS_USER_ENABLED" in dep
    assert "user-event-metrics" in dep and "KC_FEATURES" in dep
    assert "login_error" not in dep
