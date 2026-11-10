#!/usr/bin/env python3
"""Idempotent GitLab -> GitHub push mirror with a GitLab-generated SSH key (issue #10).

Standard library only. Env: GITLAB_URL (https), GITLAB_TOKEN, GITLAB_PROJECT (path or id),
GITHUB_REPO (owner/repo), GITHUB_TOKEN, optional GITLAB_CA_FILE and GITHUB_API_URL.
Ensures one push mirror (protected branches only, keep divergent refs, pinned GitHub host keys)
and the GitHub write deploy key "federal-gitlab-mirror" holding the mirror's public key.
GETs first, writes only drift, never deletes a GitLab mirror, never prints a token.
Exit: 0 ok / in sync, 2 drift (--dry-run), 1 error.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gitlab-common"))
from glapi import ApiError, Client, guard, project_path, require_https, ssl_context  # noqa: E402

KEY_TITLE = "federal-gitlab-mirror"
KNOWN_HOSTS = Path(__file__).resolve().parent / "github_known_hosts"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FLAGS = {"enabled": True, "only_protected_branches": True, "keep_divergent_refs": True}
REQUIRED = ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT", "GITHUB_REPO", "GITHUB_TOKEN")


def config(env):
    missing = [v for v in REQUIRED if not env.get(v)]
    if missing:
        raise ApiError(f"missing env var {', '.join(missing)}")
    require_https(env, "GITLAB_URL", "GITHUB_API_URL")
    if not REPO_RE.match(env["GITHUB_REPO"]) or ".." in env["GITHUB_REPO"]:
        raise ApiError("GITHUB_REPO must be owner/repo")
    return env


def clients(env):
    gl_ctx = ssl_context(env.get("GITLAB_CA_FILE"))
    gl = Client(env["GITLAB_URL"] + "/api/v4", {"PRIVATE-TOKEN": env["GITLAB_TOKEN"],
                                                "Accept": "application/json"}, gl_ctx)
    gh = Client(env.get("GITHUB_API_URL") or "https://api.github.com",
                {"Authorization": f"Bearer {env['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    return gl, gh


def host_path(url):
    """Host and repo path of a mirror URL; userinfo is ignored (GitLab scrubs it)."""
    u = urlsplit(url or "")
    path = u.path.lower().rstrip("/")
    return (u.hostname or "").lower(), path[:-4] if path.endswith(".git") else path


def key_parts(key):
    return tuple((key or "").split()[:2])  # type and base64; the comment is ignored


def plan(gl, gh, env):
    """Return (mirrors path, mirror or None, field diff, public key, stale keys, key in sync)."""
    url = f"ssh://git@github.com/{env['GITHUB_REPO']}.git"
    mirrors_path = project_path(env['GITLAB_PROJECT']) + "/remote_mirrors"
    mirrors = gl.call("GET", mirrors_path)
    if not isinstance(mirrors, list):
        raise ApiError(f"GET {mirrors_path} did not return a list")
    matches = [m for m in mirrors if host_path(m.get("url")) == host_path(url)]
    if len(matches) > 1:
        raise ApiError(f"{len(matches)} mirrors point at {url}; remove the extras by hand "
                          "in GitLab (Settings > Repository > Mirroring repositories)")
    mirror = matches[0] if matches else None
    if mirror and mirror.get("auth_method") != "ssh_public_key":
        raise ApiError(f"mirror {mirror.get('id')} to {url} uses auth_method="
                          f"{mirror.get('auth_method')}; remove it manually in GitLab "
                          "(Settings > Repository > Mirroring repositories) and rerun")
    diff = {k: v for k, v in FLAGS.items() if mirror and mirror.get(k) != v}
    pub = public_key(gl, mirrors_path, mirror["id"]) if mirror else None
    keys = gh.call("GET", f"/repos/{env['GITHUB_REPO']}/keys?per_page=100")
    # shortcut: first 100 deploy keys only; page through if a repo ever has more.
    if not isinstance(keys, list):
        raise ApiError("GitHub deploy key list is not a list")
    titled = [k for k in keys if k.get("title") == KEY_TITLE]
    in_sync = (pub is not None and len(titled) == 1 and titled[0].get("read_only") is False
               and key_parts(titled[0].get("key")) == key_parts(pub))
    return mirrors_path, mirror, diff, pub, ([] if in_sync else titled), in_sync


def public_key(gl, mirrors_path, mirror_id):
    try:
        pub = gl.call("GET", f"{mirrors_path}/{mirror_id}/public_key").get("public_key")
    except ApiError as e:
        if e.code == 404:
            raise ApiError("GitLab has no public_key endpoint (needs GitLab >= 17.9): copy "
                              "the mirror's SSH public key from the GitLab UI and add it on "
                              f"GitHub as write deploy key {KEY_TITLE}") from None
        raise
    if not pub or len(key_parts(pub)) != 2:
        raise ApiError(f"mirror {mirror_id} has no SSH public key")
    return pub


def report(env, mirror, diff, stale, key_ok):
    actions = []
    if mirror is None:
        actions.append(f"create push mirror ssh://git@github.com/{env['GITHUB_REPO']}.git "
                       "(protected branches only, keep divergent refs, pinned host keys)")
    elif diff:
        actions.append(f"update mirror {mirror['id']}: {', '.join(sorted(diff))}")
    for k in stale:
        actions.append(f"delete GitHub deploy key {k.get('id')} ({KEY_TITLE})")
    if not key_ok:
        actions.append(f"add GitHub write deploy key {KEY_TITLE} with the mirror's public key")
    for a in actions:
        print(f"plan: {a}")
    if not actions:
        print("nothing to do")
    return actions


def ensure_mirror(gl, env, mirrors_path, mirror, diff):
    if mirror is None:
        hosts = [ln.strip() for ln in KNOWN_HOSTS.read_text().splitlines() if ln.strip()]
        body = {"url": f"ssh://git@github.com/{env['GITHUB_REPO']}.git",
                "auth_method": "ssh_public_key", **FLAGS, "host_keys": hosts}
        try:
            mirror = gl.call("POST", mirrors_path, body)
        except ApiError as e:
            if e.code == 403:
                raise ApiError("GitLab refused to create the mirror (HTTP 403): push "
                                  "mirroring is disabled on the instance or mirror_available="
                                  "false limits it to admins; ask a GitLab admin") from None
            raise
        print(f"created push mirror {mirror.get('id')}")
    elif diff:
        gl.call("PUT", f"{mirrors_path}/{mirror['id']}", diff)
        print(f"updated mirror {mirror['id']}: {', '.join(sorted(diff))}")
    return mirror


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="GET only; print planned actions")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    secrets = [os.environ.get("GITLAB_TOKEN"), os.environ.get("GITHUB_TOKEN")]
    return guard(lambda: apply(args), secrets)


def apply(args):
    env = config(dict(os.environ))
    gl, gh = clients(env)
    mirrors_path, mirror, diff, pub, stale, key_ok = plan(gl, gh, env)
    actions = report(env, mirror, diff, stale, key_ok)
    if args.dry_run or not actions:
        return 2 if actions else 0
    mirror = ensure_mirror(gl, env, mirrors_path, mirror, diff)
    if not key_ok:
        pub = pub or public_key(gl, mirrors_path, mirror["id"])
        repo = env["GITHUB_REPO"]
        for k in stale:  # deploy keys cannot be edited: replace them
            gh.call("DELETE", f"/repos/{repo}/keys/{int(k['id'])}")
            print(f"deleted deploy key {k['id']}")
        gh.call("POST", f"/repos/{repo}/keys",
                {"title": KEY_TITLE, "key": pub, "read_only": False})
        print(f"added write deploy key {KEY_TITLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
