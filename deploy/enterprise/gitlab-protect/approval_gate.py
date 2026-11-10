#!/usr/bin/env python3
"""Free-tier merge approval gate for the federal GitLab (issue #16, ADR-0048).

Runs as job approval-gate from the external ci-policy config. Passes only when someone other
than the MR author approved strictly after the latest diff version (push). Standard library only
and self-contained: the job downloads this one file from the ci-policy project.
Env: CI_API_V4_URL (https), CI_PROJECT_ID, CI_MERGE_REQUEST_IID, APPROVAL_GATE_TOKEN
(read_api, Reporter), optional GITLAB_CA_FILE. Exit 0 pass, 1 fail or error. Never prints the token.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote

REQUIRED = ("CI_API_V4_URL", "CI_PROJECT_ID", "CI_MERGE_REQUEST_IID", "APPROVAL_GATE_TOKEN")
APPROVED_NOTE = "approved this merge request"


class GateError(Exception):
    pass


class Api:
    def __init__(self, base, token, ca=None):
        self.base, self.token = base.rstrip("/"), token
        self.ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={"PRIVATE-TOKEN": self.token})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:  # the body may echo the token: never print it
            raise GateError(f"GET {path} -> HTTP {e.code}") from None
        except (OSError, ValueError) as e:
            raise GateError(f"GET {path} -> {type(e).__name__}") from None


def parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def decide(author, approvals, latest_version_at):
    """approvals: [(user_id, approved_at iso or None)]. Pass only on a non-author approval
    strictly after the latest push; an approval without a time does not count."""
    pushed = parse(latest_version_at)
    if pushed is None:
        return False, "no diff version time found: failing closed"
    if not approvals:
        return False, "no approvals"
    for user, at in approvals:
        when = parse(at)
        if user != author and when is not None and when > pushed:
            return True, f"approved by user {user} at {at}, after the latest push {pushed}"
    return False, (f"no approval by someone other than the author (user {author}) after the "
                   f"latest push {latest_version_at}; approve again, then rerun approval-gate")


def fetch(api, project, iid):
    """Return (author id, [(approver id, time)], latest diff version time)."""
    mr = f"/projects/{quote(str(project), safe='')}/merge_requests/{int(iid)}"
    author = api.get(mr)["author"]["id"]
    approved_by = api.get(mr + "/approvals").get("approved_by") or []
    versions = api.get(mr + "/versions")
    latest = max((v["created_at"] for v in versions), key=parse, default=None)
    approvals, note_times = [], None
    for a in approved_by:
        user, at = a["user"]["id"], a.get("approved_at")
        if not at:  # CE has no approved_at: use that user's latest "approved" system note
            if note_times is None:
                note_times = approval_notes(api, mr)
            at = note_times.get(user)
        approvals.append((user, at))
    return author, approvals, latest


def approval_notes(api, mr):
    # shortcut: newest 100 notes only; page through if a long MR thread hides the approval.
    notes = api.get(mr + "/notes?sort=desc&order_by=created_at&per_page=100")
    latest = {}
    for n in notes:
        if n.get("system") and n.get("body") == APPROVED_NOTE:
            user, at = n["author"]["id"], n["created_at"]
            if user not in latest or parse(at) > parse(latest[user]):
                latest[user] = at
    return latest


def main():
    env = os.environ
    try:
        missing = [v for v in REQUIRED if not env.get(v)]
        if missing:
            raise GateError(f"missing env var {', '.join(missing)}")
        if not env["CI_API_V4_URL"].startswith("https://"):
            raise GateError("CI_API_V4_URL must start with https://")
        api = Api(env["CI_API_V4_URL"], env["APPROVAL_GATE_TOKEN"], env.get("GITLAB_CA_FILE"))
        ok, reason = decide(*fetch(api, env["CI_PROJECT_ID"], env["CI_MERGE_REQUEST_IID"]))
    except Exception as e:  # noqa: BLE001 - fail closed, no traceback (it could carry a token)
        msg = str(e).replace(env.get("APPROVAL_GATE_TOKEN") or "\0", "***")
        print(f"approval-gate: error: {type(e).__name__}: {msg}", file=sys.stderr)
        return 1
    print(f"approval-gate: {'PASS' if ok else 'FAIL'}: {reason}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
