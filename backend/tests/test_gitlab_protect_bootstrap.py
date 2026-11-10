"""protect_bootstrap.py against an HTTPS GitLab stub (issue #16)."""

import copy
import os
import re
from urllib.parse import unquote

import pytest

from tests.gitlab_stub import DEPLOY, load, run_script, stdlib_only

SCRIPT = DEPLOY / "gitlab-protect/protect_bootstrap.py"
TOK = "GLTOK-protect-secret"
CFG = "gitlab-ci.yml@grp/ci-policy"
PROJ = "/api/v4/projects/grp%2Fproj"
GOOD_PROJECT = {"id": 7, "only_allow_merge_if_pipeline_succeeds": True,
                "allow_merge_on_skipped_pipeline": False, "ci_config_path": CFG}


def lvl(level, id_=1, **kw):
    return {"id": id_, "access_level": level, "user_id": None, "group_id": None, **kw}


def branch(name, push=40, merge=40, force=False):
    return {"name": name, "push_access_levels": [lvl(push, 10)],
            "merge_access_levels": [lvl(merge, 20)], "allow_force_push": force}


GOOD_BRANCHES = {n: branch(n) for n in ("enterprise", "release/*")}
GOOD_TAGS = {"v*": {"name": "v*", "create_access_levels": [lvl(40, 30)]}}
GOOD_APPROVALS = {"merge_requests_author_approval": False,
                  "merge_requests_disable_committers_approval": True,
                  "reset_approvals_on_push": True}
GOOD_RULES = [{"id": 5, "name": "any-approver", "rule_type": "any_approver",
               "approvals_required": 1}]


class GitLab:
    def __init__(self, project=GOOD_PROJECT, branches=GOOD_BRANCHES, tags=GOOD_TAGS,
                 approvals=GOOD_APPROVALS, rules=GOOD_RULES, approvals_status=200,
                 rules_status=200, fail_path=None):
        self.project, self.branches = dict(project), copy.deepcopy(branches)
        self.tags, self.approvals = copy.deepcopy(tags), dict(approvals)
        self.rules, self.approvals_status = copy.deepcopy(rules), approvals_status
        self.rules_status, self.fail_path = rules_status, fail_path

    def __call__(self, method, path, query, body):
        if path == self.fail_path:
            return 500, f"boom {TOK}".encode()
        if not path.startswith(PROJ):
            return 404, None
        rest = path[len(PROJ):]
        if rest == "":
            if method == "PUT":
                self.project.update(body)
            return 200, self.project
        m = re.fullmatch(r"/protected_(branches|tags)(?:/([^/]+))?", rest)
        if m:
            store = self.branches if m[1] == "branches" else self.tags
            name = unquote(m[2] or "")
            if method == "GET":
                return (200, store[name]) if name in store else (404, {"message": "404"})
            if method == "POST":
                store[body["name"]] = body
                return 201, body
            return 200, store.get(name)
        if rest == "/approvals":
            if self.approvals_status != 200:
                return self.approvals_status, {"message": "forbidden"}
            if method == "POST":
                self.approvals.update(body)
            return 200, self.approvals
        if rest.startswith("/approval_rules"):
            if self.rules_status != 200:
                return self.rules_status, {"message": "404 Not Found"}
            return (200, self.rules) if method == "GET" else (201, body)
        return 404, None


@pytest.fixture
def gl(serve, monkeypatch):
    def start(**kw):
        stub = serve(GitLab(**kw))
        for k, v in {"GITLAB_URL": stub.base, "GITLAB_TOKEN": TOK, "GITLAB_PROJECT": "grp/proj",
                     "GITLAB_CI_CONFIG_PATH": CFG}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("GITLAB_APPROVALS", raising=False)
        monkeypatch.delenv("GITLAB_CA_FILE", raising=False)
        return stub
    return start


def run(*argv):
    return load(SCRIPT, "protect_bootstrap_t").main(list(argv))


def bpath(name):
    return PROJ + "/protected_branches/" + name.replace("/", "%2F").replace("*", "%2A")


@pytest.mark.parametrize("var", ["GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT",
                                 "GITLAB_CI_CONFIG_PATH"])
def test_missing_env_exits_1(gl, monkeypatch, capsys, var):
    stub = gl()
    monkeypatch.delenv(var)
    assert run("--dry-run") == 1
    assert var in capsys.readouterr().err and stub.requests == []


