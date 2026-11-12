"""Realm-as-code checks for deploy/enterprise/keycloak/realm (issue #129, ADR-0015/0016/0026/0051)."""

import json
from pathlib import Path

import yaml

KC = Path(__file__).resolve().parents[2] / "deploy/enterprise/keycloak"
REALM_FILE = KC / "realm/styx-realm.json"


def realm():
    return json.loads(REALM_FILE.read_text())


def test_realm_imported_by_kustomization():
    k = yaml.safe_load((KC / "kustomization.yaml").read_text())
    gens = k["configMapGenerator"]
    assert any(REALM_FILE.name in str(f) for g in gens for f in g.get("files", []))
    dep = next(d for d in yaml.safe_load_all((KC / "deployment.yaml").read_text())
               if d and d["kind"] == "Deployment")
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert "--import-realm" in c["args"]
    assert any(m["mountPath"] == "/opt/keycloak/data/import" for m in c["volumeMounts"])


def _flows():
    r = realm()
    return {f["alias"]: f for f in r["authenticationFlows"]}


def _reachable_executions(alias, flows, seen=None):
    out = []
    for e in flows[alias]["authenticationExecutions"]:
        if e.get("authenticator"):
            out.append(e["authenticator"])
        if e.get("flowAlias"):
            out += _reachable_executions(e["flowAlias"], flows)
    return out


def test_browser_flow_x509_only():
    r, flows = realm(), _flows()
    assert r["registrationAllowed"] is False
    assert r["browserFlow"] == "x509-browser"
    auths = _reachable_executions("x509-browser", flows)
    assert auths == ["auth-x509-client-username-form"]
    bad = {"auth-username-password-form", "auth-otp-form", "registration-page-form",
           "registration-user-creation", "registration-password-action",
           "webauthn-authenticator", "auth-cookie", "identity-provider-redirector"}
    assert not bad & set(auths)
    assert r["registrationFlow"] not in flows or not flows[r["registrationFlow"]]["authenticationExecutions"]
    assert not r.get("resetPasswordAllowed")
    assert not r.get("rememberMe")
    assert r["directGrantFlow"] != "direct grant"
    assert not flows[r["directGrantFlow"]]["authenticationExecutions"] or \
        _reachable_executions(r["directGrantFlow"], flows) == ["deny-access-authenticator"]


def test_x509_config_uses_card_key_attribute():
    r, flows = realm(), _flows()
    ex = flows["x509-browser"]["authenticationExecutions"][0]
    cfg = next(c for c in r["authenticatorConfig"] if c["alias"] == ex["authenticatorConfig"])["config"]
    assert cfg["x509-cert-auth.mapper-selection.user-attribute-name"] == "cardKey"
    assert cfg["x509-cert-auth.mapper-selection"] == "Custom Attribute Mapper"
    assert cfg["x509-cert-auth.mapper-selection.user-attribute-name"] == "cardKey"
    assert ex["requirement"] == "REQUIRED"


def test_card_key_attribute_read_only_for_users():
    up = json.loads(REALM_FILE.read_text())["components"][
        "org.keycloak.userprofile.UserProfileProvider"][0]["config"]["kc.user.profile.config"]
    attrs = {a["name"]: a for a in json.loads(up[0])["attributes"]}
    perms = attrs["cardKey"]["permissions"]
    assert perms["edit"] == ["admin"]
    assert "user" not in perms["view"] or "user" not in perms["edit"]


def test_admin_roles():
    names = {x["name"] for x in realm()["roles"]["realm"]}
    assert {"platform-admin", "help-desk", "auditor", "group-manager"} <= names


def test_styx_client():
    c = next(c for c in realm()["clients"] if c["clientId"] == "styx")
    assert c["publicClient"] is False and c["standardFlowEnabled"] is True
    assert c["directAccessGrantsEnabled"] is False
    assert "secret" not in c
    m = next(m for m in c["protocolMappers"] if m["protocolMapper"] == "oidc-group-membership-mapper")
    assert m["config"]["claim.name"] == "groups"
    assert m["config"]["id.token.claim"] == "true"
    assert m["config"]["userinfo.token.claim"] == "true"
    assert m["config"]["full.path"] == "false"


def test_no_secrets_in_realm():
    text = REALM_FILE.read_text().lower()
    assert '"secret"' not in text and '"credentials"' not in text
