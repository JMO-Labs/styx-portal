"""CephCluster OSD encryption via Rook Vault KMS against OpenBao (issue #62)."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = ROOT / "deploy/enterprise/rook-ceph/cephcluster.yaml"
BAD = sorted((Path(__file__).parent / "fixtures/ceph_bad").glob("*.yaml"))

REQUIRED_KMS = {
    "KMS_PROVIDER": "vault",
    "VAULT_BACKEND_PATH": "rook",
    "VAULT_SECRET_ENGINE": "kv",
    "VAULT_BACKEND": "v2",
    "VAULT_AUTH_METHOD": "kubernetes",
    "VAULT_AUTH_KUBERNETES_ROLE": "rook-ceph",
}
CRON_FIELD = r"(\*|\d+(-\d+)?)(/\d+)?(,(\*|\d+(-\d+)?)(/\d+)?)*"
CRON = re.compile(rf"^{CRON_FIELD}( {CRON_FIELD}){{4}}$")


def _sets(s):
    return s.get("storage", {}).get("storageClassDeviceSets") or []


def check_all_device_sets_encrypted(s):
    sets = _sets(s)
    assert sets, "no storageClassDeviceSets"
    for ds in sets:
        assert ds.get("encrypted") is True, f"{ds.get('name')} not encrypted"


def check_block_pvcs(s):
    for ds in _sets(s):
        vcts = ds.get("volumeClaimTemplates") or []
        assert vcts, f"{ds.get('name')} has no volumeClaimTemplates"
        for v in vcts:
            assert v["spec"].get("volumeMode") == "Block"


def check_no_host_based(s):
    st = s.get("storage", {})
    assert not st.get("nodes"), "storage.nodes is host-based"
    assert st.get("useAllDevices") is not True
    assert _sets(s)


def check_kms(s):
    cd = s.get("security", {}).get("kms", {}).get("connectionDetails", {})
    for k, v in REQUIRED_KMS.items():
        assert cd.get(k) == v, k
    addr = cd.get("VAULT_ADDR", "")
    assert re.fullmatch(r"https://[a-z0-9-]+\.[a-z0-9-]+\.svc(\.cluster\.local)?(:\d+)?", addr)
    assert cd.get("VAULT_CACERT")
    assert cd.get("VAULT_TLS_SERVER_NAME")


def check_tls_and_no_token(s):
    kms = s.get("security", {}).get("kms", {})
    assert "tokenSecretName" not in kms
    text = yaml.safe_dump(s)
    assert "VAULT_SKIP_VERIFY" not in text
    assert "VAULT_TOKEN" not in text


def check_rotation(s):
    kr = s.get("security", {}).get("keyRotation", {})
    assert kr.get("enabled") is True
    assert CRON.match(str(kr.get("schedule", ""))), kr.get("schedule")


def check_no_auto_remove(s):
    assert s.get("removeOSDsIfOutAndSafeToRemove", False) is False
    assert s.get("storage", {}).get("removeOSDsIfOutAndSafeToRemove", False) is False


CHECKS = [
    check_all_device_sets_encrypted,
    check_block_pvcs,
    check_no_host_based,
    check_kms,
    check_tls_and_no_token,
    check_rotation,
    check_no_auto_remove,
]


def _spec():
    return yaml.safe_load(CLUSTER.read_text())["spec"]


def test_all_device_sets_encrypted():
    check_all_device_sets_encrypted(_spec())


def test_device_sets_use_block_pvcs():
    check_block_pvcs(_spec())


def test_no_host_based_osds():
    check_no_host_based(_spec())


def test_kms_uses_openbao_vault_provider():
    check_kms(_spec())
    cd = _spec()["security"]["kms"]["connectionDetails"]
    assert cd["VAULT_ADDR"] == "https://openbao.openbao.svc:8200"
    assert cd["VAULT_CACERT"] == "openbao-ca"
    assert cd["VAULT_TLS_SERVER_NAME"] == "openbao.openbao.svc"
    assert cd["VAULT_AUTH_MOUNT_PATH"] == "kubernetes"


def test_kms_tls_not_skipped():
    check_tls_and_no_token(_spec())


def test_key_rotation_enabled():
    check_rotation(_spec())
    assert _spec()["security"]["keyRotation"]["schedule"] == "0 2 1 * *"


def test_osds_not_auto_removed():
    check_no_auto_remove(_spec())


@pytest.mark.parametrize("bad", ["0 2 1 *", "x 2 1 * *", "", "0 2 1 * * *"])
def test_cron_validator_rejects_malformed(bad):
    with pytest.raises(AssertionError):
        check_rotation({"security": {"keyRotation": {"enabled": True, "schedule": bad}}})


EXPECTED = {
    "unencrypted_set": check_all_device_sets_encrypted,
    "host_nodes": check_no_host_based,
    "skip_verify": check_tls_and_no_token,
}


@pytest.mark.parametrize("fixture", BAD, ids=lambda p: p.stem)
def test_bad_fixtures_rejected(fixture):
    spec = yaml.safe_load(fixture.read_text())["spec"]
    with pytest.raises((AssertionError, KeyError)):
        EXPECTED[fixture.stem](spec)


def test_fixtures_present():
    assert {p.stem for p in BAD} >= {"unencrypted_set", "host_nodes", "skip_verify"}
