"""CRL mirror, alert and fail-closed revocation for Keycloak (issue #130, ADR-0017)."""

import datetime as dt
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

KC = Path(__file__).resolve().parents[2] / "deploy/enterprise/keycloak"
CRL = KC / "crl-mirror"
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def load():
    spec = importlib.util.spec_from_file_location("crl_mirror", CRL / "crl_mirror.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def docs(name):
    return [d for d in yaml.safe_load_all((CRL / name).read_text()) if d]


def make_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(NOW - dt.timedelta(days=30))
            .not_valid_after(NOW + dt.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    return key, cert


def make_crl(next_update, revoked=()):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    key, ca = make_ca()
    b = (x509.CertificateRevocationListBuilder().issuer_name(ca.subject)
         .last_update(NOW - dt.timedelta(days=1)).next_update(next_update))
    for serial in revoked:
        b = b.add_revoked_certificate(
            x509.RevokedCertificateBuilder().serial_number(serial)
            .revocation_date(NOW - dt.timedelta(hours=1)).build())
    return b.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


# --- decision: fail closed -------------------------------------------------

def test_refuse_when_ocsp_down_and_crl_stale():
    m = load()
    der = make_crl(NOW - dt.timedelta(hours=1))
    assert m.decide(ocsp="unreachable", crl_der=der, serial=42, now=NOW) == "refuse"


def test_allow_with_fresh_crl_when_ocsp_down():
    m = load()
    der = make_crl(NOW + dt.timedelta(days=3))
    assert m.decide(ocsp="unreachable", crl_der=der, serial=42, now=NOW) == "allow"


def test_refuse_revoked_even_if_fresh():
    m = load()
    der = make_crl(NOW + dt.timedelta(days=3), revoked=[42])
    assert m.decide(ocsp="unreachable", crl_der=der, serial=42, now=NOW) == "refuse"


def test_refuse_when_no_crl():
    assert load().decide(ocsp="unreachable", crl_der=None, serial=42, now=NOW) == "refuse"


def test_ocsp_good_allows_even_with_stale_crl():
    m = load()
    der = make_crl(NOW - dt.timedelta(hours=1))
    assert m.decide(ocsp="good", crl_der=der, serial=42, now=NOW) == "allow"


def test_ocsp_revoked_refuses():
    m = load()
    der = make_crl(NOW + dt.timedelta(days=3))
    assert m.decide(ocsp="revoked", crl_der=der, serial=42, now=NOW) == "refuse"


# --- mirror script ---------------------------------------------------------

def test_next_update_parsed():
    nu = NOW + dt.timedelta(days=3)
    got = load().next_update(make_crl(nu))
    assert got == nu


def test_mirror_writes_atomically_and_metrics(tmp_path):
    m = load()
    nu = NOW + dt.timedelta(days=2)
    der = make_crl(nu)
    out = tmp_path / "crl"
    prom = tmp_path / "prom"
    out.mkdir()
    prom.mkdir()
    rc = m.run({"ca1": "http://x/ca1.crl"}, out, prom, fetch=lambda u: der, now=NOW)
    assert rc == 0
    assert (out / "ca1.crl").read_bytes() == der
    assert not list(out.glob("*.tmp*"))
    txt = (prom / "crl_mirror.prom").read_text()
    assert f'crl_next_update_timestamp_seconds{{crl="ca1"}} {int(nu.timestamp())}' in txt
    assert f"crl_mirror_last_success_timestamp_seconds {int(NOW.timestamp())}" in txt


def test_mirror_failure_keeps_old_file_and_fails(tmp_path):
    m = load()
    out, prom = tmp_path / "crl", tmp_path / "prom"
    out.mkdir()
    prom.mkdir()
    (out / "ca1.crl").write_bytes(b"old")

    def boom(url):
        raise OSError("down")

    assert m.run({"ca1": "http://x"}, out, prom, fetch=boom, now=NOW) == 1
    assert (out / "ca1.crl").read_bytes() == b"old"


def test_mirror_rejects_garbage(tmp_path):
    m = load()
    out, prom = tmp_path / "crl", tmp_path / "prom"
    out.mkdir()
    prom.mkdir()
    assert m.run({"ca1": "http://x"}, out, prom, fetch=lambda u: b"<html>", now=NOW) == 1
    assert not (out / "ca1.crl").exists()


# --- manifests -------------------------------------------------------------

def test_cronjob_and_pvc():
    (cj,) = [d for d in docs("cronjob.yaml") if d["kind"] == "CronJob"]
    assert cj["spec"]["concurrencyPolicy"] == "Forbid"
    pod = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    vols = {v["name"]: v for v in pod["volumes"]}
    assert vols["crl"]["persistentVolumeClaim"]["claimName"] == "keycloak-crl"
    assert any(d["kind"] == "PersistentVolumeClaim" and d["metadata"]["name"] == "keycloak-crl"
               for d in docs("pvc.yaml"))


def test_keycloak_mounts_crl_readonly():
    dep = next(d for d in yaml.safe_load_all((KC / "deployment.yaml").read_text())
               if d and d["kind"] == "Deployment")
    pod = dep["spec"]["template"]["spec"]
    c = pod["containers"][0]
    mount = next(v for v in c["volumeMounts"] if v["name"] == "crl")
    assert mount["readOnly"] is True and mount["mountPath"] == "/opt/keycloak/crl"
    assert any(v.get("persistentVolumeClaim", {}).get("claimName") == "keycloak-crl"
               for v in pod["volumes"])


def test_alert_rules():
    (rule,) = docs("prometheusrule.yaml")
    rules = {r["alert"]: r for g in rule["spec"]["groups"] for r in g["rules"]}
    stale = rules["KeycloakCRLStale"]["expr"]
    assert "crl_next_update_timestamp_seconds" in stale and "time()" in stale
    (cj,) = [d for d in docs("cronjob.yaml") if d["kind"] == "CronJob"]
    assert cj["spec"]["schedule"] == "0 */6 * * *"
    missed = rules["KeycloakCRLMirrorNotSucceeding"]["expr"]
    assert "crl_mirror_last_success_timestamp_seconds" in missed and "43200" in missed


def test_realm_x509_fail_closed():
    realm = json.loads((KC / "realm/styx-realm.json").read_text())
    cfg = next(c for c in realm["authenticatorConfig"] if c["alias"] == "x509-card-key")["config"]
    assert cfg["x509-cert-auth.ocsp-checking-enabled"] == "true"
    assert cfg["x509-cert-auth.ocsp-fail-open"] == "false"
    assert cfg["x509-cert-auth.crl-checking-enabled"] == "true"
    assert cfg["x509-cert-auth.crl-relative-path"].startswith("/opt/keycloak/crl/")


def test_kustomization_includes_crl_files():
    res = yaml.safe_load((KC / "kustomization.yaml").read_text())["resources"]
    for f in ("cronjob.yaml", "pvc.yaml", "prometheusrule.yaml"):
        assert f"crl-mirror/{f}" in res
    gens = yaml.safe_load((KC / "kustomization.yaml").read_text())["configMapGenerator"]
    assert any("crl_mirror.py" in str(f) for g in gens for f in g.get("files", []))


def test_kustomize_build():
    import subprocess
    if not shutil.which("kustomize"):
        pytest.skip("kustomize not installed")
    subprocess.run(["kustomize", "build", str(KC)], check=True, capture_output=True)
