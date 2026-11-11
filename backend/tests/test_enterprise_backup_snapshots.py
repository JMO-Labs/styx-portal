"""Nightly CephFS home snapshot CronJob and script (issue #38)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.backup_checks import BACKUP, NIGHTLY, check_cronjob, check_no_ceph_admin, load_docs

SCRIPT = BACKUP / "home-snapshots.sh"
TODAY = "nightly-2026-11-11"

FAKE_CEPH = r"""#!/usr/bin/env bash
echo "$*" >>"$CALLS"
group=""; args=("$@")
for i in "${!args[@]}"; do [[ "${args[$i]}" == --group_name ]] && group="${args[$((i+1))]}"; done
if [[ "$*" == "fs subvolume ls "* ]]; then
  list="$(cat "$STATE/subs.$group" 2>/dev/null || true)"
  printf '['; sep=""; for s in $list; do printf '%s{"name": "%s"}' "$sep" "$s"; sep=", "; done; printf ']\n'
elif [[ "$*" == "fs subvolume snapshot ls "* ]]; then
  f="$STATE/snaps.$group.$6"; printf '['; sep=""
  if [[ -f $f ]]; then while read -r s; do printf '%s{"name": "%s"}' "$sep" "$s"; sep=", "; done <"$f"; fi
  printf ']\n'
elif [[ "$*" == "fs subvolume snapshot create "* ]]; then
  [[ " ${FAIL:-} " == *" $6 "* ]] && { echo "secret-key-material" >&2; exit 1; }
  echo "$7" >>"$STATE/snaps.$group.$6"
elif [[ "$*" == "fs subvolume snapshot rm "* ]]; then
  f="$STATE/snaps.$group.$6"; grep -vx "$7" "$f" >"$f.new" || true; mv "$f.new" "$f"
fi
"""


@pytest.fixture
def env(tmp_path):
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    (bin_dir / "ceph").write_text(FAKE_CEPH)
    (bin_dir / "date").write_text('#!/bin/sh\necho 2026-11-11\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    calls = tmp_path / "calls"
    calls.touch()
    (state / "subs.homes").write_text("alice bob\n")
    (state / "subs.profiles").write_text("alice bob\n")
    base = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls),
            "STATE": str(state), "FS_NAME": "fs0", "GROUPS": "homes profiles", "KEEP_DAILY": "7"}
    base.pop("MON_HOSTS", None)
    return base, state, calls


def run(env_):
    return subprocess.run(["bash", str(SCRIPT)], env=env_[0], capture_output=True, text=True)


def lines(calls: Path, verb: str) -> list[str]:
    return [ln for ln in calls.read_text().splitlines() if f"snapshot {verb} " in ln]


def cj() -> dict:
    (doc,) = load_docs(BACKUP / "home-snapshots-cronjob.yaml")
    return doc


def test_cronjob_spec():
    c = cj()
    assert c["metadata"] == {"name": "styx-home-snapshots", "namespace": "styx-backup"}
    assert c["spec"]["schedule"] == "0 3 * * *"
    assert check_cronjob(c) == []
    (cm,) = load_docs(BACKUP / "home-snapshots-params.yaml")
    assert cm["metadata"]["name"] == "styx-home-snapshots"
    assert cm["data"]["FS_NAME"] == "CHANGE-ME-fs"
    assert cm["data"]["GROUPS"] == "homes profiles" and cm["data"]["KEEP_DAILY"] == "7"


def test_dedicated_client_not_admin():
    (client,) = load_docs(BACKUP / "home-snapshots-client.yaml")
    assert client["kind"] == "CephClient"
    secret = cj()["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"][1]["secret"]
    assert secret["secretName"] == f"rook-ceph-client-{client['metadata']['name']}"
    for f in BACKUP.glob("*.yaml"):
        assert check_no_ceph_admin(f.read_text()) == [], f.name


def test_kustomization_generates_script():
    k = yaml.safe_load((BACKUP / "kustomization.yaml").read_text())
    gen = {g["name"]: g["files"] for g in k["configMapGenerator"]}
    assert gen["styx-home-snapshots-script"] == ["home-snapshots.sh"]
    assert SCRIPT.read_text().splitlines()[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in SCRIPT.read_text()


def test_networkpolicy_default_deny_and_ceph_ports():
    docs = load_docs(BACKUP / "networkpolicy.yaml")
    deny = next(d for d in docs if d["spec"]["podSelector"] == {})
    assert set(deny["spec"]["policyTypes"]) == {"Ingress", "Egress"} and "egress" not in deny["spec"]
    ports = {(p["port"], p.get("endPort")) for d in docs for r in d["spec"].get("egress", [])
             for p in r["ports"]}
    assert {(53, None), (3300, None), (6789, None), (6800, 7300)} == ports
    assert "placeholder" in (BACKUP / "networkpolicy.yaml").read_text().lower()


def test_creates_dated_snapshots(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    creates = lines(env[2], "create")
    assert len(creates) == 4
    for ln in creates:
        assert NIGHTLY.match(ln.split()[6])
        assert ln.split()[6] == TODAY
        assert "--group_name" in ln


def test_idempotent(env):
    assert run(env).returncode == 0
    assert run(env).returncode == 0
    assert len(lines(env[2], "create")) == 4


def test_prunes_only_nightly(env):
    _, state, calls = env
    days = [f"nightly-2026-11-{d:02d}" for d in range(3, 12)]
    (state / "subs.profiles").write_text("")
    (state / "subs.homes").write_text("alice\n")
    (state / "snaps.homes.alice").write_text(
        "\n".join(days + ["manual-x", "scheduled-2026-11-10-03_00_00_UTC"]) + "\n")
    assert run(env).returncode == 0
    removed = [ln.split()[6] for ln in lines(calls, "rm")]
    # 9 nightly incl. today, keep 7 -> remove the 2 oldest; no new create
    assert not [c for c in lines(calls, "create") if "alice" in c]
    assert removed == days[:2]
    assert "manual-x" not in removed and not any(s.startswith("scheduled") for s in removed)


def test_partial_failure_continues(env):
    e = ({**env[0], "FAIL": "alice"}, env[1], env[2])
    r = run(e)
    assert r.returncode != 0
    assert "homes/alice" in r.stderr and "profiles/alice" in r.stderr
    assert "secret-key-material" not in r.stdout + r.stderr
    created = [ln.split()[5] for ln in lines(env[2], "create")]
    assert created.count("bob") == 2


def test_empty_group_no_calls(env):
    e = ({**env[0], "GROUPS": "empty"}, env[1], env[2])
    r = run(e)
    assert r.returncode == 0, r.stderr
    assert lines(env[2], "create") == [] and lines(env[2], "rm") == []


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_shellcheck():
    r = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
