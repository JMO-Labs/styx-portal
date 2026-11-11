"""bao_configure.py against a fake `bao` (issue #4): env guards, idempotency, dry run."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.openbao_checks import OPENBAO

SCRIPT = OPENBAO / "bao_configure.py"
FAKEBIN = Path(__file__).parent / "fixtures/fakebin"
TOKEN = "s.SECRETVALUE"


def run(tmp_path, *args, state="empty", **env_over):
    log = tmp_path / "bao.log"
    log.touch()
    # Inherit the environment (setup-python needs LD_LIBRARY_PATH) minus any BAO_/VAULT_ vars.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BAO_", "VAULT_", "FAKE_"))}
    env |= {"PATH": f"{FAKEBIN}:{os.environ['PATH']}", "FAKE_LOG": str(log), "FAKE_STATE": state,
           "BAO_ADDR": "https://openbao-active.openbao.svc:8200",
           "BAO_CACERT": "/openbao/tls/ca.crt", "BAO_TOKEN": TOKEN}
    env.update(env_over)
    env = {k: v for k, v in env.items() if v is not None}
    res = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True,
                         text=True, timeout=30)
    return res, log.read_text().splitlines()


def policies() -> list[str]:
    return sorted(p.stem for p in (OPENBAO / "policies").glob("*.hcl"))


def roles() -> list[str]:
    return [r["name"] for r in json.loads((OPENBAO / "auth-roles.json").read_text())]


def test_refuses_without_addr_or_cacert(tmp_path):
    for missing in ("BAO_ADDR", "BAO_CACERT"):
        res, calls = run(tmp_path, **{missing: None})
        assert res.returncode != 0 and missing in res.stderr
        assert calls == []


def test_refuses_skip_verify(tmp_path):
    for value in ("1", "false", ""):
        res, calls = run(tmp_path, BAO_SKIP_VERIFY=value)
        assert res.returncode != 0 and "BAO_SKIP_VERIFY" in res.stderr
        assert calls == []


def test_fresh_cluster_applies_everything(tmp_path):
    res, calls = run(tmp_path)
    assert res.returncode == 0, res.stderr
    for want in ("secrets enable -path=kv kv-v2", "audit list -format=json",
                 "auth enable kubernetes",
                 "write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc"):
        assert want in calls, want
    for p in policies():
        assert sum(c.startswith(f"policy write {p} ") for c in calls) == 1, p
    for r in roles():
        assert sum(c.startswith(f"write auth/kubernetes/role/{r} ") for c in calls) == 1, r
    eso = next(c for c in calls if c.startswith("write auth/kubernetes/role/eso "))
    for part in ("bound_service_account_names=external-secrets",
                 "bound_service_account_namespaces=external-secrets", "policies=eso-read",
                 "token_ttl=3600"):
        assert part in eso.split(), part


def test_idempotent_second_run(tmp_path):
    res, calls = run(tmp_path, state="configured")
    assert res.returncode == 0, res.stderr
    assert not [c for c in calls if " enable " in f" {c} "]
    assert not [c for c in calls if c.startswith("write auth/kubernetes/config")]


def test_never_enables_audit_over_api(tmp_path):
    # OpenBao 2.7 refuses API-created audit devices; the stdout device is declared in the
    # server HCL (values.yaml) and the script only verifies it.
    for state in ("empty", "configured"):
        res, calls = run(tmp_path, state=state)
        assert res.returncode == 0, res.stderr
        assert not [c for c in calls if c.startswith("audit enable")]


def test_fails_when_stdout_audit_missing(tmp_path):
    res, calls = run(tmp_path, FAKE_AUDIT="none")
    assert res.returncode != 0 and "audit" in res.stderr
    assert not [c for c in calls if "enable" in c.split() or "write" in c.split()]


def test_extra_mounts_file(tmp_path):
    conf = tmp_path / "conf"
    shutil.copytree(OPENBAO / "policies", conf / "policies")
    shutil.copy(OPENBAO / "auth-roles.json", conf)
    (conf / "extra-mounts.json").write_text(json.dumps([{"path": "rook", "type": "kv-v2"}]))
    res, calls = run(tmp_path, "--dir", str(conf))
    assert res.returncode == 0, res.stderr
    assert "secrets enable -path=rook kv-v2" in calls
    assert "secrets enable -path=kv kv-v2" in calls


def test_shipped_extra_mounts_rook_only():
    assert json.loads((OPENBAO / "extra-mounts.json").read_text()) == [
        {"path": "rook", "type": "kv-v2"}]


def test_dry_run_no_writes(tmp_path):
    res, calls = run(tmp_path, "--dry-run")
    assert res.returncode == 0, res.stderr
    assert calls, "dry run should still read state"
    for c in calls:
        assert "write" not in c.split() and "enable" not in c.split(), c
    assert "bao secrets enable -path=kv kv-v2" in res.stdout
    assert "bao policy write eso-read" in res.stdout


def test_token_never_printed(tmp_path):
    for args in ((), ("--dry-run",)):
        res, _ = run(tmp_path, *args)
        assert res.returncode == 0, res.stderr
        assert TOKEN not in res.stdout and TOKEN not in res.stderr


def test_stdlib_only_and_short():
    src = SCRIPT.read_text()
    assert len(src.splitlines()) < 500
    imports = {ln.split()[1].split(".")[0] for ln in src.splitlines()
               if ln.startswith(("import ", "from "))}
    assert imports <= set(sys.stdlib_module_names) | {"__future__"}, imports


def test_roles_cap_token_max_ttl(tmp_path):
    # Without token_max_ttl a role token renews up to the system max (768h by default).
    res, calls = run(tmp_path)
    assert res.returncode == 0, res.stderr
    for r in json.loads((OPENBAO / "auth-roles.json").read_text()):
        call = next(c for c in calls if c.startswith(f"write auth/kubernetes/role/{r['name']} "))
        assert f"token_max_ttl={r['token_ttl']}" in call.split(), call


def test_refuses_plain_http_addr(tmp_path):
    res, calls = run(tmp_path, BAO_ADDR="http://openbao-active.openbao.svc:8200")
    assert res.returncode != 0 and "https" in res.stderr
    assert calls == []


def test_read_errors_are_not_missing_state(tmp_path):
    # 403, TLS and connection errors also exit 2; they must surface, not read as "absent".
    for state, cause in (("denied", "permission denied"), ("tls", "x509"),
                         ("down", "connection refused")):
        for args in ((), ("--dry-run",)):
            res, calls = run(tmp_path, *args, state=state)
            assert res.returncode != 0, (state, args)
            assert cause in res.stderr, (state, res.stderr)
            assert "declare audit" not in res.stderr, res.stderr
            assert not [c for c in calls if "enable" in c.split() or "write" in c.split()]
            assert "enable" not in res.stdout and "write" not in res.stdout, (state, res.stdout)


def test_unreadable_k8s_config_is_not_overwritten(tmp_path):
    # Token may list mounts but not read auth/kubernetes/config: die, never blind-overwrite.
    res, calls = run(tmp_path, state="configured", FAKE_CONFIG="denied")
    assert res.returncode != 0 and "permission denied" in res.stderr
    assert "auth/kubernetes/config failed" in res.stderr, res.stderr
    assert not [c for c in calls if c.startswith("write auth/kubernetes/config")]


# ---- GitLab CI JWT auth (issue #10) -----------------------------------------------------

ISSUER = "https://gitlab.example.internal"


def jwt_role_write(calls: list[str], name: str = "gitlab-mirror") -> dict:
    (call,) = [c for c in calls if c.startswith(f"write auth/jwt/role/{name} - ")]
    return json.loads(call.split(" - ", 1)[1])


def test_jwt_skipped_without_issuer(tmp_path):
    for state in ("empty", "configured"):
        res, calls = run(tmp_path, state=state)
        assert res.returncode == 0, res.stderr
        assert not [c for c in calls if "jwt" in c], calls


def test_jwt_enabled_and_role_written(tmp_path):
    res, calls = run(tmp_path, BAO_GITLAB_JWT_ISSUER=ISSUER)
    assert res.returncode == 0, res.stderr
    assert "auth enable jwt" in calls
    assert (f"write auth/jwt/config bound_issuer={ISSUER} oidc_discovery_url={ISSUER}"
            in calls)
    role = jwt_role_write(calls)
    want = json.loads((OPENBAO / "jwt-roles.json").read_text())[0]
    assert role["role_type"] == "jwt"
    assert role["bound_claims"] == want["bound_claims"]
    assert role["bound_claims"]["ref_protected"] == "true"
    assert role["token_policies"] == ["gitlab-mirror"]
    assert role["token_ttl"] == role["token_max_ttl"] == want["token_ttl"] <= 900
    assert jwt_role_write(calls, "gitlab-protect")["token_policies"] == ["gitlab-protect"]


def test_jwt_idempotent(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _, first = run(tmp_path / "a", BAO_GITLAB_JWT_ISSUER=ISSUER)
    roles = tmp_path / "roles"
    roles.mkdir()
    for r in json.loads((OPENBAO / "jwt-roles.json").read_text()):
        (roles / f"{r['name']}.json").write_text(
            json.dumps({"data": jwt_role_write(first, r["name"])}))
    res, calls = run(tmp_path / "b", state="configured", BAO_GITLAB_JWT_ISSUER=ISSUER,
                     FAKE_JWT_ROLES=str(roles))
    assert res.returncode == 0, res.stderr
    assert not [c for c in calls if "jwt" in c and ("write" in c.split() or "enable" in c)]


def test_jwt_refuses_http_issuer(tmp_path):
    res, calls = run(tmp_path, BAO_GITLAB_JWT_ISSUER="http://gitlab.example.internal")
    assert res.returncode != 0 and "BAO_GITLAB_JWT_ISSUER" in res.stderr
    assert calls == []
