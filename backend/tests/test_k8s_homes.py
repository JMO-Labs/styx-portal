import json

import httpx

from app.services.k8s_api import K8sClient
from app.services.k8s_homes import ensure_home, home_pvc, profile_pvc
from app.services.k8s_instances import K8sInstanceRuntime

NS = "styx-instances"


def test_home_pvc():
    p = home_pvc(1001, NS)
    assert p["metadata"]["name"] == "home-1001"
    assert p["metadata"]["namespace"] == NS
    assert p["metadata"]["labels"]["styx/home-uid"] == "1001"
    assert p["spec"]["accessModes"] == ["ReadWriteMany"]
    assert p["spec"]["storageClassName"] == "ceph-cephfs"
    assert p["spec"]["resources"]["requests"]["storage"] == "10Gi"


def test_profile_pvc():
    p = profile_pvc("prof-a", NS)
    assert p["metadata"]["name"] == "prof-a"
    assert p["spec"]["accessModes"] == ["ReadWriteMany"]
    assert p["spec"]["storageClassName"] == "ceph-cephfs"
    assert p["spec"]["resources"]["requests"]["storage"] == "2Gi"


def test_settings_override(monkeypatch):
    monkeypatch.setenv("HOME_STORAGE_CLASS", "other")
    monkeypatch.setenv("HOME_QUOTA", "5Gi")
    monkeypatch.setenv("PROFILE_QUOTA", "1Gi")
    assert home_pvc(1, NS)["spec"]["storageClassName"] == "other"
    assert home_pvc(1, NS)["spec"]["resources"]["requests"]["storage"] == "5Gi"
    assert profile_pvc("x", NS)["spec"]["resources"]["requests"]["storage"] == "1Gi"


class FakeApi:
    def __init__(self):
        self.existing, self.created = set(), []

    def get_json(self, path, params=None):
        return {} if path.rsplit("/", 1)[-1] in self.existing else None

    def apply(self, obj):
        self.created.append(obj)
        self.existing.add(obj["metadata"]["name"])


def test_ensure_home_creates_once():
    api = FakeApi()
    ensure_home(api, 1001, NS)
    ensure_home(api, 1001, NS)
    assert [o["metadata"]["name"] for o in api.created] == ["home-1001"]


def test_runtime_profile_volume_uses_rwx():
    reqs = []

    def handler(r):
        reqs.append(r)
        return httpx.Response(200, json={})

    rt = K8sInstanceRuntime(K8sClient("https://k8s", "t", False,
                                      transport=httpx.MockTransport(handler)))
    rt.create_volume("prof-a", "20Gi")
    body = json.loads(reqs[-1].content)
    assert body["spec"]["accessModes"] == ["ReadWriteMany"]
    assert body["spec"]["resources"]["requests"]["storage"] == "2Gi"
    rt.create_volume("vol-1")
    assert json.loads(reqs[-1].content)["spec"]["accessModes"] == ["ReadWriteOnce"]
