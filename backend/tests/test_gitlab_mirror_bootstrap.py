"""mirror_bootstrap.py against one HTTPS stub for GitLab and GitHub (issue #10)."""

import base64
import hashlib
import importlib.util
import json
import re
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

DIR = Path(__file__).resolve().parents[2] / "deploy/enterprise/gitlab-mirror"
SCRIPT = DIR / "mirror_bootstrap.py"
GLTOK, GHTOK = "GLTOK-secret", "GHTOK-secret"
PROJ = "/api/v4/projects/grp%2Fproj"
MIRRORS = PROJ + "/remote_mirrors"
KEYS = "/repos/o/r/keys"
PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINEWKEY gitlab-mirror"
GOOD_MIRROR = {"id": 5, "url": "ssh://git@github.com/o/r.git", "auth_method": "ssh_public_key",
               "enabled": True, "only_protected_branches": True, "keep_divergent_refs": True}
GOOD_KEY = {"id": 9, "title": "federal-gitlab-mirror", "key": PUB.rsplit(" ", 1)[0],
            "read_only": False}


class Stub:
    def __init__(self, mirrors=(), keys=(), pubkey_status=200, mirror_post_status=201,
                 html_path=None, fail_path=None):
        self.mirrors = [dict(m) for m in mirrors]
        self.keys = [dict(k) for k in keys]
        self.pubkey_status = pubkey_status
        self.mirror_post_status = mirror_post_status
        self.html_path = html_path  # a proxy answering 200 with an HTML page
        self.fail_path = fail_path  # answers 500 (body echoes the tokens)
        self.requests = []  # (method, path, body)


def _handler(stub):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=None, raw=None):
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None
                                                else b"")
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            path = urlparse(self.path).path
            stub.requests.append((self.command, path, body))
            if path in (stub.html_path, stub.fail_path):
                if path == stub.html_path:
                    return self._send(200, raw=b"<html>login</html>")
                return self._send(500, raw=f"oops {GLTOK} {GHTOK}".encode())
            m, verb = re.match(rf"{re.escape(MIRRORS)}(?:/(\d+))?(/public_key)?$", path), self.command
            if m and verb == "GET" and m[2]:
                if stub.pubkey_status != 200:
                    return self._send(stub.pubkey_status, {"message": "404 Not found"})
                return self._send(200, {"public_key": PUB})
            if m and verb == "GET":
                return self._send(200, stub.mirrors)
            if m and verb == "POST":
                if stub.mirror_post_status != 201:
                    return self._send(stub.mirror_post_status, {"message": "403 Forbidden"})
                stub.mirrors.append({**body, "id": 11, "url": "ssh://*****@github.com/o/r.git"})
                return self._send(201, stub.mirrors[-1])
            if m and verb == "PUT":
                mirror = next(x for x in stub.mirrors if x["id"] == int(m[1]))
                mirror.update(body)
                return self._send(200, mirror)
            if path == KEYS and verb == "GET":
                return self._send(200, stub.keys)
            if path == KEYS and verb == "POST":
                stub.keys.append({**body, "id": 20})
                return self._send(201, stub.keys[-1])
            if path.startswith(KEYS + "/") and verb == "DELETE":
                kid = int(path.rsplit("/", 1)[1])
                stub.keys = [k for k in stub.keys if k["id"] != kid]
                return self._send(204)
            return self._send(404, {"message": "not found"})

        do_GET = do_POST = do_PUT = do_DELETE = _route

    return H


@pytest.fixture(scope="session")
def cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                    "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1", "-subj", "/CN=stub",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(d / "key.pem"),
                    "-out", str(d / "cert.pem")], check=True, capture_output=True)
    return d / "cert.pem", d / "key.pem"


@pytest.fixture
def gl(monkeypatch, cert):
    servers = []

    def start(**kw):
        stub = Stub(**kw)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stub))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*map(str, cert))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        base = f"https://127.0.0.1:{srv.server_port}"
        for k, v in {"GITLAB_URL": base, "GITLAB_TOKEN": GLTOK, "GITLAB_PROJECT": "grp/proj",
                     "GITHUB_REPO": "o/r", "GITHUB_TOKEN": GHTOK, "GITHUB_API_URL": base,
                     "GITLAB_CA_FILE": str(cert[0]), "SSL_CERT_FILE": str(cert[0])}.items():
            monkeypatch.setenv(k, v)
        return stub

    yield start
    for srv in servers:
        srv.shutdown()


