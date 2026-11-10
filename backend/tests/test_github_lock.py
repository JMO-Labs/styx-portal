"""github_lock.py: GitHub push-lock ruleset for the federal mirror (issue #16)."""

import os

import pytest

from tests.gitlab_stub import DEPLOY, load, run_script, stdlib_only

SCRIPT = DEPLOY / "gitlab-protect/github_lock.py"
TOK = "GHTOK-lock-secret"
RS = "/repos/o/r/rulesets"
MAIN = {"id": 1, "name": "MAIN", "target": "branch", "enforcement": "active",
        "source_type": "Repository", "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"],
                                                                  "exclude": []}},
        "rules": [{"type": "deletion"}], "bypass_actors": []}
LOCK = {"id": 2, "name": "federal-mirror-lock", "target": "branch", "enforcement": "active",
        "source_type": "Repository",
        "conditions": {"ref_name": {"include": ["refs/heads/enterprise", "refs/heads/release/*"],
                                    "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                  {"type": "update", "parameters": {"update_allows_fetch_and_merge": False}}],
        "bypass_actors": [{"actor_id": None, "actor_type": "DeployKey",
                           "bypass_mode": "always"}]}


def github(rulesets, fail=False):
    store = {r["id"]: dict(r) for r in rulesets}

    def route(method, path, query, body):
        if fail:
            return 500, f"echo {TOK}".encode()
        if path == RS and method == "GET":
            return 200, [{k: r[k] for k in ("id", "name", "target", "enforcement")}
                         for r in store.values()]
        if path == RS and method == "POST":
            store[9] = {**body, "id": 9}
            return 201, store[9]
        rid = int(path.rsplit("/", 1)[1]) if path.startswith(RS + "/") else None
        if rid in store:
            if method == "PUT":
                store[rid].update(body)
            return 200, store[rid]
        return 404, None
    return route


@pytest.fixture
def gh(serve, monkeypatch):
    def start(rulesets=(), fail=False):
        stub = serve(github(rulesets, fail))
        for k, v in {"GITHUB_API_URL": stub.base, "GITHUB_TOKEN": TOK,
                     "GITHUB_REPO": "o/r"}.items():
            monkeypatch.setenv(k, v)
        return stub
    return start


def run(*argv):
    return load(SCRIPT, "github_lock_t").main(list(argv))


def test_creates_ruleset_when_missing(gh):
    stub = gh([MAIN])
    assert run() == 0
    ((method, path, body),) = stub.writes()
    assert (method, path) == ("POST", RS)
    assert body["name"] == "federal-mirror-lock" and body["target"] == "branch"
    assert body["enforcement"] == "active"
    assert body["conditions"]["ref_name"]["include"] == ["refs/heads/enterprise",
                                                         "refs/heads/release/*"]
    assert sorted(r["type"] for r in body["rules"]) == ["deletion", "non_fast_forward", "update"]
    assert body["bypass_actors"] == [{"actor_id": None, "actor_type": "DeployKey",
                                      "bypass_mode": "always"}]


def test_in_sync_no_writes(gh):
    stub = gh([MAIN, LOCK])
    assert run() == 0 and run("--dry-run") == 0
    assert stub.writes() == []


@pytest.mark.parametrize("drift", [
    {"enforcement": "evaluate"},
    {"bypass_actors": LOCK["bypass_actors"] + [{"actor_id": 5, "actor_type": "Team",
                                                "bypass_mode": "always"}]},
    {"rules": [{"type": "deletion"}]},
    {"conditions": {"ref_name": {"include": ["refs/heads/enterprise"], "exclude": []}}},
])
def test_drift_put_updates_ruleset(gh, drift):
    stub = gh([MAIN, {**LOCK, **drift}])
    assert run() == 0
    ((method, path, body),) = stub.writes()
    assert (method, path) == ("PUT", RS + "/2") and body["name"] == "federal-mirror-lock"


def test_dry_run_exit_2_only_gets(gh, capsys):
    stub = gh([MAIN])
    assert run("--dry-run") == 2
    assert stub.writes() == [] and "federal-mirror-lock" in capsys.readouterr().out


def test_other_rulesets_untouched(gh):
    stub = gh([MAIN, {**LOCK, "enforcement": "disabled"}])
    run()
    assert not [r for r in stub.requests if r[1] == RS + "/1"]
    assert not [r for r in stub.requests if r[0] == "DELETE"]


@pytest.mark.parametrize("args", [(), ("--dry-run",)])
def test_token_never_printed(serve, args):
    stub = serve(github([], fail=True))
    env = {"PATH": os.environ["PATH"], "SSL_CERT_FILE": os.environ["SSL_CERT_FILE"],
           "GITHUB_API_URL": stub.base, "GITHUB_TOKEN": TOK, "GITHUB_REPO": "o/r"}
    res = run_script(SCRIPT, *args, env=env)
    assert res.returncode == 1
    assert TOK not in res.stdout + res.stderr and "Traceback" not in res.stderr


@pytest.mark.parametrize("var,value", [("GITHUB_REPO", "../x"), ("GITHUB_API_URL", "http://x"),
                                       ("GITHUB_TOKEN", "")])
def test_bad_env_rejected(gh, monkeypatch, capsys, var, value):
    stub = gh()
    monkeypatch.setenv(var, value)
    assert run("--dry-run") == 1
    assert var in capsys.readouterr().err and stub.requests == []


def test_lock_stdlib_only():
    assert stdlib_only(SCRIPT) <= {"glapi"}
    assert len(SCRIPT.read_text().splitlines()) < 300