def test_http_gitlab_url_rejected(gl, monkeypatch, capsys):
    stub = gl()
    monkeypatch.setenv("GITLAB_URL", "http://gitlab.example.internal")
    assert run("--dry-run") == 1
    assert "GITLAB_URL" in capsys.readouterr().err and stub.requests == []


@pytest.mark.parametrize("value", ["foo.yml", "@grp/p", "x.yml@", "x.yml@grp", "a b.yml@g/p"])
def test_bad_ci_config_path_rejected(gl, monkeypatch, capsys, value):
    stub = gl()
    monkeypatch.setenv("GITLAB_CI_CONFIG_PATH", value)
    assert run("--dry-run") == 1
    assert "GITLAB_CI_CONFIG_PATH" in capsys.readouterr().err and stub.requests == []


def test_bad_approvals_mode_rejected(gl, monkeypatch, capsys):
    gl()
    monkeypatch.setenv("GITLAB_APPROVALS", "premium")
    assert run("--dry-run") == 1
    assert "GITLAB_APPROVALS" in capsys.readouterr().err


def test_empty_project_creates_all(gl):
    stub = gl(project={"id": 7, "only_allow_merge_if_pipeline_succeeds": False,
                       "allow_merge_on_skipped_pipeline": True, "ci_config_path": ""},
              branches={}, tags={})
    assert run() == 0
    w = stub.writes()
    want_branch = {"push_access_level": 40, "merge_access_level": 40, "allow_force_push": False}
    assert ("POST", PROJ + "/protected_branches", {"name": "enterprise", **want_branch}) in w
    assert ("POST", PROJ + "/protected_branches", {"name": "release/*", **want_branch}) in w
    assert ("POST", PROJ + "/protected_tags", {"name": "v*", "create_access_level": 40}) in w
    assert ("PUT", PROJ, {"only_allow_merge_if_pipeline_succeeds": True,
                          "allow_merge_on_skipped_pipeline": False,
                          "ci_config_path": CFG}) in w
    assert len(w) == 4


def test_in_sync_makes_no_writes(gl, capsys):
    stub = gl()
    assert run() == 0
    assert stub.writes() == [] and stub.requests
    assert "nothing to do" in capsys.readouterr().out


def test_dry_run_reports_drift_exit_2_and_only_gets(gl, capsys):
    stub = gl(branches={}, tags={})
    assert run("--dry-run") == 2
    assert stub.writes() == []
    out = capsys.readouterr().out
    assert "enterprise" in out and "release/*" in out and "v*" in out


def test_force_push_drift_patched_only_that_field(gl):
    stub = gl(branches={**GOOD_BRANCHES, "enterprise": branch("enterprise", force=True)})
    assert run() == 0
    assert stub.writes() == [("PATCH", bpath("enterprise"), {"allow_force_push": False})]


def test_push_level_drift_replaced(gl):
    stub = gl(branches={**GOOD_BRANCHES, "release/*": branch("release/*", push=30)})
    assert run() == 0
    assert stub.writes() == [("PATCH", bpath("release/*"), {
        "allowed_to_push": [{"id": 10, "_destroy": True}, {"access_level": 40}]})]


def test_merge_level_drift_replaced(gl):
    stub = gl(branches={**GOOD_BRANCHES, "enterprise": branch("enterprise", merge=30)})
    assert run() == 0
    assert stub.writes() == [("PATCH", bpath("enterprise"), {
        "allowed_to_merge": [{"id": 20, "_destroy": True}, {"access_level": 40}]})]


def test_user_entries_left_alone(gl):
    b = branch("enterprise")
    b["push_access_levels"].append(lvl(40, 11, user_id=99))
    stub = gl(branches={**GOOD_BRANCHES, "enterprise": b})
    assert run() == 0
    assert stub.writes() == []


def test_project_fields_put_only_differing(gl):
    stub = gl(project={**GOOD_PROJECT, "allow_merge_on_skipped_pipeline": True})
    assert run() == 0
    assert stub.writes() == [("PUT", PROJ, {"allow_merge_on_skipped_pipeline": False})]


def test_tag_level_drift_not_fixable_fails(gl, capsys):
    stub = gl(tags={"v*": {"name": "v*", "create_access_levels": [lvl(30, 30)]}})
    assert run("--dry-run") == 2
    assert run() == 1
    assert stub.writes() == [] and "by hand" in capsys.readouterr().err