def run(*argv):
    spec = importlib.util.spec_from_file_location("mirror_bootstrap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(list(argv))


def writes(stub):
    return [r for r in stub.requests if r[0] != "GET"]


def test_fresh_creates_mirror_and_deploy_key(gl):
    stub = gl()
    assert run() == 0
    (post_m, post_k) = writes(stub)
    assert post_m[:2] == ("POST", MIRRORS)
    want = {"url": "ssh://git@github.com/o/r.git", "auth_method": "ssh_public_key",
            "enabled": True, "only_protected_branches": True, "keep_divergent_refs": True}
    assert {k: post_m[2][k] for k in want} == want
    pinned = [ln for ln in (DIR / "github_known_hosts").read_text().splitlines() if ln.strip()]
    assert post_m[2]["host_keys"] == pinned
    assert post_k == ("POST", KEYS, {"title": "federal-gitlab-mirror", "key": PUB,
                                     "read_only": False})


def test_second_run_is_noop(gl):
    stub = gl(mirrors=[GOOD_MIRROR], keys=[GOOD_KEY])
    assert run() == 0
    assert writes(stub) == [] and stub.requests


def test_dry_run_only_gets_and_exits_2_on_drift(gl, capsys):
    stub = gl()
    assert run("--dry-run") == 2
    assert writes(stub) == []
    out = capsys.readouterr().out
    assert "create push mirror" in out and "federal-gitlab-mirror" in out


def test_dry_run_in_sync_exits_0(gl):
    stub = gl(mirrors=[GOOD_MIRROR], keys=[GOOD_KEY])
    assert run("--dry-run") == 0
    assert writes(stub) == []


def test_dry_run_reports_key_drift(gl):
    stub = gl(mirrors=[GOOD_MIRROR])
    assert run("--dry-run") == 2
    assert writes(stub) == []


def test_updates_only_differing_fields(gl):
    stub = gl(mirrors=[{**GOOD_MIRROR, "only_protected_branches": False,
                        "keep_divergent_refs": False}], keys=[GOOD_KEY])
    assert run() == 0
    assert writes(stub) == [("PUT", f"{MIRRORS}/5", {"only_protected_branches": True,
                                                    "keep_divergent_refs": True})]


def test_matches_scrubbed_url(gl):
    stub = gl(mirrors=[{**GOOD_MIRROR, "url": "ssh://*****@github.com/o/r.git"}], keys=[GOOD_KEY])
    assert run() == 0
    assert writes(stub) == []


def test_other_mirrors_untouched(gl):
    other = {**GOOD_MIRROR, "id": 77, "url": "https://*****@gitlab.example.org/x.git",
             "enabled": False}
    stub = gl(mirrors=[other])
    assert run() == 0
    assert not [r for r in stub.requests if "/77" in r[1]]
    assert [r[:2] for r in writes(stub)] == [("POST", MIRRORS), ("POST", KEYS)]


def test_password_auth_mirror_refused(gl, capsys):
    stub = gl(mirrors=[{**GOOD_MIRROR, "auth_method": "password"}])
    assert run() == 1
    assert writes(stub) == []
    assert "remove" in capsys.readouterr().err.lower()


def test_deploy_key_rotation(gl):
    stub = gl(mirrors=[GOOD_MIRROR], keys=[{**GOOD_KEY, "key": "ssh-ed25519 AAAAOLD"}])
    assert run() == 0
    assert writes(stub) == [("DELETE", f"{KEYS}/9", None),
                            ("POST", KEYS, {"title": "federal-gitlab-mirror", "key": PUB,
                                            "read_only": False})]


def test_deploy_key_comment_ignored(gl):
    stub = gl(mirrors=[GOOD_MIRROR], keys=[{**GOOD_KEY, "key": GOOD_KEY["key"] + " other@host"}])
    assert run() == 0
    assert writes(stub) == []


def test_read_only_deploy_key_replaced(gl):
    stub = gl(mirrors=[GOOD_MIRROR], keys=[{**GOOD_KEY, "read_only": True}])
    assert run() == 0
    assert [r[:2] for r in writes(stub)] == [("DELETE", f"{KEYS}/9"), ("POST", KEYS)]
    assert writes(stub)[1][2]["read_only"] is False


def test_public_key_404_explains_version(gl, capsys):
    gl(mirrors=[GOOD_MIRROR], pubkey_status=404)
    assert run() == 1
    assert "17.9" in capsys.readouterr().err


def test_mirror_post_403_explains_instance_setting(gl, capsys):
    gl(mirror_post_status=403)
    assert run() == 1
    assert "mirror_available" in capsys.readouterr().err


def test_html_response_is_error(gl, capsys):
    gl(html_path=MIRRORS)
    assert run() == 1
    err = capsys.readouterr().err
    assert "JSON" in err and "Traceback" not in err


def _closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("case", ["403", "500-gitlab", "500-github", "html", "refused"])
def test_tokens_never_printed(gl, monkeypatch, capsys, case):
    kw = {"403": {"mirror_post_status": 403}, "500-gitlab": {"fail_path": MIRRORS},
          "500-github": {"mirrors": [GOOD_MIRROR], "fail_path": KEYS},
          "html": {"html_path": MIRRORS}, "refused": {}}[case]
    gl(**kw)
    if case == "refused":
        monkeypatch.setenv("GITLAB_URL", f"https://127.0.0.1:{_closed_port()}")
    for args, rc in (((), 1), (("--dry-run",), 2 if case == "403" else 1)):
        assert run(*args) == rc  # the 403 is a POST answer: a dry run never sends it
        cap = capsys.readouterr()
        for tok in (GLTOK, GHTOK):
            assert tok not in cap.out and tok not in cap.err


def test_unexpected_exception_is_redacted(gl, monkeypatch, capsys):
    gl()
    spec = importlib.util.spec_from_file_location("mirror_bootstrap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def boom(*a, **k):
        raise RuntimeError(f"bug with {GLTOK} and {GHTOK}")

    monkeypatch.setattr(mod, "plan", boom)
    assert mod.main([]) == 1
    cap = capsys.readouterr()
    assert GLTOK not in cap.err + cap.out and GHTOK not in cap.err + cap.out


def test_rejects_http_gitlab_url(gl, monkeypatch, capsys):
    stub = gl()
    monkeypatch.setenv("GITLAB_URL", "http://gitlab.example.internal")
    assert run("--dry-run") == 1
    assert "GITLAB_URL" in capsys.readouterr().err and stub.requests == []


@pytest.mark.parametrize("repo", ["../evil", "o/r/x", "o r", "o"])
def test_rejects_bad_github_repo(gl, monkeypatch, capsys, repo):
    stub = gl()
    monkeypatch.setenv("GITHUB_REPO", repo)
    assert run("--dry-run") == 1
    assert "GITHUB_REPO" in capsys.readouterr().err and stub.requests == []


@pytest.mark.parametrize("var", ["GITLAB_URL", "GITLAB_TOKEN", "GITLAB_PROJECT", "GITHUB_REPO",
                                 "GITHUB_TOKEN"])
def test_missing_env_exits_1(gl, monkeypatch, capsys, var):
    stub = gl()
    monkeypatch.delenv(var)
    assert run("--dry-run") == 1
    assert var in capsys.readouterr().err and stub.requests == []


def test_known_hosts_file_pinned():
    for line in (DIR / "github_known_hosts").read_text().splitlines():
        host, ktype, b64 = line.split()
        assert host == "github.com"
        if ktype == "ssh-ed25519":
            fp = base64.b64encode(hashlib.sha256(base64.b64decode(b64)).digest()).decode()
            assert "SHA256:" + fp.rstrip("=") == "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
            return
    pytest.fail("no ssh-ed25519 entry for github.com")


def test_stdlib_only_and_short():
    import sys
    src = SCRIPT.read_text()
    assert len(src.splitlines()) < 300
    imports = {ln.split()[1].split(".")[0] for ln in src.splitlines()
               if ln.startswith(("import ", "from "))}
    assert imports <= set(sys.stdlib_module_names) | {"glapi"}, imports
