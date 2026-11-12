"""Static checks for deploy/enterprise/kyverno signed-image policy."""

import yaml

from tests.openbao_checks import ROOT, load_docs

KY = ROOT / "deploy/enterprise/kyverno"
REGISTRY = "harbor.example.internal/styx/"


def policy() -> dict:
    (doc,) = load_docs(KY / "clusterpolicy.yaml")
    return doc


def rules() -> dict:
    return {r["name"]: r for r in policy()["spec"]["rules"]}


def test_clusterpolicy_enforce():
    p = policy()
    assert p["kind"] == "ClusterPolicy"
    assert p["spec"]["validationFailureAction"] == "Enforce"


def test_all_rules_scoped_to_desktop_namespaces():
    for r in policy()["spec"]["rules"]:
        sel = r["match"]["any"][0]["resources"]
        assert sel["kinds"] == ["Pod"]
        assert sel["namespaceSelector"] == {"matchLabels": {"styx.io/desktop": "true"}}


def test_verify_images_cosign_key_and_digest():
    (vi,) = rules()["verify-signature"]["verifyImages"]
    assert vi["imageReferences"] == [REGISTRY + "*"]
    assert vi["required"] is True and vi["verifyDigest"] is True
    (entry,) = vi["attestors"][0]["entries"]
    assert "BEGIN PUBLIC KEY" in entry["keys"]["publicKeys"]


def test_allowlist_rule_requires_registry_and_digest():
    text = yaml.safe_dump(rules()["require-allowlisted-digest"])
    assert REGISTRY + "*@sha256:*" in text
    assert "initContainers" in text


def test_kustomization_lists_policy():
    (k,) = load_docs(KY / "kustomization.yaml")
    assert "clusterpolicy.yaml" in k["resources"]
