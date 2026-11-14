from types import SimpleNamespace

import pytest

from app.services.k8s_instance_objects import (
    BASELINE_CAPS, build_objects, pvc, refuse_reason)

NS = "styx-instances"


def _build(**kw):
    args = dict(name="selkies-abc", image="selkies-desktop:latest",
                env={"A": "1"}, volumes={"vol-home": {"bind": "/config"}},
                port=8080, ns=NS, owner="u1", gpu_enabled=False, gpu_count=1,
                memory_limit=None, cpu_limit=None, shm_size=None, cap_add=[],
                read_only_rootfs=False, tmpfs=[], extra_hosts={},
                entrypoint=None, command=None)
    args.update(kw)
    dep, svc = build_objects(**args)
    return dep, svc, dep["spec"]["template"]["spec"], dep["spec"]["template"]["spec"]["containers"][0]


def test_deployment_shape_and_hardening():
    dep, svc, pod, c = _build()
    assert dep["kind"] == "Deployment" and dep["apiVersion"] == "apps/v1"
    assert dep["metadata"]["namespace"] == NS
    assert dep["spec"]["replicas"] == 0
    assert dep["spec"]["strategy"] == {"type": "Recreate"}
    labels = dep["metadata"]["labels"]
    assert labels == {"app": "selkies-abc", "styx/owner": "u1",
                      "app.kubernetes.io/managed-by": "styx-backend"}
    assert dep["spec"]["selector"]["matchLabels"] == {"app": "selkies-abc"}
    assert dep["spec"]["template"]["metadata"]["labels"] == labels
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["securityContext"] == {"seccompProfile": {"type": "RuntimeDefault"}}
    sc = c["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["capabilities"]["drop"] == ["ALL"]
    assert sc.get("privileged") is not True
    assert "hostNetwork" not in pod and "hostPID" not in pod
    assert not any("hostPath" in v for v in pod.get("volumes", []))


def test_service_shape():
    _, svc, _, _ = _build()
    assert svc["kind"] == "Service"
    assert svc["spec"]["selector"] == {"app": "selkies-abc"}
    assert svc["spec"]["ports"] == [{"name": "http", "port": 8080, "targetPort": 8080}]


def test_image_mapping():
    assert _build()[3]["image"] == "ghcr.io/jmo-labs/styx-desktop:latest"
    assert _build(image="ghcr.io/x/y:1")[3]["image"] == "ghcr.io/x/y:1"


def test_env_default_and_override():
    env = {e["name"]: e["value"] for e in _build()[3]["env"]}
    assert env == {
        "PIXELFLUX_WAYLAND": "true",
        "SELKIES_MANUAL_WIDTH": "1920",
        "SELKIES_MANUAL_HEIGHT": "1080",
        "SELKIES_FRAMERATE": "30",
        "SELKIES_SCALING_DPI": "96",
        "A": "1",
    }
    env = {e["name"]: e["value"] for e in _build(env={"PIXELFLUX_WAYLAND": "false"})[3]["env"]}
    assert env["PIXELFLUX_WAYLAND"] == "false"


def test_limits_requests_and_gpu():
    c = _build(memory_limit="8g", cpu_limit="4.0", gpu_enabled=True, gpu_count=2)[3]
    assert c["resources"]["limits"] == {"memory": "8Gi", "cpu": "4", "amd.com/gpu": 2}
    assert c["resources"]["requests"] == {"memory": "4Gi", "cpu": "1"}
    c = _build(memory_limit="512m", cpu_limit="0.5")[3]
    assert c["resources"]["limits"] == {"memory": "512Mi", "cpu": "500m"}
    assert c["resources"]["requests"] == {"memory": "256Mi", "cpu": "125m"}


def test_volumes_shm_tmpfs():
    _, _, pod, c = _build(shm_size="2g", tmpfs=["/tmp"], read_only_rootfs=True)
    mounts = {m["mountPath"]: m["name"] for m in c["volumeMounts"]}
    vols = {v["name"]: v for v in pod["volumes"]}
    assert vols[mounts["/config"]]["persistentVolumeClaim"]["claimName"] == "vol-home"
    assert vols[mounts["/dev/shm"]]["emptyDir"] == {"medium": "Memory", "sizeLimit": "2Gi"}
    assert vols[mounts["/tmp"]]["emptyDir"] == {"medium": "Memory"}
    assert c["securityContext"]["readOnlyRootFilesystem"] is True


def test_hosts_entrypoint_command():
    _, _, pod, c = _build(extra_hosts={"nas": "192.168.1.5"},
                          entrypoint=["/e"], command=["a", "b"])
    assert pod["hostAliases"] == [{"ip": "192.168.1.5", "hostnames": ["nas"]}]
    assert c["command"] == ["/e"] and c["args"] == ["a", "b"]


def test_caps_net_raw_dropped_others_refused():
    c = _build(cap_add=["CHOWN", "NET_RAW"])[3]
    assert c["securityContext"]["capabilities"]["add"] == ["CHOWN"]
    with pytest.raises(ValueError):
        _build(cap_add=["SYS_ADMIN"])


def test_pvc():
    p = pvc("vol-home", NS)
    assert p["kind"] == "PersistentVolumeClaim"
    assert p["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert p["spec"]["storageClassName"] == "longhorn"
    assert p["spec"]["resources"]["requests"]["storage"] == "20Gi"
    assert p["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "styx-backend"


def _t(**kw):
    return SimpleNamespace(**{"privileged": False, "dind": False, "cap_add": [], **kw})


def test_refuse_reason():
    assert refuse_reason(_t()) is None
    assert "dind" in refuse_reason(_t(dind=True)).lower()
    assert "privileged" in refuse_reason(_t(privileged=True)).lower()
    assert "SYS_ADMIN" in refuse_reason(_t(cap_add=["SYS_ADMIN"]))
    assert refuse_reason(_t(cap_add=["NET_RAW", *sorted(BASELINE_CAPS)])) is None


def test_parse_quantity():
    from app.services.k8s_instance_objects import parse_qty
    assert parse_qty("250m") == 0.25
    assert parse_qty("1") == 1
    assert parse_qty("123456n") == pytest.approx(0.000123456)
    assert parse_qty("512Mi") == 512 * 1024 ** 2
    assert parse_qty("1Gi") == 1024 ** 3
    assert parse_qty("1048576Ki") == 1024 ** 3
    assert parse_qty("") == 0 and parse_qty(None) == 0


def test_readiness_probe_on_web_port():
    _, _, _, c = _build()
    assert c["readinessProbe"] == {"tcpSocket": {"port": 8080}, "initialDelaySeconds": 2,
                                   "periodSeconds": 2, "failureThreshold": 3}


def test_image_pull_policy_if_not_present():
    _, _, _, c = _build()
    assert c["imagePullPolicy"] == "IfNotPresent"


def _envmap(c):
    return {e["name"]: e["value"] for e in c["env"]}


def test_cpu_tier_defaults_applied():
    _, _, _, c = _build()
    assert c["resources"]["limits"] == {"cpu": "3", "memory": "4Gi"}
    e = _envmap(c)
    assert (e["SELKIES_MANUAL_WIDTH"], e["SELKIES_MANUAL_HEIGHT"]) == ("1920", "1080")
    assert e["SELKIES_FRAMERATE"] == "30"
    assert e["SELKIES_SCALING_DPI"] == "96"


def test_template_values_win_over_cpu_tier():
    _, _, _, c = _build(memory_limit="8g", cpu_limit="2",
                        env={"SELKIES_FRAMERATE": "60", "SELKIES_MANUAL_WIDTH": "2560"})
    assert c["resources"]["limits"] == {"cpu": "2", "memory": "8Gi"}
    e = _envmap(c)
    assert e["SELKIES_FRAMERATE"] == "60" and e["SELKIES_MANUAL_WIDTH"] == "2560"
    assert e["SELKIES_MANUAL_HEIGHT"] == "1080"
