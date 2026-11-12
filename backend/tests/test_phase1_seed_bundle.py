"""Phase 1 seed bundle: lock check, scripts, Job manifest, docs (issue #25)."""

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "deploy" / "enterprise" / "images"
spec = importlib.util.spec_from_file_location("chk", ROOT / "scripts" / "check_phase1_lock.py")
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)

D = "sha256:" + "a" * 64


def test_committed_lock_is_digest_only_and_subset_of_images():
    assert chk.check((IMG / "phase1.lock").read_text(), (IMG / "phase1.images").read_text()) == []


@pytest.mark.parametrize("line", ["docker.io/x/y:1.0", "docker.io/x/y", "docker.io/x/y@sha256:abc",
                                  "docker.io/x/y:1@sha256:" + "A" * 64, "docker.io/x/y@PLACEHOLDER"])
def test_tag_only_or_bad_refs_fail(line):
    assert chk.check(line + "\n", "docker.io/x/y:1\n")


def test_unknown_repo_in_lock_fails():
    assert chk.check(f"docker.io/z/z@{D}\n", "docker.io/x/y:1\n")


def test_empty_lock_fails():
    assert chk.check("# only comments\n", "docker.io/x/y:1\n")


def test_strict_requires_full_coverage():
    assert chk.check(f"docker.io/x/y@{D}\n", "docker.io/x/y:1\ndocker.io/x/w:2\n") == []
    assert chk.check(f"docker.io/x/y@{D}\n", "docker.io/x/y:1\ndocker.io/x/w:2\n", strict=True)


def test_images_cover_phase1_components():
    txt = (IMG / "phase1.images").read_text()
    for needle in ("goharbor/harbor-core", "rook/ceph", "ceph/ceph", "cloudnative-pg/postgresql",
                   "openbao/openbao", "external-secrets/external-secrets", "traefik"):
        assert needle in txt


def test_scripts_exist_and_parse():
    for s in ("build_seed_bundle.sh", "resolve_phase1_digests.sh"):
        p = ROOT / "scripts" / s
        assert p.stat().st_mode & 0o100
        assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    b = (ROOT / "scripts" / "build_seed_bundle.sh").read_text()
    assert "oci-archive:" in b and "check_phase1_lock.py" in b and "--strict" in b


def test_kind_spike_imports_archive_and_checks_digests():
    p = ROOT / "scripts" / "kind" / "10-seed-bundle-import.sh"
    assert p.stat().st_mode & 0o100
    t = p.read_text()
    assert "crictl images --digests" in t and "phase1.lock" in t


def test_harbor_push_job_manifest():
    t = (ROOT / "deploy/enterprise/harbor/seed-push-job.yaml").read_text()
    assert "kind: Job" in t and "phase1.lock" in t and "skopeo" in t
    assert "runAsNonRoot: true" in t and "allowPrivilegeEscalation: false" in t
    assert not re.search(r"(?i)password:\s*\S", t)


def test_airgap_todo_closed_and_runbook_references_bundle():
    assert "TODO" not in (ROOT / "deploy/rke2/inventory/group_vars/all.yml").read_text().split("rke2_airgap_mode")[1].splitlines()[0]
    readme = (ROOT / "deploy/rke2/README.md").read_text()
    assert "`rke2_airgap_mode: false` for now" not in readme and "phase1.lock" in readme
    assert "rke2_airgap_mode: true" in (ROOT / "deploy/rke2/inventory/group_vars/all.yml").read_text()
    rb = (ROOT / "docs/enterprise/runbooks/full-site-restore.md").read_text()
    step5 = rb.split("### Step 5: Images and Harbor")[1].split("### Step 6")[0]
    assert "phase1.lock" in step5 and "seed bundle" in step5.lower()
