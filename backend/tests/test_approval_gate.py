"""Free-tier approval gate (issue #16): non-author approval after the latest push."""

import os

import pytest
import yaml

from tests.gitlab_stub import DEPLOY, load, run_script, stdlib_only

DIR = DEPLOY / "gitlab-protect"
SCRIPT = DIR / "approval_gate.py"
TOK = "GATE-secret-tok"
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


def gitlab(approved_by, notes=(), versions=(PUSH,), status=200):
    def route(method, path, query, body):
        if status != 200:
            return status, f"echo {TOK}".encode()
        data = {MR: {"iid": 3, "author": {"id": ALICE, "username": "alice"}},
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


def gate_env(base, **kw):
    return {"PATH": os.environ["PATH"], "SSL_CERT_FILE": os.environ["SSL_CERT_FILE"],
            "CI_API_V4_URL": base + "/api/v4", "CI_PROJECT_ID": "7",
            "CI_MERGE_REQUEST_IID": "3", "APPROVAL_GATE_TOKEN": TOK, **kw}


@pytest.mark.parametrize("approved_by,status,rc", [
    ([bob("2026-11-10T11:00:00Z")], 200, 0),
    ([bob("2026-11-10T09:00:00Z")], 200, 1),
    ([], 500, 1),
])
def test_main_exit_codes_and_no_token_in_output(serve, approved_by, status, rc):
    stub = serve(gitlab(approved_by, status=status))
    res = run_script(SCRIPT, env=gate_env(stub.base))
    assert res.returncode == rc, res.stderr
    assert TOK not in res.stdout + res.stderr and "Traceback" not in res.stderr
    assert (res.stdout + res.stderr).strip()  # the reason is printed


@pytest.mark.parametrize("missing", ["CI_API_V4_URL", "CI_PROJECT_ID", "CI_MERGE_REQUEST_IID",
                                     "APPROVAL_GATE_TOKEN"])
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
    assert job["variables"]["GIT_STRATEGY"] == "none"
    (rule,) = job["rules"]
    assert rule["when"] == "manual" and rule["allow_failure"] is False
    cond = rule["if"]
    assert '$CI_PIPELINE_SOURCE == "merge_request_event"' in cond
    assert '$CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "enterprise"' in cond
    assert "$CI_MERGE_REQUEST_TARGET_BRANCH_NAME =~ /^release\\//" in cond
    # Keys an MR's own approval-gate job could otherwise deep-merge in are pinned here.
    assert job["inherit"] == {"default": False, "variables": False}
    for key in ("image", "before_script", "after_script", "cache", "dependencies", "hooks"):
        assert key in job, key
    script = "\n".join(job["script"])
    assert "approval_gate.py/raw?ref=$GATE_REF" in script and "python3 -I" in script
    assert "$GATE_REF" in script and job["variables"]["GATE_REF"]
