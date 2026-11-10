"""Shared stdlib client for the GitLab/GitHub settings-as-code scripts (issues #10, #16).

Errors never carry a response body (it may echo a token); `guard` is the one exit path that
prints them, redacted, without a traceback.
"""

import http.client
import json
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit


class ApiError(Exception):
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
            ctx = self.ctx or ssl.create_default_context()  # urlopen caches its default
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError(f"{what} -> HTTP {e.code}", e.code) from None
        except urllib.error.URLError as e:
            raise ApiError(f"{what} -> {e.reason}") from None
        except (OSError, http.client.HTTPException) as e:  # timeout, reset, short body
            raise ApiError(f"{what} -> {e!r}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise ApiError(f"{what} -> response is not JSON (proxy or login page?)") from None


def ssl_context(ca):
    """TLS context trusting GITLAB_CA_FILE, or None for the system store."""
    try:
        return ssl.create_default_context(cafile=ca) if ca else None
    except (OSError, ssl.SSLError) as e:
        raise ApiError(f"cannot read GITLAB_CA_FILE {ca}: {e}") from None


def project_path(project):
    """API path of a project given as numeric id or group/path."""
    return f"/projects/{quote(str(project), safe='')}"


def require_https(env, *names):
    for var in names:
        if var in env and not env[var].startswith("https://"):
            raise ApiError(f"{var} must start with https:// (tokens are never sent in clear)")


def guard(body, secrets):
    """Run body() -> exit code; print any error redacted and without a traceback."""
    try:
        return body()
    except ApiError as e:
        print(f"error: {redact(str(e), secrets)}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - no traceback: it could carry a token
        print(f"error: unexpected {type(e).__name__}: {redact(str(e), secrets)}",
              file=sys.stderr)
    return 1
