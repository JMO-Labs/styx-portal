"""Static checks for deploy/logging (styx-portal#11): Fluent Bit -> Elastic SIEM."""
import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "logging"
ELASTIC = ROOT / "elastic"
AUDIT_LOG = "/var/lib/rancher/rke2/server/logs/audit.log"


def _docs(name):
    return [d for d in yaml.safe_load_all((ROOT / name).read_text()) if d]


def _all_docs():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    return [d for f in k["resources"] for d in _docs(f)]


def _kind(kind):
    return [d for d in _all_docs() if d["kind"] == kind]


def _values(release):
    (hc,) = [h for h in _kind("HelmChart") if h["metadata"]["name"] == release]
    return yaml.safe_load(hc["spec"]["valuesContent"])


def _sections(text):
    """Parse classic Fluent Bit config into [(SECTION, {lower key: value})]."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            out.append((line.strip("[]").upper(), {}))
        else:
            k, _, v = line.partition(" ")
            out[-1][1][k.lower()] = v.strip()
    return out


def _all(section, key):
    return [s for v in (_values("fluent-bit"), _values("fluent-bit-audit"))
            for name, s in _sections(v["config"][key]) if name == section]


def _outputs():
    return [o for o in _all("OUTPUT", "outputs") if o["name"] == "es"]


def _inputs():
    return _all("INPUT", "inputs")


def _files():
    return [p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def _bootstrap():
    spec = importlib.util.spec_from_file_location("es_bootstrap", ELASTIC / "bootstrap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan(env=None):
    return {path: body for path, body in _bootstrap().plan(env or {})}


# --- kustomization -----------------------------------------------------------------

def test_kustomization_lists_all_resources():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    yamls = {p.name for p in ROOT.glob("*.yaml")} - {"kustomization.yaml"}
    assert yamls == set(k["resources"])
    assert "components" not in k  # ExternalSecret stays opt-in until #4 is live
    assert not any("external-secret" in r for r in k["resources"])
    (gen,) = k["secretGenerator"]
    assert gen["name"] == "elastic-shipper"
    assert gen["envs"] == ["secrets.example.env"]
    assert (ROOT / "secrets.example.env").exists()


def test_namespace_logging():
    (ns,) = _kind("Namespace")
    assert ns["metadata"]["name"] == "logging"


def test_helmchart_pulled_through_harbor():
    charts = _kind("HelmChart")
    assert {c["metadata"]["name"] for c in charts} == {"fluent-bit", "fluent-bit-audit"}
    for c in charts:
        assert c["apiVersion"] == "helm.cattle.io/v1"
        assert c["spec"]["chart"].startswith("oci://harbor.")
        assert c["spec"]["chart"].endswith("/fluent-bit")
        assert re.fullmatch(r"\d+\.\d+\.\d+", c["spec"]["version"])
        assert c["spec"]["targetNamespace"] == "logging"
        assert yaml.safe_load(c["spec"]["valuesContent"])["image"]["repository"].startswith(
            "harbor.")


def test_lua_configmap_maps_k8s_audit_to_ecs():
    (cm,) = [c for c in _kind("ConfigMap") if c["metadata"]["name"] == "fluent-bit-lua"]
    lua = cm["data"]["styx.lua"]
    for fn in ("function k8s_audit_ecs", "function styx_route"):
        assert fn in lua
    for field in ('"@timestamp"', "user", "source", "kubernetes.audit_logs", "outcome"):
        assert field in lua
    for release in ("fluent-bit", "fluent-bit-audit"):
        mounts = _values(release)["extraVolumes"]
        assert {"name": "lua", "configMap": {"name": "fluent-bit-lua"}} in mounts


# --- outputs, TLS, credentials -------------------------------------------------------

def test_es_outputs_verify_tls_and_hostname():
    outs = _outputs()
    assert len(outs) == 4
    for o in outs:
        assert o.get("tls", "").lower() == "on"
        assert o.get("tls.verify", "").lower() == "on"
        assert o.get("tls.verify_hostname", "").lower() == "on", o["match"]
        assert o.get("tls.ca_file")
        assert o["write_operation"] == "create"
        assert o["suppress_type_name"].lower() == "on"
        assert o["compress"] == "gzip"
        assert o["http_api_key"] == "${ELASTIC_API_KEY}"


def test_no_literal_credentials():
    for o in _outputs():
        for k in ("http_api_key", "http_passwd", "cloud_auth"):
            if k in o:
                assert re.fullmatch(r"\$\{[A-Z_]+\}", o[k]), k
    key_like = re.compile(r"(?i)(api[_-]?key|passw(or)?d|secret)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{16,}")
    for p in _files():
        assert not key_like.search(p.read_text()), p
    env = (ROOT / "secrets.example.env").read_text()
    assert re.search(r"^ELASTIC_API_KEY=$", env, re.M)
    for release in ("fluent-bit", "fluent-bit-audit"):
        env_from = _values(release)["envFrom"]
        assert {"secretRef": {"name": "elastic-shipper"}} in env_from


def test_styx_audit_route_uses_event_id():
    (o,) = [o for o in _outputs() if o["match"] == "styx.audit"]
    assert o["id_key"] == "event.id"
    assert o["index"] == "logs-styx.audit-default"
    (c,) = [o for o in _outputs() if o["match"] == "kube.*"]
    assert c["index"] == "logs-kubernetes.container_logs-default"
    (a,) = [o for o in _outputs() if o["match"] == "k8s.audit"]
    assert a["index"] == "logs-kubernetes.audit_logs-default"


def test_styx_audit_only_from_backend_container():
    """Any pod can print an ECS line; only styx/backend may reach the audit stream."""
    lua = _kind("ConfigMap")[0]["data"]["styx.lua"]
    assert '["namespace_name"] == "styx"' in lua
    assert '["container_name"] == "backend"' in lua
    (rt,) = [f for f in _all("FILTER", "filters")
             if f["name"] == "rewrite_tag" and f["rule"].startswith("$_styx_audit ")]
    assert rt["rule"].split()[2] == "styx.audit"


def test_squid_route_filter_output_and_role():
    lua = _kind("ConfigMap")[0]["data"]["styx.lua"]
    assert '["namespace_name"] == "egress-proxy"' in lua
    assert '["container_name"] == "squid"' in lua
    assert 'record["squid"] == 1' in lua
    (rt,) = [f for f in _all("FILTER", "filters")
             if f["name"] == "rewrite_tag" and f["rule"].split()[2] == "squid.access"]
    assert rt["rule"].startswith("$_squid ")
    # field filter runs on the squid tag only and keeps an allowlist
    (lf,) = [f for f in _all("FILTER", "filters")
             if f["name"] == "lua" and f["match"] == "squid.access"]
    assert lf["call"] == "squid_filter"
    body = lua.split("function squid_filter")[1].split("\nfunction ")[0]
    for k in ("ts", "src", "host", "method", "status", "action", "port_name", "bytes",
              "pod_name"):
        assert k in body
    assert "url" not in body and "path" not in body
    (o,) = [o for o in _outputs() if o["match"] == "squid.access"]
    assert o["index"] == "logs-squid.access-default"
    assert o["tls.verify"] == "on" and o["http_api_key"] == "${ELASTIC_API_KEY}"
    role = json.loads((ELASTIC / "roles" / "styx-shipper.json").read_text())
    assert "logs-squid.*-*" in role["indices"][0]["names"]


def test_filesystem_buffering():
    for v in (_values("fluent-bit"), _values("fluent-bit-audit")):
        (svc,) = [s for n, s in _sections(v["config"]["service"]) if n == "SERVICE"]
        assert svc["storage.path"]
    for i in _inputs():
        assert i["storage.type"] == "filesystem"
    for o in _outputs():
        assert o["storage.total_limit_size"]
        assert o["retry_limit"].lower() == "false"


def test_apiserver_audit_controlplane_only():
    (tail,) = [i for i in _inputs() if i.get("path") == AUDIT_LOG]
    assert tail["tag"] == "k8s.audit"
    v = _values("fluent-bit-audit")
    assert v["nodeSelector"] == {"node-role.kubernetes.io/control-plane": "true"}
    assert any(t.get("key") == "CriticalAddonsOnly" for t in v["tolerations"])
    vols = {x["name"]: x for x in v["extraVolumes"]}
    assert vols["rke2-audit"]["hostPath"]["path"] == str(Path(AUDIT_LOG).parent)
    (m,) = [m for m in v["extraVolumeMounts"] if m["name"] == "rke2-audit"]
    assert m["readOnly"] is True
    # The all-nodes release must never mount the audit log.
    main = _values("fluent-bit")
    assert AUDIT_LOG not in json.dumps(main)


def test_audit_policy_never_logs_secret_bodies():
    pol = yaml.safe_load((ROOT / "rke2" / "audit-policy.yaml").read_text())
    assert pol["apiVersion"] == "audit.k8s.io/v1" and pol["kind"] == "Policy"
    rules = pol["rules"]
    for r in rules:
        res = {x for g in r.get("resources", []) for x in g.get("resources", [])}
        if res & {"secrets", "configmaps"}:
            assert r["level"] in ("Metadata", "None"), r
        assert r["level"] in ("None", "Metadata", "Request", "RequestResponse")
    assert rules[-1] == {"level": "Metadata"}
    secret_idx = next(i for i, r in enumerate(rules)
                      if any("secrets" in g.get("resources", []) for g in r.get("resources", [])))
    rr = [i for i, r in enumerate(rules) if r["level"] in ("Request", "RequestResponse")]
    assert all(i > secret_idx for i in rr)  # first match wins: secrets rule must come first
    rr_res = {x for i in rr for g in rules[i]["resources"] for x in g.get("resources", [])}
    assert {"pods/exec", "pods/attach", "pods/portforward"} <= rr_res
    assert any(g.get("group") == "rbac.authorization.k8s.io"
               for i in rr for g in rules[i]["resources"])
    nones = [r for r in rules if r["level"] == "None"]
    assert any({"get", "list", "watch"} <= set(r.get("verbs", [])) for r in nones)
    assert any("/healthz*" in r.get("nonResourceURLs", []) for r in nones)


def test_netpol_egress_only_elastic_dns_and_apiserver():
    (cnp,) = _kind("CiliumNetworkPolicy")
    assert cnp["metadata"]["namespace"] == "logging"
    egress = cnp["spec"]["egress"]
    assert len(egress) == 3
    dns, es, api = egress
    assert dns["toEndpoints"][0]["matchLabels"]["k8s-app"] == "kube-dns"
    assert es["toFQDNs"] == [{"matchName": "siem.example.internal"}]
    assert {p["port"] for p in es["toPorts"][0]["ports"]} == {"443", "9200"}
    # The kubernetes filter needs the API server for pod metadata; nothing else.
    assert api == {"toEntities": ["kube-apiserver"]}
    for o in _outputs():
        assert o["host"] == "${ELASTIC_HOST}"


def test_external_secret_component():
    comp = ROOT / "components" / "external-secret"
    k = yaml.safe_load((comp / "kustomization.yaml").read_text())
    assert k["kind"] == "Component"
    (es,) = [d for f in k["resources"] for d in yaml.safe_load_all((comp / f).read_text())]
    assert es["kind"] == "ExternalSecret"
    assert es["metadata"]["name"] == "elastic-shipper"
    assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    refs = {d["remoteRef"]["key"] for d in es["spec"]["data"]}
    assert refs == {"kv/styx/logging/elastic"}
    assert {d["secretKey"] for d in es["spec"]["data"]} >= {"ELASTIC_API_KEY"}
    patches = "\n".join(p["patch"] for p in k["patches"])
    assert "$patch: delete" in patches  # drops the placeholder generated Secret
    assert "styx.io/openbao-secrets" in patches  # ClusterSecretStore namespace gate


# --- Elastic assets ----------------------------------------------------------------

def test_ilm_phases():
    pol = _plan()["_ilm/policy/styx-logs"]["policy"]["phases"]
    assert pol["hot"]["actions"]["rollover"] == {"max_primary_shard_size": "50gb",
                                                 "max_age": "30d"}
    assert pol["cold"]["min_age"] == "90d"
    assert pol["delete"]["min_age"] == "455d"
    custom = _plan({"RETENTION_DELETE_DAYS": "365"})["_ilm/policy/styx-logs"]
    assert custom["policy"]["phases"]["delete"]["min_age"] == "365d"


def test_bootstrap_rejects_bad_retention():
    import pytest
    for bad in ("abc", "30", "365d"):
        with pytest.raises(ValueError):
            _plan({"RETENTION_DELETE_DAYS": bad})


def test_index_templates_per_dataset():
    plan = _plan()
    names = {p.rsplit("/", 1)[1] for p in plan if p.startswith("_index_template/")}
    assert names == {"logs-styx.audit", "logs-styx.egress", "logs-styx.dlp",
                     "logs-kubernetes.container_logs", "logs-kubernetes.audit_logs",
                     "logs-squid.access"}
    for p, body in plan.items():
        if p.startswith("_index_template/"):
            name = p.rsplit("/", 1)[1]
            assert body["data_stream"] == {}
            assert body["index_patterns"] == [f"{name}-*"]
            assert body["priority"] > 200  # above built-in logs-*-* and integrations
            assert body["composed_of"][:2] == ["styx@settings", "styx-ecs@mappings"]
            assert "${" not in json.dumps(body)
    settings = plan["_component_template/styx@settings"]["template"]["settings"]
    assert settings["index.lifecycle.name"] == "styx-logs"


def test_shipper_role_least_privilege():
    role = _plan()["_security/role/styx-shipper"]
    assert role["cluster"] == []
    (idx,) = role["indices"]
    assert set(idx["names"]) == {"logs-styx.*-*", "logs-kubernetes.*-*", "logs-squid.*-*"}
    assert set(idx["privileges"]) == {"create_doc", "auto_configure"}
    assert not set(idx["privileges"]) & {"all", "write", "delete", "index", "manage"}


def _props():
    return _plan()["_component_template/styx-ecs@mappings"]["template"]["mappings"]["properties"]


def test_detail_mapped_flattened():
    assert _props()["styx"]["properties"]["audit"]["properties"]["detail"]["type"] == \
        "flattened"


def test_reserved_hook_fields_mapped():
    p = _props()
    styx = p["styx"]["properties"]
    assert set(styx["identity"]["properties"]) == {"card_key", "card_type"}
    assert set(styx["dlp"]["properties"]) == {"direction", "channel", "filename_sha256"}
    assert {"domain"} <= set(p["url"]["properties"])
    assert {"domain"} <= set(p["destination"]["properties"])
    assert p["http"]["properties"]["request"]["properties"]["method"]["type"] == "keyword"
    assert p["rule"]["properties"]["category"]["type"] == "keyword"
    assert set(p["file"]["properties"]) == {"size", "mime_type"}  # never file.hash
    assert p["event"]["properties"]["id"]["type"] == "keyword"
    assert p["@timestamp"]["type"] == "date"


def test_bootstrap_dry_run_needs_no_key(capsys):
    rc = _bootstrap().main(["--dry-run"], env={})
    assert rc == 0
    out = capsys.readouterr().out
    assert "PUT _ilm/policy/styx-logs" in out


def test_bootstrap_requires_setup_key_and_https():
    mod = _bootstrap()
    assert mod.main([], env={"ELASTIC_URL": "https://siem.example.internal:9200"}) == 2
    assert mod.main([], env={"ELASTIC_URL": "http://siem:9200",
                             "ELASTIC_SETUP_API_KEY": "x"}) == 2


# --- alerting ------------------------------------------------------------------------

def test_prometheusrule_shipper_failure_alert():
    (pr,) = _kind("PrometheusRule")
    rules = {r["alert"]: r for g in pr["spec"]["groups"] for r in g["rules"]}
    assert {"FluentBitOutputFailing", "FluentBitRetriesHigh"} <= set(rules)
    assert "fluentbit_output" in rules["FluentBitOutputFailing"]["expr"]
    assert rules["FluentBitOutputFailing"]["labels"]["severity"] == "critical"
    assert pr["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    for release in ("fluent-bit", "fluent-bit-audit"):
        assert _values(release)["serviceMonitor"]["enabled"] is True


def test_files_under_500_lines():
    for p in _files():
        assert len(p.read_text().splitlines()) < 500, p
