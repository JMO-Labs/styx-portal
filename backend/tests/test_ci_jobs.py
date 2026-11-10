"""GitLab CI jobs, OpenBao role and docs for protected-branch rules as code (issue #16)."""

import json
import re

import pytest
import yaml

from tests.openbao_checks import OPENBAO, ROOT, policy_paths

CI = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
APPLY_JOBS = ("gitlab-mirror-apply", "gitlab-protect-apply")


def shell(job):
    return "\n".join(CI[job].get("before_script", []) + CI[job]["script"])


@pytest.mark.parametrize("job", APPLY_JOBS)
def test_apply_jobs_do_not_eval_command_substitution(job):
    body = shell(job)
    assert 'eval "$(' not in body
    assert re.search(r'creds="\$\(python3 ', body) and 'eval "$creds"' in body


@pytest.mark.parametrize("job", APPLY_JOBS + ("gitlab-protect-drift",))
def test_apply_jobs_gate_on_rc_0_or_2(job):
    body = shell(job)
    assert "-le 2" not in body
    if job != "gitlab-protect-drift":
        assert '"$rc" -eq 0' in body and '"$rc" -eq 2' in body


def test_protect_apply_manual_protected_and_logs_in():
    job = CI["gitlab-protect-apply"]
    (rule,) = job["rules"]
    assert rule["when"] == "manual"
    assert rule["if"].replace("'", '"') == '$CI_COMMIT_REF_PROTECTED == "true"'
    body = shell("gitlab-protect-apply")
    assert '"role": "gitlab-protect"' in body and "kv/data/gitlab-protect/bootstrap" in body
    applied = re.search(r"protect_bootstrap\.py$", body, re.M)
    assert applied and body.index("protect_bootstrap.py --dry-run") < applied.start()
    assert "github_lock.py" not in body  # the GitHub push-lock is applied only at cutover
    assert job["id_tokens"] and "GITLAB_TOKEN" not in (job.get("variables") or {})


def test_drift_job_schedule_only():
    job = CI["gitlab-protect-drift"]
    (rule,) = job["rules"]
    cond = rule["if"]
    assert '$CI_PIPELINE_SOURCE == "schedule"' in cond
    assert '$CI_COMMIT_REF_PROTECTED == "true"' in cond and "when" not in rule
    body = shell("gitlab-protect-drift")
    assert "protect_bootstrap.py --dry-run" in body
    assert body.count("protect_bootstrap.py") == body.count("protect_bootstrap.py --dry-run")
    assert not job.get("allow_failure")


def test_iac_job_lints_and_tests_offline():
    job = CI["gitlab-protect-iac"]
    assert job["stage"] == "test"
    assert job["rules"] == CI["pytest"]["rules"]  # on_push_or_mr
    script = "\n".join(job["script"])
    for f in ("gitlab-common/glapi.py", "protect_bootstrap.py", "approval_gate.py",
              "github_lock.py"):
        assert f in script, f
    for t in ("test_gitlab_glapi.py", "test_gitlab_protect_bootstrap.py",
              "test_approval_gate.py", "test_github_lock.py", "test_ci_jobs.py"):
        assert f"tests/{t}" in script, t


def test_protect_policy_read_only_and_scoped():
    assert policy_paths((OPENBAO / "policies/gitlab-protect.hcl").read_text()) == {
        "kv/data/gitlab-protect/*": {"read"}}


def test_protect_jwt_role_matches_mirror_shape():
    roles = {r["name"]: r for r in json.loads((OPENBAO / "jwt-roles.json").read_text())}
    mirror, protect = roles["gitlab-mirror"], roles["gitlab-protect"]
    assert set(protect) == set(mirror)
    assert protect["bound_claims"] == mirror["bound_claims"]
    assert protect["bound_audiences"] == mirror["bound_audiences"]
    assert protect["policies"] == ["gitlab-protect"]
    assert isinstance(protect["token_ttl"], int) and 0 < protect["token_ttl"] <= 900


def test_docs_linked_and_matrix_rows():
    page = ROOT / "docs/operate/gitlab-protect.md"
    assert page.is_file()
    nav = (ROOT / "zensical.toml").read_text()
    assert nav.index("operate/gitlab-mirror.md") < nav.index("operate/gitlab-protect.md")
    adr = (ROOT / "docs/enterprise/adr/0048-code-provenance-federal-gitlab-source-of-truth.md")
    assert "operate/gitlab-protect.md" in adr.read_text()
    assert "operate/gitlab-protect.md" in (
        ROOT / "deploy/enterprise/gitlab-protect/README.md").read_text()
    cm = (ROOT / "docs/enterprise/control-matrix.md").read_text()
    for ctl in ("CM-3", "SA-10"):
        row = next(ln for ln in cm.splitlines() if ln.startswith(f"| {ctl} |"))
        for cite in ("protect_bootstrap.py", "approval-gate", "gitlab-protect-drift",
                     "github_lock.py"):
            assert cite in row, (ctl, cite)
        assert row.rstrip().endswith("| Planned |"), ctl
