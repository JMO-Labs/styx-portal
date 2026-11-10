"""Static checks for deploy/enterprise/external-secrets (issue #4, ADR-0042)."""

from tests.openbao_checks import ESO, check_images, load_docs, load_yaml


def store() -> dict:
    (doc,) = load_docs(ESO / "clustersecretstore.yaml")
    return doc


def test_clustersecretstore_openbao():
    s = store()
    vault = s["spec"]["provider"]["vault"]
    assert vault["server"] == "https://openbao-active.openbao.svc:8200"
    assert vault["path"] == "kv" and vault["version"] == "v2"
    assert vault["caProvider"] == {"type": "Secret", "name": "openbao-ca", "key": "ca.crt",
                                   "namespace": "external-secrets"}
    k8s = vault["auth"]["kubernetes"]
    assert k8s["mountPath"] == "kubernetes" and k8s["role"] == "eso"
    assert k8s["serviceAccountRef"] == {"name": "external-secrets", "namespace": "external-secrets"}


def test_store_restricted_by_namespace_label():
    conds = store()["spec"]["conditions"]
    assert len(conds) == 1
    assert conds[0] == {"namespaceSelector": {"matchLabels": {"styx.io/openbao-secrets": "true"}}}


def test_store_has_no_static_token_auth():
    assert list(store()["spec"]["provider"]["vault"]["auth"]) == ["kubernetes"]
    assert list(store()["spec"]["provider"]) == ["vault"]


def test_eso_images_pinned_by_digest():
    v = load_yaml(ESO / "values.yaml")
    imgs = [v["image"], v["webhook"]["image"], v["certController"]["image"]]
    for img in imgs:
        assert check_images(img) == [], img
    assert v["installCRDs"] is True
    assert v["serviceAccount"]["name"] == "external-secrets"


def test_matches_offsite_export_contract():
    # #13's ExternalSecrets reference ClusterSecretStore/openbao and keys under kv/.
    s = store()
    assert (s["kind"], s["metadata"]["name"]) == ("ClusterSecretStore", "openbao")
    assert s["apiVersion"] == "external-secrets.io/v1"


def test_namespace():
    (ns,) = load_docs(ESO / "namespace.yaml")
    assert ns["metadata"]["name"] == "external-secrets"
