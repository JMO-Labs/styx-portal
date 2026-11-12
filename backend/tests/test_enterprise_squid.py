"""Static checks for the Squid egress proxy manifests (issue #161). No Squid needed."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SQUID = ROOT / "deploy/enterprise/squid"
PARAMS = ROOT / "deploy/k8s/components/cilium-baseline/proxy-params.yaml"
KEYS = ["squid", "ts", "src", "host", "method", "status", "action", "port_name", "bytes"]


def docs() -> list[dict]:
    out = []
    for f in sorted(SQUID.glob("*.yaml")):
        out += [d for d in yaml.safe_load_all(f.read_text()) if d]
    return out


def kind(k: str, name: str | None = None) -> dict:
    return next(d for d in docs() if d["kind"] == k and (name is None or d["metadata"]["name"] == name))


def conf() -> str:
    cm = kind("ConfigMap", "squid-config")
    return cm["data"]["squid.conf"]


def directives() -> list[str]:
    return [ln.strip() for ln in conf().splitlines() if ln.strip() and not ln.strip().startswith("#")]


def params() -> dict:
    return yaml.safe_load(PARAMS.read_text())["data"]


def test_kustomization_lists_resources():
    k = yaml.safe_load((SQUID / "kustomization.yaml").read_text())
    for f in k["resources"]:
        assert (SQUID / f).exists(), f
    assert "namespace.yaml" in k["resources"]


def test_namespace_and_selector_match_params():
    p = params()
    assert kind("Namespace")["metadata"]["name"] == p["namespace"] == "egress-proxy"
    for k in ("Deployment", "Service"):
        d = kind(k, "squid")
        assert d["metadata"]["namespace"] == p["namespace"]
    dep = kind("Deployment", "squid")
    assert dep["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/name"] == p["name"]
    assert dep["spec"]["selector"]["matchLabels"]["app.kubernetes.io/name"] == p["name"]
    assert kind("Service", "squid")["metadata"]["labels"]["app.kubernetes.io/name"] == p["name"]


def test_service_ports():
    ports = {x["port"] for x in kind("Service", "squid")["spec"]["ports"]}
    assert ports == {int(params()["port"]), 3129}


def test_no_ssl_bump_and_port_rules():
    d = "\n".join(directives())
    assert "ssl_bump" not in d
    assert re.search(r"^acl SSL_ports port 443$", d, re.M)
    assert re.search(r"^acl Safe_ports port 80$", d, re.M)
    assert "http_access deny CONNECT !SSL_ports" in d
    assert "http_access deny !Safe_ports !CONNECT" in d
    assert "http_port 3128 name=category" in d and "http_port 3129 name=allowlist" in d


def test_category_and_allowlist_acls():
    d = "\n".join(directives())
    # dstdomain cannot glob: the entrypoint expands the category files into an included conf
    assert "/etc/squid/categories/*.txt" in conf()
    assert "include /tmp/categories.conf" in d
    assert "/etc/squid/categories/*.txt" in kind("Deployment", "squid")["spec"]["template"]["spec"]["containers"][0]["args"][0]
    assert re.search(r"acl allowlist_port myportname allowlist", d)
    assert "/etc/squid/allowlist/allowlist.txt" in d
    assert "http_access allow allowlist_port allowlist_hosts" in d
    assert "http_access deny allowlist_port" in d
    assert d.rstrip().endswith("http_access deny all")


def test_allowlist_configmap():
    cm = kind("ConfigMap", "squid-allowlist")
    assert cm["data"]["allowlist.txt"].strip()


def test_access_log_json_no_path():
    logs = [x for x in directives() if x.startswith(("logformat", "access_log"))]
    fmt = next(x for x in logs if x.startswith("logformat"))
    assert "stdio:/dev/stdout" in " ".join(logs)
    body = fmt.split(None, 2)[2]
    assert re.findall(r'"(\w+)":', body) == KEYS
    assert '"squid":1' in body.replace(" ", "")
    assert "%>rd" in body
    for bad in ("%ru", "%rp", "%>ru", "%>rp", "%>rP", "%rP", "%>ru", "%>rs"):
        assert bad not in body
    # substituting every code must give valid JSON
    json.loads(re.sub(r"%\{[^}]*\}\w+|%[<>]?[.\w]+(?:\.%\d*\w+)?", "1", body))


def test_nonroot_and_limits():
    dep = kind("Deployment", "squid")
    pod = dep["spec"]["template"]["spec"]
    c = pod["containers"][0]
    sc = {**pod.get("securityContext", {}), **c.get("securityContext", {})}
    assert sc.get("runAsNonRoot") is True and sc.get("runAsUser", 1) != 0
    assert c["resources"]["limits"]["memory"] and c["resources"]["limits"]["cpu"]
    assert c["resources"]["requests"]
    vols = {v["name"]: v for v in pod["volumes"]}
    assert "persistentVolumeClaim" in vols["categories"]
    mounts = {m["mountPath"] for m in c["volumeMounts"]}
    assert {"/etc/squid/categories", "/etc/squid/allowlist"} <= mounts
