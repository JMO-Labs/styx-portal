"""Free-tier approval gate (issue #16): non-author approval after the latest push."""

import os

import pytest
import yaml

from tests.gitlab_stub import DEPLOY, load, run_script, stdlib_only

DIR = DEPLOY / "gitlab-protect"
SCRIPT = DIR / "approval_gate.py"
TOK = "GATE-secret-tok"
JOB_TOK = "JOB-secret-tok"
SHA = "a" * 40
MR = "/api/v4/projects/7/merge_requests/3"
PUSH = "2026-11-10T10:00:00.000Z"
ALICE, BOB = 1, 2  # alice is the author


@pytest.fixture
def gate():
    return load(SCRIPT, "approval_gate_t")


def test_decide_no_approvals_fails(gate):
    ok, reason = gate.decide(ALICE, [], PUSH)
    assert not ok and "no approval" in reason


def test_decide_author_only_approval_fails(gate):
    assert not gate.decide(ALICE, [(ALICE, "2026-11-10T11:00:00Z")], PUSH)[0]


def test_decide_non_author_after_push_passes(gate):
    ok, reason = gate.decide(ALICE, [(BOB, "2026-11-10T11:00:00Z")], PUSH)
    assert ok and str(BOB) in reason


def test_decide_approval_before_latest_push_fails(gate):
    assert not gate.decide(ALICE, [(BOB, "2026-11-10T09:59:59Z")], PUSH)[0]


def test_decide_equal_timestamp_fails(gate):
    assert not gate.decide(ALICE, [(BOB, "2026-11-10T10:00:00Z")], PUSH)[0]


def test_decide_mixed_author_and_stale_fails(gate):
    approvals = [(ALICE, "2026-11-10T12:00:00Z"), (BOB, "2026-11-10T09:00:00Z")]
    assert not gate.decide(ALICE, approvals, PUSH)[0]


def test_decide_missing_time_fails_closed(gate):
    assert not gate.decide(ALICE, [(BOB, None)], PUSH)[0]
    assert not gate.decide(ALICE, [(BOB, "2026-11-10T11:00:00Z")], None)[0]


def test_decide_timezone_offsets_compared_correctly(gate):
    # 11:30+02:00 is 09:30Z: before the 10:00Z push.
    assert not gate.decide(ALICE, [(BOB, "2026-11-10T11:30:00+02:00")], PUSH)[0]
    assert gate.decide(ALICE, [(BOB, "2026-11-10T12:30:00+02:00")], PUSH)[0]


def note(user, body, at, system=True):
    return {"system": system, "body": body, "author": {"id": user}, "created_at": at}


def job(name="approval-gate", project_id=7, ref="refs/merge-requests/3/head", sha=SHA):
    return {"id": 99, "name": name, "pipeline": {"id": 5, "project_id": project_id,
                                                  "ref": ref, "sha": sha}}


def gitlab(approved_by, notes=(), versions=(PUSH,), status=200, the_job=None):
    def route(method, path, query, body):
        if status != 200:
            return status, f"echo {TOK} {JOB_TOK}".encode()
        data = {"/api/v4/job": the_job or job(),
                MR: {"iid": 3, "sha": SHA, "author": {"id": ALICE, "username": "alice"}},
                MR + "/approvals": {"approved_by": approved_by},
                MR + "/versions": [{"id": i, "created_at": v} for i, v in enumerate(versions)],
                MR + "/notes": list(notes)}
        return (200, data[path]) if method == "GET" and path in data else (404, None)
    return route


def bob(at=None):
    entry = {"user": {"id": BOB, "username": "bob"}}
    return {**entry, "approved_at": at} if at else entry


