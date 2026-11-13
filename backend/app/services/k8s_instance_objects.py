"""Pure builders for instance Deployments/Services/PVCs (no I/O)."""
import logging
import re

from app.config import Settings
from app.services import image_digest

logger = logging.getLogger("styx-portal")
MANAGED = {"app.kubernetes.io/managed-by": "styx-backend"}
BASELINE_CAPS = {"AUDIT_WRITE", "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL",
                 "MKNOD", "NET_BIND_SERVICE", "SETFCAP", "SETGID", "SETPCAP",
                 "SETUID", "SYS_CHROOT"}
_UNITS = {"k": "Ki", "m": "Mi", "g": "Gi", "t": "Ti"}
_warned_net_raw = False


_SUFFIX = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
           "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4}


def parse_qty(q: str | None) -> float:
    """k8s quantity ("250m", "123456n", "512Mi") -> cores / bytes."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zA-Z]*)", (q or "").strip())
    return float(m[1]) * _SUFFIX.get(m[2], 1) if m else 0.0


def _qty(v: str) -> str:
    """Docker size ("8g", "512m") -> k8s quantity."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmgt])b?", v.strip().lower())
    if not m:
        return v
    n = float(m[1])
    return f"{int(n) if n == int(n) else n}{_UNITS[m[2]]}"


def _mem_half(v: str) -> str:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti)", _qty(v))
    if not m:
        return _qty(v)
    n, unit = float(m[1]) / 2, m[2]
    order = ["Ki", "Mi", "Gi", "Ti"]
    while n != int(n) and unit != "Ki":
        n, unit = n * 1024, order[order.index(unit) - 1]
    return f"{int(n)}{unit}"


def _cpu(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{round(v * 1000)}m"


def _caps(cap_add: list[str]) -> list[str]:
    global _warned_net_raw
    out = []
    for c in cap_add:
        if c == "NET_RAW":
            if not _warned_net_raw:
                _warned_net_raw = True
                logger.info("k8s: dropping NET_RAW from template cap_add")
        elif c in BASELINE_CAPS:
            out.append(c)
        else:
            raise ValueError(f"capability {c} is not allowed on Kubernetes")
    return out


def refuse_reason(template) -> str | None:
    if getattr(template, "dind", False):
        return "DinD templates are not supported on Kubernetes"
    if getattr(template, "privileged", False):
        return "Privileged templates are not supported on Kubernetes"
    bad = [c for c in (template.cap_add or []) if c != "NET_RAW" and c not in BASELINE_CAPS]
    if bad:
        return f"Capabilities not supported on Kubernetes: {', '.join(bad)}"
    return None


def pvc(name: str, ns: str, size: str | None = None) -> dict:
    cfg = Settings()
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "metadata": {"name": name, "namespace": ns, "labels": dict(MANAGED)},
            "spec": {"accessModes": ["ReadWriteOnce"],
                     "storageClassName": cfg.INSTANCE_STORAGE_CLASS,
                     "resources": {"requests": {"storage": size or cfg.INSTANCE_VOLUME_SIZE}}}}


def proxy_env(mode: str, cfg) -> dict:
    port = (cfg.EGRESS_PROXY_PORT_ALLOWLIST if mode == "allowlist"
            else cfg.EGRESS_PROXY_PORT_CATEGORY)
    url = f"http://{cfg.EGRESS_PROXY_HOST}:{port}"
    no = "localhost,127.0.0.1,.svc,.cluster.local"
    return {"HTTP_PROXY": url, "HTTPS_PROXY": url, "http_proxy": url,
            "https_proxy": url, "NO_PROXY": no, "no_proxy": no}


