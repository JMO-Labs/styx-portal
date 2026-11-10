"""Seal-key Ansible playbook structure (issue #4, C1): place, never generate, never log."""

import yaml

from tests.openbao_checks import OPENBAO

PLAYBOOK = OPENBAO / "ansible/seal-key.yml"
# Chart defaults for openbao/openbao 0.30.7 (server.uid / server.gid), overridable per inventory.
UID = "{{ openbao_uid | default(100) }}"
GID = "{{ openbao_gid | default(1000) }}"


def play() -> dict:
    (p,) = yaml.safe_load(PLAYBOOK.read_text())
    return p


def tasks() -> list[dict]:
    return play()["tasks"]


def touches_key(task: dict) -> bool:
    text = yaml.safe_dump(task)
    return "openbao_seal_key_src" in text or ".key" in text


def module(task: dict, name: str) -> dict | None:
    return task.get(f"ansible.builtin.{name}")


def test_hosts_masters():
    assert play()["hosts"] == "masters"


def test_key_tasks_no_log():
    keyed = [t for t in tasks() if touches_key(t)]
    assert keyed
    for t in keyed:
        assert t.get("no_log") is True, t["name"]


def test_key_mode_0400_dir_0500():
    files = [module(t, "file") for t in tasks() if module(t, "file")]
    by_path = {f["path"]: f for f in files}
    assert by_path["/etc/openbao/seal"]["mode"] == "0500"
    assert by_path["/var/lib/openbao/raft"]["mode"] == "0700"
    for f in by_path.values():
        assert f["state"] == "directory"
        assert f["owner"] == UID and f["group"] == GID
    (copy,) = [module(t, "copy") for t in tasks() if module(t, "copy")]
    assert copy["mode"] == "0400"
    assert copy["dest"] == "/etc/openbao/seal/{{ openbao_seal_key_id }}.key"
    assert copy["src"] == "{{ openbao_seal_key_src }}"
    assert copy["owner"] == UID and copy["group"] == GID
    # Play vars outrank inventory vars; the uid/gid defaults live in the filter instead.
    assert "vars" not in play()


def test_stat_follows_symlinked_key_src():
    (stat,) = [module(t, "stat") for t in tasks() if module(t, "stat")]
    assert stat["follow"] is True


def test_asserts_32_bytes_and_required_src():
    asserts = [module(t, "assert") for t in tasks() if module(t, "assert")]
    conds = " ".join(c for a in asserts for c in a["that"])
    assert "openbao_seal_key_src is defined" in conds
    assert "openbao_seal_key_id is defined" in conds
    assert "== 32" in conds
    # The checks run before anything is written to the nodes.
    names = [next(iter(k for k in t if k.startswith("ansible.builtin."))) for t in tasks()]
    first_write = min(i for i, n in enumerate(names) if n.endswith(("file", "copy")))
    last_assert = max(i for i, n in enumerate(names) if n.endswith("assert"))
    assert last_assert < first_write


def test_never_generates_key():
    text = PLAYBOOK.read_text()
    for bad in ("openssl rand", "/dev/urandom", "community.crypto"):
        assert bad not in text, bad
