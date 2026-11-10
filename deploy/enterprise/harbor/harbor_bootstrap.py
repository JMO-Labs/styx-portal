#!/usr/bin/env python3
"""Idempotent Harbor bootstrap: private projects and the system robot "ci-push" (issue #5).

Standard library only. Env: HARBOR_URL, HARBOR_ADMIN_PASSWORD (user is always "admin"),
optional HARBOR_CA_FILE. GETs first and only creates what is missing. Never creates
local users: one local user locks Harbor to db_auth and blocks the Phase 2 OIDC switch.
Never prints the admin password or the robot secret.
"""

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

PROJECTS = ("styx", "golden", "platform")
ROBOT = "ci-push"
API = "/api/v2.0"


class HarborError(Exception):
    pass


class Client:
    def __init__(self, url, password, ca_file=None):
        self.url = url.rstrip("/")
        token = base64.b64encode(f"admin:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json",
                        "X-Is-Resource-Name": "true"}
        self.ctx = ssl.create_default_context(cafile=ca_file) if ca_file else None

    def call(self, method, path, body=None, ok_404=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + API + path, data=data, method=method,
                                     headers=dict(self.headers))
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if ok_404 and e.code == 404:
                return None
            raise HarborError(f"{method} {API}{path} -> HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise HarborError(f"{method} {API}{path} -> {e.reason}") from None
        return json.loads(raw) if raw else {}


def robot_body():
    access = [{"resource": "repository", "action": a} for a in ("push", "pull")]
    return {
        "name": ROBOT,
        "description": "GitLab CI push/pull (harbor_bootstrap.py)",
        "level": "system",
        "duration": -1,
        "disable": False,
        "permissions": [{"kind": "project", "namespace": p, "access": access}
                        for p in PROJECTS],
    }


def find_robot(client):
    # shortcut: first 100 system robots only; page through if that ever grows.
    robots = client.call("GET", "/robots?q=level%3Dsystem&page_size=100") or []
    return any(r.get("name") in (ROBOT, f"robot${ROBOT}") or
               str(r.get("name", "")).endswith(f"${ROBOT}") for r in robots)


def write_secret(path, secret):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # also tighten a pre-existing file
    with os.fdopen(fd, "w") as f:
        f.write(secret + "\n")


def plan(client):
    missing = [p for p in PROJECTS
               if client.call("GET", f"/projects/{quote(p)}", ok_404=True) is None]
    return missing, not find_robot(client)


def apply(client, missing, need_robot, secret_out):
    for p in missing:
        client.call("POST", "/projects",
                    {"project_name": p, "public": False, "metadata": {"public": "false"}})
        print(f"created project {p}")
    if need_robot:
        created = client.call("POST", "/robots", robot_body())
        write_secret(secret_out, created["secret"])
        print(f"created robot {created['name']}; secret written to {secret_out}")


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print planned actions only")
    ap.add_argument("--secret-out", help="file for the new robot secret (mode 0600)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    missing_env = [v for v in ("HARBOR_URL", "HARBOR_ADMIN_PASSWORD") if not os.environ.get(v)]
    if missing_env:
        print(f"error: missing env var {', '.join(missing_env)}", file=sys.stderr)
        return 2
    client = Client(os.environ["HARBOR_URL"], os.environ["HARBOR_ADMIN_PASSWORD"],
                    os.environ.get("HARBOR_CA_FILE") or None)
    try:
        missing, need_robot = plan(client)
        for p in missing:
            print(f"plan: create private project {p}")
        if need_robot:
            print(f"plan: create system robot {ROBOT} (push, pull on {', '.join(PROJECTS)})")
        if not missing and not need_robot:
            print("nothing to do")
        if args.dry_run:
            return 0
        if need_robot and not args.secret_out:
            print("error: --secret-out is required to create the robot", file=sys.stderr)
            return 2
        apply(client, missing, need_robot, args.secret_out)
    except HarborError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
