#!/usr/bin/env python3
"""GitHub push-lock for the federal mirror branches as code (issue #16, ADR-0048).

Ensures one repository ruleset "federal-mirror-lock" on GITHUB_REPO: enterprise and release/*
accept no update, deletion or force push except from deploy keys (the GitLab push mirror's
write key). Apply only at cutover (docs/operate/gitlab-protect.md). Standard library only
(plus the sibling glapi module). Env: GITHUB_REPO (owner/repo), GITHUB_TOKEN, optional
GITHUB_API_URL (https). GETs first, writes only drift, never deletes or edits other rulesets,
never prints the token. Exit: 0 ok / in sync, 2 drift (--dry-run), 1 error.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gitlab-common"))
from glapi import ApiError, Client, guard, require_https  # noqa: E402

RULESET = {
    "name": "federal-mirror-lock",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/heads/enterprise", "refs/heads/release/*"],
                                "exclude": []}},
    "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}],
    # GitHub takes actor_id null for DeployKey: every deploy key with write access bypasses.
    "bypass_actors": [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}],
}
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def config(env):
    missing = [v for v in ("GITHUB_REPO", "GITHUB_TOKEN") if not env.get(v)]
    if missing:
        raise ApiError(f"missing env var {', '.join(missing)}")
    require_https(env, "GITHUB_API_URL")
    if not REPO_RE.match(env["GITHUB_REPO"]) or ".." in env["GITHUB_REPO"]:
        raise ApiError("GITHUB_REPO must be owner/repo")
    return env


def normal(rs):
    """Comparable form of a ruleset: only the fields this script manages."""
    ref = (rs.get("conditions") or {}).get("ref_name") or {}
    return (rs.get("target"), rs.get("enforcement"),
            sorted(ref.get("include") or []), sorted(ref.get("exclude") or []),
            sorted(r.get("type") for r in rs.get("rules") or []),
            sorted((a.get("actor_type"), str(a.get("actor_id")), a.get("bypass_mode"))
                   for a in rs.get("bypass_actors") or []))


def plan(gh, repo):
    """Return (method, path) to write, or None when in sync."""
    # shortcut: first 100 rulesets only; page through if a repo ever has more.
    listed = gh.call("GET", f"/repos/{repo}/rulesets?per_page=100&includes_parents=false")
    if not isinstance(listed, list):
        raise ApiError("GitHub ruleset list is not a list")
    mine = [r for r in listed if r.get("name") == RULESET["name"]]
    if not mine:
        return "POST", f"/repos/{repo}/rulesets"
    path = f"/repos/{repo}/rulesets/{int(mine[0]['id'])}"
    return None if normal(gh.call("GET", path)) == normal(RULESET) else ("PUT", path)


def apply(args):
    env = config(dict(os.environ))
    gh = Client(env.get("GITHUB_API_URL") or "https://api.github.com",
                {"Authorization": f"Bearer {env['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    write = plan(gh, env["GITHUB_REPO"])
    if write is None:
        print("nothing to do")
        return 0
    verb = "create" if write[0] == "POST" else "update"
    print(f"plan: {verb} ruleset {RULESET['name']} on {env['GITHUB_REPO']}")
    if args.dry_run:
        return 2
    gh.call(*write, RULESET)
    print(f"done: {verb} ruleset {RULESET['name']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="GET only; print planned actions")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    return guard(lambda: apply(args), [os.environ.get("GITHUB_TOKEN")])


if __name__ == "__main__":
    sys.exit(main())
