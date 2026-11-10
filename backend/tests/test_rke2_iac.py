"""Static checks for the RKE2 node IaC under deploy/rke2 (issue #2)."""

import ipaddress
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "rke2"
INV = ROOT / "inventory"
FILES = [
    "ansible.cfg", "requirements.yml", "site.yml", "inventory/hosts.example.yml",
    "inventory/group_vars/all.yml", "inventory/group_vars/masters.yml",
    "inventory/group_vars/workers.yml", ".yamllint", ".ansible-lint", "README.md",
]
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
TOKEN_LOOKUP = "{{ lookup('env', 'RKE2_TOKEN') }}"
SECRET_LINE = re.compile(r"^\s*-?\s*[\w.-]*(token|password)\s*:\s*(.*)$", re.I)


def _load(rel):
    return yaml.safe_load((ROOT / rel).read_text())


def _vars(group):
    return _load(f"inventory/group_vars/{group}.yml")


def _hosts(group):
    return _load("inventory/hosts.example.yml")["all"]["children"][group]["hosts"]


def _has_literal_secret(line: str) -> bool:
    if "defaultSecret12345" in line:
        return True
    m = SECRET_LINE.match(line)
    if not m:
        return False
    value = m.group(2).strip().strip("'\"")
    is_jinja = value.startswith("{{") and value.endswith("}}")
    return bool(value) and not is_jinja and not value.startswith("!vault")


def _tracked_files():
    assert ROOT.is_dir(), ROOT
    # roles/, collections/ and .ansible/ hold installed upstream deps (gitignored).
    return [p for p in ROOT.rglob("*")
            if p.is_file() and not {"roles", "collections", ".ansible"} & set(p.relative_to(ROOT).parts)]


def test_required_files_exist():
    missing = [f for f in FILES if not (ROOT / f).is_file()]
    assert not missing


def test_role_pinned_exactly():
    roles = {r["name"]: r for r in _load("requirements.yml")["roles"]}
    assert roles["lablabs.rke2"]["version"] == "1.54.0"


def test_inventory_topology():
    masters, workers = _hosts("masters"), _hosts("workers")
    assert len(masters) == 3
    assert len(workers) == 8
    assert not set(masters) & set(workers)


def test_inventory_uses_placeholder_ips():
    hosts = {**_hosts("masters"), **_hosts("workers")}
    ips = [h["ansible_host"] for h in hosts.values()] + [_vars("all")["rke2_api_ip"]]
    for ip in ips:
        assert any(ipaddress.ip_address(ip) in n for n in DOC_NETS), ip


def test_rke2_version_pinned():
    v = _vars("all")
    m = re.fullmatch(r"v1\.(\d+)\.\d+\+rke2r\d+", v["rke2_version"])
    assert m and int(m.group(1)) >= 34
    assert v["rke2_version"] not in ("latest", "stable")
    assert v["rke2_allow_downgrade"] is False


def test_cis_profile_and_apiserver_arg():
    v = _vars("all")
    assert v["rke2_cis_profile"] == "cis"
    assert "service-account-extend-token-expiration=false" in v["rke2_kube_apiserver_args"]


def test_ha_keepalived_not_kubevip():
    v = _vars("all")
    assert v["rke2_ha_mode"] is True
    assert v["rke2_ha_mode_keepalived"] is True
    assert v["rke2_ha_mode_kubevip"] is False
    sans = v["rke2_additional_sans"]
    assert v["rke2_api_ip"] in sans
    assert any(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", s) and not s[0].isdigit() for s in sans)


def test_cni_cilium_and_no_bundled_ingress():
    v = _vars("all")
    assert v["rke2_cni"] == ["cilium"]
    assert v["rke2_ingress_controller"] == "none"


def test_server_taint_and_worker_labels():
    assert _vars("masters")["rke2_server_node_taints"] == ["CriticalAddonsOnly=true:NoExecute"]
    labels = _vars("workers")["k8s_node_label"]
    assert {"node.kubernetes.io/worker=true", "styx.io/gpu-ready=true"} <= set(labels)
    # kubelet/NodeRestriction refuse node-role.kubernetes.io/* in --node-labels; agents would not register.
    assert not any(lbl.startswith("node-role.kubernetes.io/") for lbl in labels)


def test_token_from_env_only():
    assert _vars("all")["rke2_token"] == TOKEN_LOOKUP


def test_secret_helper_catches_planted_values():
    assert _has_literal_secret("rke2_token: abc123") is True
    assert _has_literal_secret("  password: 'hunter2'") is True
    assert _has_literal_secret("x: defaultSecret12345") is True
    assert _has_literal_secret('"rke2_token": abc123') is True
    assert _has_literal_secret("'password': hunter2") is True
    assert _has_literal_secret(f'rke2_token: "{TOKEN_LOOKUP}"') is False
    assert _has_literal_secret("password: !vault |") is False


def test_no_literal_secrets_committed():
    bad = [f"{p.relative_to(ROOT)}: {line}" for p in _tracked_files()
           for line in p.read_text().splitlines() if _has_literal_secret(line)]
    assert not bad


def test_site_asserts_token_present():
    (play,) = _load("site.yml")
    assert play["hosts"] == "masters:workers"
    roles = [r["role"] if isinstance(r, dict) else r for r in play["roles"]]
    assert roles == ["lablabs.rke2"]
    (task,) = [t for t in play["pre_tasks"] if "ansible.builtin.assert" in t]
    conds = task["ansible.builtin.assert"]["that"]
    # trim: a whitespace-only RKE2_TOKEN renders as a null token and each server mints its own.
    assert "rke2_token | trim | length > 0" in conds
    assert "rke2_token != 'defaultSecret12345'" in conds
    # always: --tags runs must not skip the guard.
    assert "always" in task["tags"]


def test_no_kube_proxy_or_cilium_tuning_here():
    for p in _tracked_files():
        text = p.read_text()
        assert "disable-kube-proxy" not in text, p
        assert "HelmChartConfig" not in text, p
