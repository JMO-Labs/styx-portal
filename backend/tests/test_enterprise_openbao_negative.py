"""The OpenBao validators reject known-bad values (issue #4), so the positive tests mean something."""

from pathlib import Path

import pytest
import yaml

from tests.openbao_checks import OPENBAO, check_values, deep_merge, load_yaml

BAD = Path(__file__).parent / "fixtures/openbao_bad"
CASES = ["seal_shamir", "seal_env_key", "tls_disabled", "raft_on_ceph", "hostpath_rw",
         "extra_hostpath", "image_tag_only", "two_replicas"]


@pytest.mark.parametrize("name", CASES)
def test_bad_values_rejected(name):
    case = yaml.safe_load((BAD / f"{name}.yaml").read_text())
    bad = deep_merge(load_yaml(OPENBAO / "values.yaml"), case["patch"])
    errs = check_values(bad)
    assert errs, f"{name} was accepted"
    assert any(case["expect"] in e for e in errs), errs
