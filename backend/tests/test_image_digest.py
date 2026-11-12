import httpx

from app.config import Settings
from app.services import image_digest
from app.services.image_digest import resolve_digest

REF = "harbor.example/styx/desktop:latest"


def art(digest, push, signed):
    return {"digest": digest, "push_time": push,
            "accessories": [{"type": "signature.cosign"}] if signed else []}


def cfg():
    return Settings(HARBOR_URL="https://harbor.example", HARBOR_USER="u", HARBOR_PASSWORD="p")


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_newest_signed_picked():
    seen = []

    def h(r):
        seen.append(r)
        return httpx.Response(200, json=[
            art("sha256:old", "2026-01-01T00:00:00Z", True),
            art("sha256:new", "2026-03-01T00:00:00Z", True),
            art("sha256:mid", "2026-02-01T00:00:00Z", True)])
    assert resolve_digest(REF, cfg(), client(h)) == "harbor.example/styx/desktop@sha256:new"
    assert "/projects/styx/repositories/desktop/artifacts" in seen[0].url.raw_path.decode()
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_unsigned_newer_skipped():
    """Harbor semantics: the tag sits on the newest (unsigned) push; the older
    signed artifact no longer holds it and is untagged."""
    seen = []

    def h(r):
        seen.append(r)
        return httpx.Response(200, json=[
            {**art("sha256:unsigned", "2026-03-01T00:00:00Z", False),
             "tags": [{"name": "latest"}]},
            {**art("sha256:signed", "2026-01-01T00:00:00Z", True), "tags": None}])
    assert resolve_digest(REF, cfg(), client(h)).endswith("@sha256:signed")
    assert "tags=" not in str(seen[0].url.params.get("q", ""))


def test_foreign_registry_untouched():
    def h(r):
        raise AssertionError("harbor must not be queried")
    ref = "ghcr.io/jmo-labs/styx-desktop:latest"
    assert resolve_digest(ref, cfg(), client(h)) == ref


def test_non_list_body_falls_back():
    assert resolve_digest(REF, cfg(), client(lambda r: httpx.Response(
        200, json={"errors": [{"code": "x"}]}))) == REF


def test_harbor_down_falls_back(caplog):
    def h(r):
        raise httpx.ConnectError("down")
    assert resolve_digest(REF, cfg(), client(h)) == REF
    assert "harbor" in caplog.text.lower()


def test_no_signed_falls_back():
    assert resolve_digest(REF, cfg(), client(lambda r: httpx.Response(
        200, json=[art("sha256:a", "2026-01-01T00:00:00Z", False)]))) == REF


def test_disabled_without_harbor_url():
    assert resolve_digest(REF, Settings(HARBOR_URL=""), None) == REF


def test_already_pinned_untouched():
    pinned = "harbor.example/styx/desktop@sha256:abc"
    assert resolve_digest(pinned, cfg(), None) == pinned


def test_build_objects_pins_digest(monkeypatch):
    from app.services.k8s_instance_objects import build_objects
    monkeypatch.setattr(image_digest, "resolve_digest",
                        lambda ref, *a, **k: "harbor.example/styx/desktop@sha256:new")
    objs = build_objects("n", REF, {}, {}, 3000, "ns", "o")
    dep = next(o for o in objs if o["kind"] == "Deployment")
    assert dep["spec"]["template"]["spec"]["containers"][0]["image"].endswith("@sha256:new")


def test_running_instance_not_patched_when_newer_digest_appears(monkeypatch):
    from app.services.k8s_api import K8sClient
    from app.services.k8s_instances import K8sInstanceRuntime
    calls, bodies = [], []

    def h(r):
        bodies.append(r.content)
        calls.append((r.method, r.url.path))
        return httpx.Response(200, json={})
    rt = K8sInstanceRuntime(K8sClient("https://k8s", "t", False,
                                      transport=httpx.MockTransport(h)))
    monkeypatch.setattr(image_digest, "resolve_digest", lambda ref, *a, **k: "r@sha256:new")
    rt.start_container("selkies-a")
    rt.get_container_status("selkies-a")
    assert all(m == "PATCH" or m == "GET" for m, _ in calls)
    assert not [b for b in bodies if b"image" in b]
    assert rt.pinned_digest("selkies-a") is None


def test_create_records_digest(monkeypatch):
    from app.services.k8s_api import K8sClient
    from app.services.k8s_instances import K8sInstanceRuntime
    rt = K8sInstanceRuntime(K8sClient("https://k8s", "t", False, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={}))))
    monkeypatch.setattr(image_digest, "resolve_digest",
                        lambda ref, *a, **k: "harbor.example/styx/desktop@sha256:new")
    rt.create_container("selkies-a", REF, {}, {}, {}, 3000)
    assert rt.pinned_digest("selkies-a") == "sha256:new"


def test_non_dict_artifact_not_signed():
    """Line 24: a malformed list entry is skipped, not a crash."""
    assert resolve_digest(REF, cfg(), client(lambda r: httpx.Response(
        200, json=["junk", None, art("sha256:ok", "2026-01-01T00:00:00Z", True)]))) \
        == "harbor.example/styx/desktop@sha256:ok"


def test_split_registry_port_without_tag():
    """Line 33: the colon is a registry port, not a tag separator."""
    assert image_digest._split("harbor.example:8443/styx/desktop", "harbor.example:8443") \
        == ("harbor.example:8443/styx/desktop", "styx", "desktop")


def test_owned_client_is_closed(monkeypatch):
    """Line 66: with no injected client, the one created internally is closed."""
    created = []

    class Fake(httpx.Client):
        def __init__(self, *a, **k):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(
                200, json=[art("sha256:a", "2026-01-01T00:00:00Z", True)])))
            created.append(self)

    monkeypatch.setattr(image_digest.httpx, "Client", Fake)
    assert resolve_digest(REF, cfg()).endswith("@sha256:a")
    assert created and created[0].is_closed
