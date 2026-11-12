#!/usr/bin/env python3
"""Idempotent Keycloak break-glass admin bootstrap (issue #131, ADR-0025).

Standard library only. Env: KC_URL, KC_ADMIN_USER, KC_ADMIN_PASSWORD, optional KC_CA_FILE,
BREAKGLASS_{1,2}_USERNAME and BREAKGLASS_{1,2}_PASSWORD (from the OpenBao ExternalSecret).
Creates exactly two local admins in the master realm with required action CONFIGURE_TOTP,
and binds a master browser flow that always requires password and OTP (no X.509).
Never prints any password.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

REALM = "master"
FLOW = "breakglass-browser"
ADMIN_ROLE = "admin"
LISTENER = "micrometer-user-event-metrics"


class KCError(Exception):
    pass


class Client:
    def __init__(self, url, user, password, ca_file=None):
        if not url.startswith(("https://", "http://")):
            raise KCError(f"KC_URL must start with https:// (got {url!r})")
        self.url = url.rstrip("/")
        try:
            self.ctx = ssl.create_default_context(cafile=ca_file) if ca_file else None
        except (OSError, ssl.SSLError) as e:
            raise KCError(f"cannot read KC_CA_FILE {ca_file}: {e}") from None
        form = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli",
                                       "username": user, "password": password}).encode()
        req = urllib.request.Request(f"{self.url}/realms/{REALM}/protocol/openid-connect/token",
                                     data=form, method="POST")
        tok = self._send(req, "token request")
        if not isinstance(tok, dict) or "access_token" not in tok:
            raise KCError("token request returned no access_token")
        self.token = tok["access_token"]

    def _send(self, req, what):
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise KCError(f"{what} -> HTTP {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise KCError(f"{what} -> {getattr(e, 'reason', e)!r}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise KCError(f"{what} -> response is not JSON") from None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}/admin/realms/{REALM}{path}", data=data,
                                     method=method, headers={
                                         "Authorization": f"Bearer {self.token}",
                                         "Content-Type": "application/json"})
        return self._send(req, f"{method} {path.split('?')[0]}")


def read_env():
    names = ["KC_URL", "KC_ADMIN_USER", "KC_ADMIN_PASSWORD"]
    for i in (1, 2):
        names += [f"BREAKGLASS_{i}_USERNAME", f"BREAKGLASS_{i}_PASSWORD"]
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ValueError(f"missing env var {', '.join(missing)}")
    users = [(os.environ[f"BREAKGLASS_{i}_USERNAME"], os.environ[f"BREAKGLASS_{i}_PASSWORD"])
             for i in (1, 2)]
    if users[0][0] == users[1][0]:
        raise ValueError("BREAKGLASS_1_USERNAME and BREAKGLASS_2_USERNAME must differ")
    return users


def ensure_user(kc, username, password, dry):
    found = kc.call("GET", f"/users?username={urllib.parse.quote(username)}&exact=true")
    if found:
        print(f"user {username}: exists")
        return False
    print(f"plan: create break-glass admin {username} (CONFIGURE_TOTP)")
    if dry:
        return True
    kc.call("POST", "/users", {"username": username, "enabled": True, "emailVerified": True,
                               "requiredActions": ["CONFIGURE_TOTP"]})
    uid = kc.call("GET", f"/users?username={urllib.parse.quote(username)}&exact=true")[0]["id"]
    kc.call("PUT", f"/users/{uid}/reset-password",
            {"type": "password", "value": password, "temporary": False})
    role = kc.call("GET", f"/roles/{ADMIN_ROLE}")
    kc.call("POST", f"/users/{uid}/role-mappings/realm", [role])
    return True


def _otp_subflow(execs, otp):
    """Nearest preceding subflow execution one level above the OTP form."""
    i = execs.index(otp)
    for e in reversed(execs[:i]):
        if e.get("authenticationFlow") and e.get("level", 0) == otp.get("level", 0) - 1:
            return e
    return None


def ensure_events_listener(kc, dry):
    cfg = kc.call("GET", "/events/config")
    listeners = list(cfg.get("eventsListeners") or [])
    if LISTENER in listeners:
        return False
    print(f"plan: add {LISTENER} to master eventsListeners")
    if not dry:
        kc.call("PUT", "/events/config", {**cfg, "eventsListeners": listeners + [LISTENER]})
    return True


def ensure_flow(kc, dry):
    changed = False
    exists = True
    if not any(f.get("alias") == FLOW for f in kc.call("GET", "/authentication/flows")):
        print(f"plan: copy browser flow to {FLOW}")
        changed = exists = False
        if not dry:
            kc.call("POST", "/authentication/flows/browser/copy", {"newName": FLOW})
    if exists or not dry:
        execs = kc.call("GET", f"/authentication/flows/{FLOW}/executions")
        for e in execs:
            # OTP form, and the (level-0 relative) subflow holding it, must be REQUIRED.
            # The subflow's own condition is left untouched (a disabled one skips the subflow).
            if e.get("providerId") == "auth-otp-form":
                targets = [e, _otp_subflow(execs, e)]
            else:
                continue
            for t in targets:
                if t and t.get("requirement") != "REQUIRED":
                    print(f"plan: {t.get('providerId') or t.get('displayName')} -> REQUIRED")
                    changed = True
                    if not dry:
                        kc.call("PUT", f"/authentication/flows/{FLOW}/executions",
                                {**t, "requirement": "REQUIRED"})
    realm = kc.call("GET", "")
    if realm.get("browserFlow") != FLOW:
        print(f"plan: bind master browserFlow={FLOW}")
        changed = True
        if not dry:
            kc.call("PUT", "", {**realm, "browserFlow": FLOW})
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print planned actions only")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        users = read_env()
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        kc = Client(os.environ["KC_URL"], os.environ["KC_ADMIN_USER"],
                    os.environ["KC_ADMIN_PASSWORD"], os.environ.get("KC_CA_FILE") or None)
        changed = [ensure_user(kc, u, p, args.dry_run) for u, p in users]
        changed.append(ensure_flow(kc, args.dry_run))
        changed.append(ensure_events_listener(kc, args.dry_run))
        if not any(changed):
            print("nothing to do")
    except KCError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
