"""harbor_bootstrap.py against a stub Harbor v2.0 API (issue #5)."""

import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/enterprise/harbor/harbor_bootstrap.py"
PROJECTS = {"styx", "golden", "platform"}
ROBOT_SECRET = "S3CRET-xyz"
ADMIN_PW = "PW-abc"


class Stub:
    def __init__(self, projects=(), robots=(), fail_project_post=False, html=False,
                 robot_status=201, short_body=False, robot_reply=None):
        self.robot_reply = robot_reply  # override the robot POST body (API/proxy drift)
        self.html = html  # a proxy answering 200 with an HTML page
        self.robot_status = robot_status
        self.short_body = short_body  # connection drops mid-body
        self.projects = set(projects)
        self.robots = list(robots)
        self.fail_project_post = fail_project_post
        self.requests = []  # (method, path, body)


def _handler(stub):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=None):
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _record(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            stub.requests.append((self.command, self.path, body))
            return body

        def do_GET(self):
            self._record()
            path = urlparse(self.path).path
            if path.startswith("/api/v2.0/projects/"):
                name = unquote(path.rsplit("/", 1)[1])
                if name in stub.projects:
                    return self._send(200, {"name": name, "project_id": 1})
                return self._send(404, {"errors": [{"code": "NOT_FOUND"}]})
            if path == "/api/v2.0/robots":
                if stub.html:
                    self.send_response(200)
                    self.send_header("Content-Length", "6")
                    self.end_headers()
                    return self.wfile.write(b"<html>")
                if stub.short_body:
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    return self.wfile.write(b"[")
                return self._send(200, stub.robots)
            return self._send(404, {})

        def do_POST(self):
            body = self._record()
            path = urlparse(self.path).path
            if path == "/api/v2.0/projects":
                if stub.fail_project_post:
                    return self._send(500, {"errors": [{"code": "INTERNAL"}]})
                stub.projects.add(body["project_name"])
                return self._send(201)
            if path == "/api/v2.0/robots":
                if stub.robot_status != 201:
                    return self._send(stub.robot_status, {"errors": [{"code": "CONFLICT"}]})
                name = "robot$ci-push"
                stub.robots.append({"id": 7, "name": name, "level": "system"})
                if stub.robot_reply is not None:
                    return self._send(201, stub.robot_reply)
                return self._send(201, {"id": 7, "name": name, "secret": ROBOT_SECRET})
            return self._send(404, {})

        do_PUT = do_DELETE = do_POST

    return H


@pytest.fixture
def harbor(monkeypatch):
    servers = []

    def start(**kw):
        stub = Stub(**kw)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stub))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append((srv, stub))
        monkeypatch.setenv("HARBOR_URL", f"http://127.0.0.1:{srv.server_port}")
        monkeypatch.setenv("HARBOR_ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.delenv("HARBOR_CA_FILE", raising=False)
        return stub

    yield start
    for srv, stub in servers:
        srv.shutdown()
        # adversarial: no test may ever write to the users API
        assert not [r for r in stub.requests if "/users" in r[1] and r[0] != "GET"]


def run(*argv):
    spec = importlib.util.spec_from_file_location("harbor_bootstrap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(list(argv))


def writes(stub):
    return [r for r in stub.requests if r[0] != "GET"]


def test_creates_missing_projects_and_robot(harbor, tmp_path):
    stub = harbor()
    assert run("--secret-out", str(tmp_path / "robot")) == 0
    posts = [r for r in writes(stub) if r[1] == "/api/v2.0/projects"]
    assert {b["project_name"] for _, _, b in posts} == PROJECTS
    assert all(b["public"] is False for _, _, b in posts)
    (robot,) = [r for r in writes(stub) if r[1] == "/api/v2.0/robots"]
    body = robot[2]
    assert body["level"] == "system" and body["name"] == "ci-push"
    perms = {p["namespace"]: {(a["resource"], a["action"]) for a in p["access"]}
             for p in body["permissions"]}
    assert set(perms) == PROJECTS
    for acts in perms.values():
        assert {("repository", "push"), ("repository", "pull")} <= acts
    assert len(writes(stub)) == 4


def test_idempotent(harbor, tmp_path):
    stub = harbor(projects=PROJECTS, robots=[{"id": 7, "name": "robot$ci-push"}])
    assert run("--secret-out", str(tmp_path / "robot")) == 0
    assert writes(stub) == []
    assert not (tmp_path / "robot").exists()


def test_dry_run_no_writes(harbor, capsys):
    stub = harbor()
    assert run("--dry-run") == 0
    assert writes(stub) == [] and stub.requests
    out = capsys.readouterr().out
    assert "styx" in out and "ci-push" in out


def test_never_creates_users():
    src = SCRIPT.read_text()
    assert "/users" not in src


def test_secret_not_printed(harbor, tmp_path, capsys):
    harbor()
    out_file = tmp_path / "robot"
    assert run("--secret-out", str(out_file)) == 0
    cap = capsys.readouterr()
    for s in (ROBOT_SECRET, ADMIN_PW):
        assert s not in cap.out and s not in cap.err
    assert "robot$ci-push" in cap.out and str(out_file) in cap.out
    assert out_file.read_text().strip() == ROBOT_SECRET
    assert os.stat(out_file).st_mode & 0o777 == 0o600


def test_missing_env_fails(harbor, monkeypatch, capsys):
    harbor()
    monkeypatch.delenv("HARBOR_ADMIN_PASSWORD")
    assert run("--dry-run") != 0
    assert "HARBOR_ADMIN_PASSWORD" in capsys.readouterr().err


def test_http_error_fails(harbor, tmp_path, capsys):
    harbor(fail_project_post=True)
    assert run("--secret-out", str(tmp_path / "robot")) != 0
    assert "500" in capsys.readouterr().err


def test_unwritable_secret_out_fails_before_create(harbor, tmp_path, capsys):
    stub = harbor(projects=PROJECTS)
    assert run("--secret-out", str(tmp_path / "missing/dir/robot")) != 0
    assert "error:" in capsys.readouterr().err
    assert writes(stub) == []  # the one-time secret is never stranded


def test_non_json_body_fails_cleanly(harbor, tmp_path, capsys):
    harbor(projects=PROJECTS, html=True)
    assert run("--secret-out", str(tmp_path / "robot")) == 1
    assert "error:" in capsys.readouterr().err


def test_failed_robot_post_keeps_existing_secret_file(harbor, tmp_path):
    harbor(projects=PROJECTS, robot_status=409)
    out_file = tmp_path / "robot"
    out_file.write_text("OLD-secret\n")
    assert run("--secret-out", str(out_file)) == 1
    assert out_file.read_text() == "OLD-secret\n"
    assert [p.name for p in tmp_path.iterdir()] == ["robot"]  # no temp file left behind


def test_missing_ca_file_fails_cleanly(harbor, monkeypatch, capsys):
    harbor()
    monkeypatch.setenv("HARBOR_CA_FILE", "/nonexistent.pem")
    assert run("--dry-run") == 1
    assert "HARBOR_CA_FILE" in capsys.readouterr().err


def test_dropped_connection_is_http_error(harbor, tmp_path, capsys):
    harbor(projects=PROJECTS, short_body=True)
    assert run("--secret-out", str(tmp_path / "robot")) == 1
    err = capsys.readouterr().err
    assert "/robots" in err and "secret-out" not in err


@pytest.mark.parametrize("trailing", ["", "/"])
def test_directory_secret_out_fails_before_create(harbor, tmp_path, capsys, trailing):
    stub = harbor(projects=PROJECTS)
    (tmp_path / "d").mkdir()
    assert run("--secret-out", str(tmp_path / "d") + trailing) != 0
    assert "--secret-out" in capsys.readouterr().err
    assert writes(stub) == []  # the one-time secret is never stranded


def test_robot_reply_without_secret_fails_cleanly(harbor, tmp_path, capsys):
    harbor(projects=PROJECTS, robot_reply={"id": 7})
    assert run("--secret-out", str(tmp_path / "robot")) == 1
    assert "error:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []  # no temp file left behind


def test_url_without_scheme_fails_cleanly(harbor, monkeypatch, capsys):
    harbor()
    monkeypatch.setenv("HARBOR_URL", "harbor.example.internal")
    assert run("--dry-run") != 0
    assert "HARBOR_URL" in capsys.readouterr().err
