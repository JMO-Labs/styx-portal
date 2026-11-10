"""Static checks for the opt-in offsite export component (issue #13)."""

import re
from pathlib import Path

import yaml

K8S = Path(__file__).resolve().parents[2] / "deploy" / "k8s"
COMP = K8S / "offsite-export"
FILES = ["kustomization.yaml", "params.env", "offsite-export.sh", "externalsecret.yaml",
         "pv.yaml", "cronjob-export.yaml", "cronjob-verify.yaml", "networkpolicy.yaml",
         "prometheusrule.yaml"]


def _load(name):
    return [d for d in yaml.safe_load_all((COMP / name).read_text()) if d]


def _one(name, kind):
    (doc,) = [d for d in _load(name) if d["kind"] == kind]
    return doc


def _pod(name):
    return _one(name, "CronJob")["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def _params():
    out = {}
    for line in (COMP / "params.env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def test_component_files_exist():
    for f in FILES:
        assert (COMP / f).is_file(), f


def test_not_in_base_kustomization():
    assert "offsite-export" not in (K8S / "kustomization.yaml").read_text()


def test_export_cronjob_security():
    cj = _one("cronjob-export.yaml", "CronJob")
    assert cj["metadata"]["name"] == "styx-offsite-export"
    assert cj["spec"]["schedule"] == "30 4 * * *"
    assert cj["spec"]["concurrencyPolicy"] == "Forbid"
    pod = _pod("cronjob-export.yaml")
    (c,) = pod["containers"]
    sc = c["securityContext"]
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["capabilities"] == {"drop": ["ALL"], "add": ["DAC_READ_SEARCH"]}
    assert sc["seccompProfile"] == {"type": "RuntimeDefault"}
    assert "privileged" not in yaml.safe_dump(pod)
    (snap,) = [m for m in c["volumeMounts"] if m["name"] == "snapshots"]
    assert snap["readOnly"] is True
    (vol,) = [v for v in pod["volumes"] if v["name"] == "snapshots"]
    assert vol["persistentVolumeClaim"]["readOnly"] is True
    env = {e["name"]: e.get("value") for e in c.get("env", [])}
    for key in ("KOPIA_CONFIG_PATH", "KOPIA_CACHE_DIRECTORY", "KOPIA_LOG_DIR"):
        assert env[key].startswith("/work/"), key
    (work,) = [v for v in pod["volumes"] if v["name"] == "work"]
    assert "emptyDir" in work
    refs = [r for e in c["envFrom"] for r in e.values()]
    assert {"name": "styx-offsite-export"} in refs
    assert {"name": "styx-offsite-params"} in refs


def test_verify_cronjob_runs_verify_mode():
    exp = _one("cronjob-export.yaml", "CronJob")
    ver = _one("cronjob-verify.yaml", "CronJob")
    assert ver["metadata"]["name"] == "styx-offsite-verify"
    assert ver["spec"]["schedule"] == "30 10 * * *"
    assert ver["spec"]["schedule"] != exp["spec"]["schedule"]
    (c,) = _pod("cronjob-verify.yaml")["containers"]
    assert "verify" in c["args"]
    (e,) = _pod("cronjob-export.yaml")["containers"]
    assert "export" in e["args"]


def test_kopia_image_pinned():
    k = yaml.safe_load((COMP / "kustomization.yaml").read_text())
    (img,) = [i for i in k["images"] if i["name"].endswith("kopia/kopia")]
    assert img["newTag"] and img["newTag"] != "latest"


def test_params_defaults():
    p = _params()
    assert p["OFFSITE_CIPHER"] == "AES256-GCM-HMAC-SHA256"
    assert (p["OFFSITE_KEEP_DAILY"], p["OFFSITE_KEEP_WEEKLY"], p["OFFSITE_KEEP_MONTHLY"]) == (
        "30", "8", "12")
    assert p["OFFSITE_LOCK_DAYS"] == "35"
    # Kopia: lock must outlive the full-maintenance interval (7 d) by at least 1 d.
    assert int(p["OFFSITE_LOCK_DAYS"]) > 7 + 1
    assert p["OFFSITE_S3_PREFIX"] == "styx/"
    # Orphaned sources (deleted users) go once older than Kopia's keep-annual 3 horizon.
    assert p["OFFSITE_ORPHAN_DAYS"] == "1095"
    assert p["OFFSITE_SNAP_ROOT"] == "/snapshots"
    assert p["OFFSITE_SNAP_PREFIX"] == "nightly-"
    assert p["OFFSITE_VERIFY_PERCENT"] == "1"
    assert p["OFFSITE_FULL_VERIFY_DOW"] == "7"
    assert p["OFFSITE_S3_ENDPOINT"].endswith(".example.invalid")
    assert "OFFSITE_S3_BUCKET" in p and "OFFSITE_S3_REGION" in p


def test_externalsecret_keys_and_store():
    es = _one("externalsecret.yaml", "ExternalSecret")
    assert es["metadata"]["name"] == "styx-offsite-export"
    assert es["spec"]["target"]["name"] == "styx-offsite-export"
    assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    keys = [d["secretKey"] for d in es["spec"]["data"]]
    assert sorted(keys) == ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "KOPIA_PASSWORD"]
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {"backup/offsite/kopia"}


def test_no_secret_literals():
    for f in COMP.iterdir():
        text = f.read_text()
        assert not re.search(r"AKIA[0-9A-Z]{16}", text), f.name
        if f.suffix == ".yaml":
            for d in _load(f.name):
                if d["kind"] == "Secret":
                    assert not ({"data", "stringData"} & d.keys()), f.name


def test_prometheus_alerts():
    pr = _one("prometheusrule.yaml", "PrometheusRule")
    assert pr["metadata"]["name"] == "styx-offsite"
    rules = {r["alert"]: r["expr"] for g in pr["spec"]["groups"] for r in g["rules"]}
    assert set(rules) == {"StyxOffsiteExportFailed", "StyxOffsiteExportStale",
                          "StyxOffsiteVerifyFailed", "StyxOffsiteVerifyStale"}
    assert "93600" in rules["StyxOffsiteExportStale"]
    assert "absent(" in rules["StyxOffsiteExportStale"]
    assert "180000" in rules["StyxOffsiteVerifyStale"]
    assert 'styx-offsite-export.*' in rules["StyxOffsiteExportFailed"]


def test_networkpolicy_egress_only_dns_and_bucket():
    cnp = _one("networkpolicy.yaml", "CiliumNetworkPolicy")
    egress = cnp["spec"]["egress"]
    assert len(egress) == 2
    dns, bucket = egress
    assert dns["toEndpoints"][0]["matchLabels"]["k8s-app"] == "kube-dns"
    assert dns["toPorts"][0]["ports"][0]["port"] == "53"
    (fqdn,) = bucket["toFQDNs"]
    assert fqdn["matchName"].endswith(".example.invalid")
    assert bucket["toPorts"] == [{"ports": [{"port": "443", "protocol": "TCP"}]}]
    assert "world" not in yaml.safe_dump(cnp)


def test_pv_readonly_static_cephfs():
    docs = {d["kind"]: d for d in _load("pv.yaml")}
    pv, pvc = docs["PersistentVolume"], docs["PersistentVolumeClaim"]
    assert pv["spec"]["accessModes"] == ["ReadOnlyMany"]
    assert pvc["spec"]["accessModes"] == ["ReadOnlyMany"]
    csi = pv["spec"]["csi"]
    assert csi["driver"] == "cephfs.csi.ceph.com" and csi["readOnly"] is True
    assert csi["volumeAttributes"]["staticVolume"] == "true"
    assert {"clusterID", "fsName"} <= csi["volumeAttributes"].keys()
    assert csi["nodeStageSecretRef"]["name"] != "styx-offsite-export"
    assert pvc["spec"]["volumeName"] == pv["metadata"]["name"]


ROOT = K8S.parents[1]
ENT = ROOT / "docs" / "enterprise"


def _row(text, ctl):
    (line,) = [ln for ln in text.splitlines() if ln.startswith(f"| {ctl} |")]
    return line


def test_docs_and_compliance_records():
    page = (ROOT / "docs/operate/offsite-backup.md").read_text()
    for phrase in ("params.env", "offsite-export.sh init", "escrow", "change-password",
                   "retention", "D05", "D37", "restore", "pod-security"):
        assert phrase.lower() in page.lower(), phrase
    assert '"operate/offsite-backup.md"' in (ROOT / "zensical.toml").read_text()
    (adr37,) = (ENT / "adr").glob("0037-*.md")
    cons = adr37.read_text().split("## Consequences", 1)[1]
    for phrase in ("Kopia", "SC-13", "scrypt", "FIPS"):
        assert phrase in cons, phrase
    cm = (ENT / "control-matrix.md").read_text()
    for ctl in ("CP-6", "CP-9", "SC-28"):
        row = _row(cm, ctl)
        assert "deploy/k8s/offsite-export" in row and "IaC done, not deployed" in row, ctl
        assert row.rstrip().endswith("| Planned |"), ctl
    (adr11,) = (ENT / "adr").glob("0011-*.md")
    assert "- Status: Accepted\n" in adr11.read_text()


def test_docs_require_noncurrent_version_lifecycle():
    """Object Lock buckets are versioned: Kopia GC only adds delete markers (testing pass 3)."""
    page = (ROOT / "docs/operate/offsite-backup.md").read_text()
    for phrase in ("NoncurrentVersionExpiration", "ExpiredObjectDeleteMarker",
                   "mc ilm rule add", "--noncurrent-expire-days"):
        assert phrase in page, phrase
    deleted = page.split("## Deleted users", 1)[1].split("\n## ", 1)[0]
    assert "noncurrent" in deleted.lower()
    cost = page.split("## Cost check", 1)[1].split("\n## ", 1)[0]
    assert "lifecycle" in cost.lower()


def test_docs_bound_is_per_pack_and_rotation_erases():
    """Kopia GC drops only whole packs; shared live packs keep purged chunks (testing pass 4)."""
    page = (ROOT / "docs/operate/offsite-backup.md").read_text()
    deleted = page.split("## Deleted users", 1)[1].split("\n## ", 1)[0].lower()
    for phrase in ("whole pack", "shared", "escrowed key", "rotat", "crypto-shred",
                   "erase deadline"):
        assert phrase in deleted, phrase
    cost = page.split("## Cost check", 1)[1].split("\n## ", 1)[0].lower()
    assert "whole pack" in cost