def test_never_unprotects(gl):
    bad = {n: branch(n, push=30, merge=0, force=True) for n in ("enterprise", "release/*")}
    stub = gl(project={"id": 7}, branches=bad,
              tags={"v*": {"name": "v*", "create_access_levels": [lvl(0, 30)]}})
    run()
    run("--dry-run")
    assert not [r for r in stub.requests if r[0] == "DELETE"]


def test_unmanaged_protected_branch_untouched(gl):
    stub = gl(branches={**GOOD_BRANCHES, "feature/x": branch("feature/x", force=True)})
    assert run() == 0
    assert not [r for r in stub.requests if "feature" in r[1]]


def test_gate_mode_never_calls_approvals_endpoints(gl):
    stub = gl(approvals={}, rules=[])
    assert run() == 0
    assert not [r for r in stub.requests if "approval" in r[1]]


def test_native_mode_sets_approval_settings_and_rule(gl, monkeypatch):
    stub = gl(approvals={"merge_requests_author_approval": True,
                         "merge_requests_disable_committers_approval": False,
                         "reset_approvals_on_push": False}, rules=[])
    monkeypatch.setenv("GITLAB_APPROVALS", "native")
    assert run() == 0
    assert stub.writes() == [
        ("POST", PROJ + "/approvals", GOOD_APPROVALS),
        ("POST", PROJ + "/approval_rules", {"name": "any-approver", "rule_type": "any_approver",
                                            "approvals_required": 1})]


def test_native_mode_rule_count_drift_put(gl, monkeypatch):
    stub = gl(rules=[{**GOOD_RULES[0], "approvals_required": 0}])
    monkeypatch.setenv("GITLAB_APPROVALS", "native")
    assert run() == 0
    assert stub.writes() == [("PUT", PROJ + "/approval_rules/5", {"approvals_required": 1})]


def test_native_mode_in_sync_no_writes(gl, monkeypatch):
    stub = gl()
    monkeypatch.setenv("GITLAB_APPROVALS", "native")
    assert run() == 0 and stub.writes() == []
    assert run("--dry-run") == 0


@pytest.mark.parametrize("kw", [{"approvals_status": 403}, {"rules_status": 404}])
def test_native_mode_403_warns_exit_0(gl, monkeypatch, capsys, kw):
    stub = gl(rules=[], **kw)
    monkeypatch.setenv("GITLAB_APPROVALS", "native")
    assert run() == 0
    assert run("--dry-run") == 0
    assert "native approvals unavailable on this tier" in capsys.readouterr().out
    assert stub.writes() == []


def protect_env(base, **kw):
    return {"PATH": os.environ["PATH"], "SSL_CERT_FILE": os.environ["SSL_CERT_FILE"],
            "GITLAB_URL": base, "GITLAB_TOKEN": TOK, "GITLAB_PROJECT": "grp/proj",
            "GITLAB_CI_CONFIG_PATH": CFG, **kw}


@pytest.mark.parametrize("args", [(), ("--dry-run",)])
def test_tokens_never_printed(serve, args):
    stub = serve(GitLab(fail_path=PROJ))
    res = run_script(SCRIPT, *args, env=protect_env(stub.base))
    assert res.returncode == 1
    assert TOK not in res.stdout + res.stderr and "Traceback" not in res.stderr


def test_unexpected_exception_is_redacted(gl, monkeypatch, capsys):
    gl()
    mod = load(SCRIPT, "protect_bootstrap_t")

    def boom(*a, **k):
        raise RuntimeError(f"bug with {TOK}")

    monkeypatch.setattr(mod, "plan", boom)
    assert mod.main([]) == 1
    cap = capsys.readouterr()
    assert TOK not in cap.out + cap.err and "Traceback" not in cap.err


def test_numeric_project_and_trailing_slash_url(gl, monkeypatch):
    stub = gl()
    monkeypatch.setenv("GITLAB_PROJECT", "7")
    monkeypatch.setenv("GITLAB_URL", stub.base + "/")
    run("--dry-run")
    assert stub.requests[0][1] == "/api/v4/projects/7"


def test_protect_stdlib_only():
    assert stdlib_only(SCRIPT) <= {"glapi"}
    assert len(SCRIPT.read_text().splitlines()) < 300
