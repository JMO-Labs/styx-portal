#!/usr/bin/env python3
"""Protected branches, tags and merge checks on the federal GitLab as code (issue #16).

Standard library only (plus the sibling glapi module). Env: GITLAB_URL (https), GITLAB_TOKEN,
GITLAB_PROJECT (path or id), GITLAB_CI_CONFIG_PATH (<file>@<group>/<project>), optional
GITLAB_CA_FILE and GITLAB_APPROVALS (gate, the default, or native = also set Premium approvals).
GETs first, writes only drift, never unprotects, never touches unmanaged branches or tags,
never prints a token. Exit: 0 ok / in sync, 2 drift (--dry-run), 1 error.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gitlab-common"))
from glapi import ApiError, Client, guard, project_path, require_https, ssl_context  # noqa: E402

# ---- desired state (change here, dry-run, MR, apply: docs/operate/gitlab-protect.md) ----
PUSH_LEVEL = 40  # Maintainers, per the AC. 0 (No one) forces every change through an MR.
MERGE_LEVEL = 40
BRANCHES = ("enterprise", "release/*")
TAG = "v*"
TAG_CREATE_LEVEL = 40
PROJECT = {"only_allow_merge_if_pipeline_succeeds": True,
           "allow_merge_on_skipped_pipeline": False}  # + ci_config_path from env
APPROVAL_SETTINGS = {"merge_requests_author_approval": False,
                     "merge_requests_disable_committers_approval": True,
                     "reset_approvals_on_push": True}
APPROVAL_RULE = {"name": "any-approver", "rule_type": "any_approver", "approvals_required": 1}

REQUIRED = ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT", "GITLAB_CI_CONFIG_PATH")
CI_CONFIG_RE = re.compile(r"^[\w./-]+\.ya?ml@[\w.-]+(/[\w.-]+)+$")
TIER_WARNING = "native approvals unavailable on this tier; approval-gate still enforces"


def config(env):
    missing = [v for v in REQUIRED if not env.get(v)]
    if missing:
        raise ApiError(f"missing env var {', '.join(missing)}")
    require_https(env, "GITLAB_URL")
    if not CI_CONFIG_RE.match(env["GITLAB_CI_CONFIG_PATH"]):
        raise ApiError("GITLAB_CI_CONFIG_PATH must be <file>.yml@<group>/<project>")
    if env.setdefault("GITLAB_APPROVALS", "gate") not in ("gate", "native"):
        raise ApiError("GITLAB_APPROVALS must be gate or native")
    return env


def get_or_none(gl, path):
    try:
        return gl.call("GET", path)
    except ApiError as e:
        if e.code == 404:
            return None
        raise


def level_change(entries, want):
    """allowed_to_* entries replacing role levels != want; user/group/key entries are kept."""
    roles = [e for e in entries or [] if not any(e.get(k) for k in
                                                 ("user_id", "group_id", "deploy_key_id"))]
    change = [{"id": e["id"], "_destroy": True} for e in roles if e.get("access_level") != want]
    if not any(e.get("access_level") == want for e in roles):
        change.append({"access_level": want})
    return change


def plan_branch(gl, proj, name):
    path = f"{proj}/protected_branches/{quote(name, safe='')}"
    cur = get_or_none(gl, path)
    if cur is None:
        return [(f"protect branch {name}", "POST", f"{proj}/protected_branches",
                 {"name": name, "push_access_level": PUSH_LEVEL,
                  "merge_access_level": MERGE_LEVEL, "allow_force_push": False})]
    body = {}
    if cur.get("allow_force_push") is not False:
        body["allow_force_push"] = False
    for key, field, want in (("allowed_to_push", "push_access_levels", PUSH_LEVEL),
                             ("allowed_to_merge", "merge_access_levels", MERGE_LEVEL)):
        change = level_change(cur.get(field), want)
        if change:
            body[key] = change
    return [(f"update branch {name}: {', '.join(body)}", "PATCH", path, body)] if body else []


def plan_tag(gl, proj, manual):
    cur = get_or_none(gl, f"{proj}/protected_tags/{quote(TAG, safe='')}")
    if cur is None:
        return [(f"protect tag {TAG}", "POST", f"{proj}/protected_tags",
                 {"name": TAG, "create_access_level": TAG_CREATE_LEVEL})]
    if level_change(cur.get("create_access_levels"), TAG_CREATE_LEVEL):
        # The API cannot edit a protected tag and this script never unprotects.
        manual.append(f"protected tag {TAG} create level is not {TAG_CREATE_LEVEL}: fix it by "
                      "hand in Settings > Repository > Protected tags")
    return []


def plan_native(gl, proj):
    try:
        cur = gl.call("GET", f"{proj}/approvals")
        diff = any(cur.get(k) != v for k, v in APPROVAL_SETTINGS.items())
        acts = [("set approval settings", "POST", f"{proj}/approvals", APPROVAL_SETTINGS)]
        acts = acts if diff else []
        rules = [r for r in gl.call("GET", f"{proj}/approval_rules")
                 if r.get("rule_type") == "any_approver"]
    except ApiError as e:
        if e.code in (403, 404):
            print(f"warning: {TIER_WARNING}")
            return []
        raise
    want = APPROVAL_RULE["approvals_required"]
    if not rules:
        acts.append(("add any_approver rule", "POST", f"{proj}/approval_rules", APPROVAL_RULE))
    elif rules[0].get("approvals_required") != want:
        acts.append((f"set any_approver rule {rules[0]['id']} to {want}", "PUT",
                     f"{proj}/approval_rules/{int(rules[0]['id'])}", {"approvals_required": want}))
    return acts


def plan(gl, env):
    """Return (actions, native, manual): actions are (description, method, path, body);
    native are the Premium approval actions, the only ones allowed to fail softly."""
    proj, manual = project_path(env["GITLAB_PROJECT"]), []
    want = {**PROJECT, "ci_config_path": env["GITLAB_CI_CONFIG_PATH"]}
    cur = gl.call("GET", proj)
    diff = {k: v for k, v in want.items() if cur.get(k) != v}
    actions = [(f"update project: {', '.join(diff)}", "PUT", proj, diff)] if diff else []
    for name in BRANCHES:
        actions += plan_branch(gl, proj, name)
    actions += plan_tag(gl, proj, manual)
    native = plan_native(gl, proj) if env["GITLAB_APPROVALS"] == "native" else []
    return actions, native, manual


def apply(args):
    env = config(dict(os.environ))
    gl = Client(env["GITLAB_URL"].rstrip("/") + "/api/v4",
                {"PRIVATE-TOKEN": env["GITLAB_TOKEN"], "Accept": "application/json"},
                ssl_context(env.get("GITLAB_CA_FILE")))
    actions, native, manual = plan(gl, env)
    for desc, *_ in actions + native:
        print(f"plan: {desc}")
    for m in manual:
        print(f"plan: manual: {m}")
    if not actions and not native and not manual:
        print("nothing to do")
        return 0
    if args.dry_run:
        return 2
    for act in actions + native:
        desc, method, path, body = act
        try:
            gl.call(method, path, body)
        except ApiError as e:
            if e.code in (403, 404) and act in native:
                print(f"warning: {TIER_WARNING}")
                continue
            raise
        print(f"done: {desc}")
    if manual:
        raise ApiError("; ".join(manual))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="GET only; print planned actions")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    return guard(lambda: apply(args), [os.environ.get("GITLAB_TOKEN")])


if __name__ == "__main__":
    sys.exit(main())
