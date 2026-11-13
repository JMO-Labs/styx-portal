"""Grafana SLO dashboards: parse, unique uid, only defined metric names, ConfigMap wiring."""

import json
import re
from pathlib import Path

import yaml

K8S = Path(__file__).resolve().parents[2] / "deploy" / "k8s"
DASH = K8S / "dashboards"
NAMES = ["availability", "launch", "stream-rtt", "headroom"]

# Instrumentation / exporter series dashboards may use besides slo-rules.yaml names.
INSTRUMENTED = {
    "styx_launch_duration_seconds_bucket", "styx_launch_duration_seconds_count",
    "styx_launch_duration_seconds_sum", "styx_launch_failures_total",
    "styx_stream_rtt_seconds_bucket", "styx_stream_rtt_seconds_count",
    "styx_stream_rtt_seconds_sum", "styx_slo_business_hours",
    "styx_maintenance_active", "styx_capacity_peak_desktops",
    "probe_success", "kube_node_status_allocatable",
}
KEYWORDS = {"and", "or", "unless", "bool", "offset", "by", "without", "on", "ignoring",
            "group_left", "group_right", "inf", "nan"}


def _defined_metrics():
    rules = yaml.safe_load((K8S / "slo-rules.yaml").read_text())
    rec = {r["record"] for g in rules["spec"]["groups"] for r in g["rules"] if "record" in r}
    return rec | INSTRUMENTED


def _exprs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "expr" and isinstance(v, str):
                yield v
            else:
                yield from _exprs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _exprs(v)


def _metric_names(expr):
    e = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)
    e = re.sub(r"\{[^}]*\}", "", e)
    e = re.sub(r"\[[^\]]*\]", "", e)
    e = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", "", e)
    names = re.findall(r"(?<![\w:$])([A-Za-z_:][\w:]*)(?!\w|\s*\()", e)
    return {n for n in names if n.lower() not in KEYWORDS}


def _load(name):
    return json.loads((DASH / f"{name}.json").read_text())


def test_four_dashboards_parse_with_unique_uids():
    uids = [_load(n)["uid"] for n in NAMES]
    assert len(set(uids)) == 4


def test_only_defined_metric_names():
    defined = _defined_metrics()
    for n in NAMES:
        exprs = list(_exprs(_load(n)))
        assert exprs, n
        for e in exprs:
            unknown = _metric_names(e) - defined
            assert not unknown, f"{n}: {unknown} in {e}"


def test_each_shows_sli_budget_and_burn_rate():
    for n in NAMES:
        titles = " ".join(p["title"].lower() for p in _load(n)["panels"])
        for want in ("sli", "error budget remaining", "burn rate"):
            assert want in titles, (n, want)


def test_metric_name_extractor_flags_unknown():
    assert _metric_names('sum by (le) (rate(foo_bucket{a="b"}[5m])) / bar') == {"foo_bucket", "bar"}


def test_kustomize_configmap_generator():
    k = yaml.safe_load((K8S / "kustomization.yaml").read_text())
    gens = {g["name"]: g for g in k["configMapGenerator"]}
    assert len(gens) == 4
    files = set()
    for g in gens.values():
        assert g["options"]["labels"]["grafana_dashboard"] == "1"
        assert g["options"]["disableNameSuffixHash"] is True
        (f,) = g["files"]
        files.add(f)
        assert (K8S / f).is_file()
    assert files == {f"dashboards/{n}.json" for n in NAMES}