def build_objects(name, image, env, volumes, port, ns, owner, *, gpu_enabled=False,
                  gpu_count=1, memory_limit=None, cpu_limit=None, shm_size=None,
                  cap_add=None, read_only_rootfs=False, tmpfs=None, extra_hosts=None,
                  entrypoint=None, command=None, posix_uid: int | None = None,
                  egress_mode=None, home_read_only: bool = False,
                  client=None) -> list[dict]:
    if "/" not in image:
        image = Settings().K8S_DESKTOP_IMAGE
    image = image_digest.resolve_digest(image)
    cfg = Settings()
    if client is not None:  # launch only on a digest every node has pulled
        from app.services.k8s_prepull import ready_digest
        image = ready_digest(client, ns, image)
    memory_limit = memory_limit or cfg.CPU_TIER_MEMORY
    cpu_limit = cpu_limit or cfg.CPU_TIER_CPU
    w, _, h = cfg.CPU_TIER_RESOLUTION.partition("x")
    tier_env = {"SELKIES_MANUAL_WIDTH": w, "SELKIES_MANUAL_HEIGHT": h,
                "SELKIES_FRAMERATE": str(cfg.CPU_TIER_FPS),
                "SELKIES_SCALING_DPI": "192" if cfg.CPU_TIER_HIDPI else "96"}
    labels = {"app": name, "styx/owner": owner, **MANAGED}
    if egress_mode:
        labels["styx.io/egress-mode"] = egress_mode
        env = {**proxy_env(egress_mode, cfg), **env}
    limits: dict = {}
    requests: dict = {}
    if memory_limit:
        limits["memory"] = _qty(memory_limit)
        requests["memory"] = _mem_half(memory_limit)
    if cpu_limit:
        limits["cpu"] = _cpu(float(cpu_limit))
        requests["cpu"] = _cpu(float(cpu_limit) / 4)
    if gpu_enabled:
        limits["amd.com/gpu"] = gpu_count
    vols, mounts = [], []
    for i, (pvc_name, spec) in enumerate(volumes.items()):
        vols.append({"name": f"v{i}", "persistentVolumeClaim": {"claimName": pvc_name}})
        mounts.append({"name": f"v{i}", "mountPath": spec["bind"]})
    if shm_size:
        vols.append({"name": "shm", "emptyDir": {"medium": "Memory",
                                                  "sizeLimit": _qty(shm_size)}})
        mounts.append({"name": "shm", "mountPath": "/dev/shm"})  # nosec B108 - path inside the pod
    for i, path in enumerate(tmpfs or []):
        vols.append({"name": f"tmp{i}", "emptyDir": {"medium": "Memory"}})
        mounts.append({"name": f"tmp{i}", "mountPath": path})
    sec_ctx: dict = {"seccompProfile": {"type": "RuntimeDefault"}}
    if posix_uid is not None:
        sec_ctx.update(runAsUser=posix_uid, runAsGroup=posix_uid, fsGroup=posix_uid,
                       runAsNonRoot=True)
        vols.append({"name": "home",
                     "persistentVolumeClaim": {"claimName": f"home-{posix_uid}"}})
        mounts.append({"name": "home", "mountPath": cfg.HOME_MOUNT_PATH,
                       **({"readOnly": True} if home_read_only else {})})
    if env.get("STYX_INSTANCE_ID"):
        from app.services.unlock_token import unlock_key
        iid = env["STYX_INSTANCE_ID"]
        env = {**env, "STYX_UNLOCK_URL": f"https://login.{cfg.DOMAIN}/api/instances/{iid}/unlock",
               "STYX_UNLOCK_KEY": unlock_key(iid).hex()}
    caps = _caps(list(cap_add or []))
    cap_spec: dict = {"drop": ["ALL"]}
    if caps:
        cap_spec["add"] = caps
    container: dict = {
        "name": "desktop", "image": image, "imagePullPolicy": "IfNotPresent",
        "env": [{"name": k, "value": v}
                for k, v in {"PIXELFLUX_WAYLAND": "true", **tier_env, **env}.items()],
        "ports": [{"containerPort": port}],
        "securityContext": {"allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": read_only_rootfs,
                            "capabilities": cap_spec},
        "volumeMounts": mounts,
        # ponytail: TCP on the web port; selkies' own port is loopback-only so it can't be probed from the kubelet
        "readinessProbe": {"tcpSocket": {"port": port}, "initialDelaySeconds": 2,
                           "periodSeconds": 2, "failureThreshold": 3},
    }
    if limits:
        container["resources"] = {"limits": limits, "requests": requests}
    if entrypoint is not None:
        container["command"] = entrypoint
    if command is not None:
        container["args"] = command
    pod: dict = {"automountServiceAccountToken": False, "enableServiceLinks": False,
                 "securityContext": sec_ctx,
                 "containers": [container], "volumes": vols}
    if extra_hosts:
        pod["hostAliases"] = [{"ip": ip, "hostnames": [h]}
                              for h, ip in extra_hosts.items()]
    dep = {"apiVersion": "apps/v1", "kind": "Deployment",
           "metadata": {"name": name, "namespace": ns, "labels": dict(labels)},
           "spec": {"replicas": 0, "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": name}},
                    "template": {"metadata": {"labels": dict(labels)}, "spec": pod}}}
    svc = {"apiVersion": "v1", "kind": "Service",
           "metadata": {"name": name, "namespace": ns, "labels": dict(MANAGED)},
           "spec": {"selector": {"app": name},
                    "ports": [{"name": "http", "port": port, "targetPort": port}]}}
    return [dep, svc]