def test_fetch_uses_note_time_when_approved_at_missing(gate, serve):
    notes = [note(BOB, "unapproved this merge request", "2026-11-10T12:00:00Z"),
             note(BOB, "approved this merge request", "2026-11-10T11:00:00Z"),
             note(BOB, "approved this merge request", "2026-11-10T08:00:00Z"),
             note(BOB, "approved this merge request", "2026-11-10T13:00:00Z", system=False)]
    stub = serve(gitlab([bob()], notes, versions=("2026-11-10T09:00:00Z", PUSH)))
    api = gate.Api(stub.base + "/api/v4", TOK)
    author, approvals, latest = gate.fetch(api, "7", "3")
    assert author == ALICE and latest == PUSH
    assert approvals == [(BOB, "2026-11-10T11:00:00Z")]
    assert all(r[0] == "GET" for r in stub.requests)


def test_fetch_prefers_approved_at(gate, serve):
    stub = serve(gitlab([bob("2026-11-10T11:00:00Z")]))
    api = gate.Api(stub.base + "/api/v4", TOK)
    assert gate.fetch(api, "7", "3")[1] == [(BOB, "2026-11-10T11:00:00Z")]
    assert not [r for r in stub.requests if r[1].endswith("/notes")]


def test_fetch_rejects_mr_sha_other_than_pipeline_sha(gate, serve):
    stub = serve(gitlab([bob("2026-11-10T11:00:00Z")]))
    api = gate.Api(stub.base + "/api/v4", TOK)
    with pytest.raises(gate.GateError, match="sha"):
        gate.fetch(api, "7", "3", "b" * 40)


def test_check_job_returns_iid_and_sha(gate):
    assert gate.check_job(job(), "7", "3") == ("3", SHA)


@pytest.mark.parametrize("bad,iid", [
    (job(ref="refs/merge-requests/4/head"), "3"),  # env IID forged to another MR
    (job(name="evil"), "3"),  # a token stolen from another job
    (job(name="approval-gate 1/2"), "3"),  # parallel: split
    (job(project_id=8), "3"),
    (job(ref="feature/x"), "3"),
    (job(ref="refs/merge-requests/3/merge"), "3"),  # merged results: fail closed
])
def test_check_job_rejects_forged_context(gate, bad, iid):
    with pytest.raises(gate.GateError):
        gate.check_job(bad, "7", iid)


def gate_env(base, **kw):
    return {"PATH": os.environ["PATH"], "SSL_CERT_FILE": os.environ["SSL_CERT_FILE"],
            "CI_API_V4_URL": base + "/api/v4", "CI_PROJECT_ID": "7", "CI_JOB_TOKEN": JOB_TOK,
            "CI_MERGE_REQUEST_IID": "3", "APPROVAL_GATE_TOKEN": TOK, **kw}


@pytest.mark.parametrize("approved_by,status,the_job,rc", [
    ([bob("2026-11-10T11:00:00Z")], 200, None, 0),
    ([bob("2026-11-10T09:00:00Z")], 200, None, 1),
    ([], 500, None, 1),
    # env CI_MERGE_REQUEST_IID=3 but the job token's pipeline is MR 4 (approved): fail
    ([bob("2026-11-10T11:00:00Z")], 200, job(ref="refs/merge-requests/4/head"), 1),
    ([bob("2026-11-10T11:00:00Z")], 200, job(sha="c" * 40), 1),
])
def test_main_exit_codes_and_no_token_in_output(serve, approved_by, status, the_job, rc):
    stub = serve(gitlab(approved_by, status=status, the_job=the_job))
    res = run_script(SCRIPT, env=gate_env(stub.base))
    assert res.returncode == rc, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert TOK not in out and JOB_TOK not in out and "Traceback" not in out
    assert (res.stdout + res.stderr).strip()  # the reason is printed


@pytest.mark.parametrize("missing", ["CI_API_V4_URL", "CI_PROJECT_ID", "CI_MERGE_REQUEST_IID",
                                     "APPROVAL_GATE_TOKEN", "CI_JOB_TOKEN"])
def test_main_missing_env_fails(serve, missing):
    stub = serve(gitlab([]))
    env = gate_env(stub.base)
    del env[missing]
    res = run_script(SCRIPT, env=env)
    assert res.returncode == 1 and missing in res.stderr and stub.requests == []


def test_main_rejects_http_api(serve):
    stub = serve(gitlab([]))
    res = run_script(SCRIPT, env=gate_env(stub.base, CI_API_V4_URL="http://gl.example/api/v4"))
    assert res.returncode == 1 and "https" in res.stderr and stub.requests == []


