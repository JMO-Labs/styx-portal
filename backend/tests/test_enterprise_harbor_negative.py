"""Each bad values override must be rejected by harbor_checks (issue #5)."""

import copy
from pathlib import Path

import pytest
import yaml

from tests import harbor_checks as hc

REPO = Path(__file__).resolve().parents[2]
VALUES = REPO / "deploy/enterprise/harbor/values.yaml"
FIXTURES = Path(__file__).parent / "fixtures/harbor_bad"


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = merge(out.get(k, {}), v) if isinstance(v, dict) and isinstance(
            out.get(k), dict) else v
    return out


@pytest.mark.parametrize("fixture, message", [
    ("tag_only_image.yaml", "core.image not pinned by digest"),
    ("sslmode_disable.yaml", "sslmode must be verify-full"),
    ("redirect_enabled.yaml", "disableredirect must be true"),
    ("trivy_on.yaml", "trivy.enabled must be false"),
    ("single_replica.yaml", "registry.replicas must be >= 2"),
    ("default_admin_password.yaml", "existingSecretAdminPassword must be harbor-admin"),
    ("oidc_or_self_reg.yaml", "self_registration must be false"),
    ("filesystem_storage.yaml", "imageChartStorage.type must be s3"),
    ("chart_generated_secret.yaml", "core.existingSecret must be harbor-core-secret"),
])
def test_bad_values_rejected(fixture, message):
    good = yaml.safe_load(VALUES.read_text())
    assert hc.errors(good) == []
    bad = merge(good, yaml.safe_load((FIXTURES / fixture).read_text()))
    errs = hc.errors(bad)
    assert any(message in e for e in errs), errs
