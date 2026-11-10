"""Static checks for GitLab -> GitHub mirroring as code (issue #10, ADR-0048)."""

import json
import re

import yaml

from tests.openbao_checks import OPENBAO, ROOT, policy_paths


def test_mirror_policy_is_read_only_and_scoped():
    assert policy_paths((OPENBAO / "policies/gitlab-mirror.hcl").read_text()) == {
        "kv/data/gitlab-mirror/*": {"read"}}


def test_jwt_role_binds_protected_ref():
    (role,) = json.loads((OPENBAO / "jwt-roles.json").read_text())
    assert role["name"] == "gitlab-mirror" and role["role_type"] == "jwt"
    assert role["bound_claims"]["ref_protected"] == "true"
    assert role["bound_claims"]["project_path"] and "*" not in role["bound_claims"]["project_path"]
    assert role["bound_audiences"] and role["user_claim"]
    assert role["policies"] == ["gitlab-mirror"]
    assert isinstance(role["token_ttl"], int) and 0 < role["token_ttl"] <= 900


def test_ci_apply_job_is_manual_and_protected():
    text = (ROOT / ".gitlab-ci.yml").read_text()
    ci = yaml.safe_load(text)
    iac = ci["gitlab-mirror-iac"]
    assert iac["stage"] == "test"
    script = "\n".join(iac["script"])
    assert "ruff check" in script and "mirror_bootstrap.py" in script
    assert "tests/test_gitlab_mirror_bootstrap.py" in script
    apply = ci["gitlab-mirror-apply"]
    (rule,) = apply["rules"]
    assert rule["when"] == "manual"
    assert rule["if"].replace("'", '"') == '$CI_COMMIT_REF_PROTECTED == "true"'
    assert apply["id_tokens"]
    body = "\n".join(apply["script"])
    assert "auth/jwt/login" in body and "mirror_bootstrap.py" in body
    assert not {"GITLAB_TOKEN", "GITHUB_TOKEN"} & set(apply.get("variables") or {})
    assert not re.search(r"glpat-|ghp_|github_pat_|gho_", text)


def row(text: str, control: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"| {control} |"))


def test_control_matrix_rows_cite_mirror():
    cm = (ROOT / "docs/enterprise/control-matrix.md").read_text()
    for ctl in ("CM-3", "SA-10", "SR-4"):
        r = row(cm, ctl)
        assert "gitlab-mirror" in r and "0048" in r, ctl
        assert r.rstrip().endswith("| Planned |"), ctl


def test_docs_page_linked():
    assert (ROOT / "docs/operate/gitlab-mirror.md").is_file()
    assert "operate/gitlab-mirror.md" in (ROOT / "zensical.toml").read_text()
    assert "operate/gitlab-mirror.md" in (
        ROOT / "deploy/enterprise/gitlab-mirror/README.md").read_text()
