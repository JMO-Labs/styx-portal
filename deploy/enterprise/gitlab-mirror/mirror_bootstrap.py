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
import http.client
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

KEY_TITLE = "federal-gitlab-mirror"
KNOWN_HOSTS = Path(__file__).resolve().parent / "github_known_hosts"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FLAGS = {"enabled": True, "only_protected_branches": True, "keep_divergent_refs": True}
REQUIRED = ("GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT", "GITHUB_REPO", "GITHUB_TOKEN")


class MirrorError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def redact(msg, secrets):
    """The one place error text passes through before it is printed."""
    for s in secrets:
        if s:
            msg = msg.replace(s, "***")
    return msg


class Client:
    def __init__(self, base, headers, ctx=None):
        self.base, self.headers, self.ctx = base.rstrip("/"), headers, ctx

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=dict(self.headers))
        if data is not None:
            req.add_header("Content-Type", "application/json")
        what = f"{method} {urlsplit(self.base).netloc}{path}"
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise MirrorError(f"{what} -> HTTP {e.code}", e.code) from None
        except urllib.error.URLError as e:
            raise MirrorError(f"{what} -> {e.reason}") from None
        except (OSError, http.client.HTTPException) as e:  # timeout, reset, short body
            raise MirrorError(f"{what} -> {e!r}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise MirrorError(f"{what} -> response is not JSON (proxy or login page?)") from None


def config(env):
    missing = [v for v in REQUIRED if not env.get(v)]
    if missing:
        raise MirrorError(f"missing env var {', '.join(missing)}")
    for var in ("GITLAB_URL", "GITHUB_API_URL"):
        if var in env and not env[var].startswith("https://"):
            raise MirrorError(f"{var} must start with https:// (tokens are never sent in clear)")
    if not REPO_RE.match(env["GITHUB_REPO"]) or ".." in env["GITHUB_REPO"]:
        raise MirrorError("GITHUB_REPO must be owner/repo")
    return env


def clients(env):
    try:
        ca = env.get("GITLAB_CA_FILE")
        gl_ctx = ssl.create_default_context(cafile=ca) if ca else None
    except (OSError, ssl.SSLError) as e:
        raise MirrorError(f"cannot read GITLAB_CA_FILE {ca}: {e}") from None
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
    mirrors_path = f"/projects/{quote(env['GITLAB_PROJECT'], safe='')}/remote_mirrors"
    mirrors = gl.call("GET", mirrors_path)
    if not isinstance(mirrors, list):
        raise MirrorError(f"GET {mirrors_path} did not return a list")
    matches = [m for m in mirrors if host_path(m.get("url")) == host_path(url)]
    if len(matches) > 1:
        raise MirrorError(f"{len(matches)} mirrors point at {url}; remove the extras by hand "
                          "in GitLab (Settings > Repository > Mirroring repositories)")
    mirror = matches[0] if matches else None
    if mirror and mirror.get("auth_method") != "ssh_public_key":
        raise MirrorError(f"mirror {mirror.get('id')} to {url} uses auth_method="
                          f"{mirror.get('auth_method')}; remove it manually in GitLab "
                          "(Settings > Repository > Mirroring repositories) and rerun")
    diff = {k: v for k, v in FLAGS.items() if mirror and mirror.get(k) != v}
    pub = public_key(gl, mirrors_path, mirror["id"]) if mirror else None
    keys = gh.call("GET", f"/repos/{env['GITHUB_REPO']}/keys?per_page=100")
    # shortcut: first 100 deploy keys only; page through if a repo ever has more.
    if not isinstance(keys, list):
        raise MirrorError("GitHub deploy key list is not a list")
    titled = [k for k in keys if k.get("title") == KEY_TITLE]
    in_sync = (pub is not None and len(titled) == 1 and titled[0].get("read_only") is False
               and key_parts(titled[0].get("key")) == key_parts(pub))
    return mirrors_path, mirror, diff, pub, ([] if in_sync else titled), in_sync


def public_key(gl, mirrors_path, mirror_id):
    try:
        pub = gl.call("GET", f"{mirrors_path}/{mirror_id}/public_key").get("public_key")
    except MirrorError as e:
        if e.code == 404:
            raise MirrorError("GitLab has no public_key endpoint (needs GitLab >= 17.9): copy "
                              "the mirror's SSH public key from the GitLab UI and add it on "
                              f"GitHub as write deploy key {KEY_TITLE}") from None
        raise
    if not pub or len(key_parts(pub)) != 2:
        raise MirrorError(f"mirror {mirror_id} has no SSH public key")
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
        except MirrorError as e:
            if e.code == 403:
                raise MirrorError("GitLab refused to create the mirror (HTTP 403): push "
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
    try:
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
    except MirrorError as e:
        print(f"error: {redact(str(e), secrets)}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - no traceback: it could carry a token
        print(f"error: unexpected {type(e).__name__}: {redact(str(e), secrets)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