def test_gate_stdlib_only():
    assert stdlib_only(SCRIPT) == set()


def test_ci_policy_yaml_defines_gate_before_include():
    text = (DIR / "ci-policy/gitlab-ci.yml").read_text()
    ci = yaml.safe_load(text)
    (inc,) = ci["include"]
    assert inc["ref"] == "$CI_COMMIT_SHA" and inc["file"] == ".gitlab-ci.yml"
    assert inc["project"] == "$CI_PROJECT_PATH"
    job = ci["approval-gate"]
    assert job["variables"] == {"GIT_STRATEGY": "none"}
    (rule,) = job["rules"]
    assert rule["when"] == "manual" and rule["allow_failure"] is False
    cond = rule["if"]
    assert '$CI_PIPELINE_SOURCE == "merge_request_event"' in cond
    assert '$CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "enterprise"' in cond
    assert "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME =~ /^release\\//" in cond
    # Keys an MR's own approval-gate job could otherwise deep-merge in are pinned here.
    assert job["inherit"] == {"default": False, "variables": False}
    for key in ("image", "before_script", "after_script", "cache", "dependencies", "hooks",
                "services", "tags"):
        assert key in job, key
    assert job["services"] == [] and job["tags"]  # a trusted runner, not an MR-chosen one


def test_ci_policy_gate_inputs_are_script_literals():
    """Job or manual-run variables override YAML variables, so the API URL, product project
    and gate ref must be literals inside the (pinned) script, not $VARIABLES."""
    job = yaml.safe_load((DIR / "ci-policy/gitlab-ci.yml").read_text())["approval-gate"]
    curl, _check, run = job["script"]
    assert "approval_gate.py/raw?ref=" in curl and "$CI_JOB_TOKEN" in curl
    url = curl.split('"')[-2]
    assert url.startswith("https://") and "$" not in url
    assert "CI_API_V4_URL=https://" in run and "CI_PROJECT_ID=" in run
    assert run.endswith("python3 -I /tmp/approval_gate.py")
    literals = run.split("CI_API_V4_URL=")[1].split("python3")[0]
    assert "$" not in literals


def test_ci_policy_pins_workflow_so_mr_pipelines_exist():
    """An included workflow: could drop MR pipelines (and with them the gate); the main file's
    workflow wins. MR pipelines are always created; branch pipelines step aside for them."""
    wf = yaml.safe_load((DIR / "ci-policy/gitlab-ci.yml").read_text())["workflow"]
    first, *rest = wf["rules"]
    assert first == {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}
    assert {"if": '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS && $CI_PIPELINE_SOURCE == "push"',
            "when": "never"} in rest


def test_ci_policy_workflow_never_rule_is_push_only():
    """Only push pipelines step aside for an open MR; schedule/web/api (drift, apply) still run."""
    rules = yaml.safe_load((DIR / "ci-policy/gitlab-ci.yml").read_text())["workflow"]["rules"]
    nevers = [r for r in rules if r.get("when") == "never"]
    assert nevers and all('$CI_PIPELINE_SOURCE == "push"' in r["if"] for r in nevers)
    assert rules[-1] == {"when": "always"}  # a schedule source falls through to here


def test_ci_policy_gate_runs_in_clean_env_with_pinned_download():
    """MR job variables deep-merge in, so proxy/CA env must not reach curl or the gate,
    and the downloaded gate is checked against a pinned sha256 before it runs."""
    curl, check, run = yaml.safe_load((DIR / "ci-policy/gitlab-ci.yml").read_text())[
        "approval-gate"]["script"]
    assert "--noproxy '*'" in curl and "--proto '=https'" in curl and "--cacert " in curl
    assert "sha256sum -c" in check and "$" not in check.split("|")[0]
    assert run.startswith("env -i PATH=") and "python3 -I /tmp/approval_gate.py" in run
    assert "GITLAB_CA_FILE" not in run and "PROXY" not in run.upper()
