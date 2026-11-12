"""CephFS-backed RWX PVCs: per-user home and per-profile volumes (ADR-0034, ADR-0054)."""
from app.config import Settings
from app.services.k8s_instance_objects import MANAGED


def _rwx(name: str, ns: str, size: str, labels: dict) -> dict:
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "metadata": {"name": name, "namespace": ns, "labels": {**MANAGED, **labels}},
            "spec": {"accessModes": ["ReadWriteMany"],
                     "storageClassName": Settings().HOME_STORAGE_CLASS,
                     "resources": {"requests": {"storage": size}}}}


def home_pvc(uid: int, ns: str) -> dict:
    return _rwx(f"home-{uid}", ns, Settings().HOME_QUOTA, {"styx/home-uid": str(uid)})


def profile_pvc(name: str, ns: str) -> dict:
    return _rwx(name, ns, Settings().PROFILE_QUOTA, {})


def ensure_home(api, uid: int, ns: str) -> None:
    """Create the user's home PVC unless it already exists."""
    name = f"home-{uid}"
    if api.get_json(f"/api/v1/namespaces/{ns}/persistentvolumeclaims/{name}") is None:
        api.apply(home_pvc(uid, ns))
