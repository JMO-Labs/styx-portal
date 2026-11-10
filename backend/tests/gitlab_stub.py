"""Shared HTTPS stub for the GitLab/GitHub settings-as-code scripts (issues #10, #16).

A test builds a `Stub` with a `route(method, path, query, body)` function that returns
(status, json_body) or (status, raw_bytes); every request is recorded as (method, path, body).
"""

import importlib.util
import json
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy/enterprise"


class Stub:
    def __init__(self, route):
        self.route = route
        self.requests = []  # (method, path, body)
        self.base = ""

    def writes(self):
        return [r for r in self.requests if r[0] != "GET"]


def _handler(stub):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _route(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            u = urlsplit(self.path)
            stub.requests.append((self.command, u.path, body))
            code, out = stub.route(self.command, u.path, parse_qs(u.query), body)
            data = out if isinstance(out, bytes) else (b"" if out is None
                                                       else json.dumps(out).encode())
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _route

    return H


@pytest.fixture(scope="session")
def stub_cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                    "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1", "-subj", "/CN=stub",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(d / "key.pem"),
                    "-out", str(d / "cert.pem")], check=True, capture_output=True)
    return d / "cert.pem", d / "key.pem"


@pytest.fixture
def serve(monkeypatch, stub_cert):
    """serve(route) -> Stub with .base = https://127.0.0.1:port; trusts the stub cert."""
    servers = []

    def start(route):
        stub = Stub(route)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stub))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*map(str, stub_cert))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        stub.base = f"https://127.0.0.1:{srv.server_port}"
        monkeypatch.setenv("SSL_CERT_FILE", str(stub_cert[0]))
        return stub

    yield start
    for srv in servers:
        srv.shutdown()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(path: Path, *argv, env=None):
    """Run a script in a subprocess (isolated mode) and return the CompletedProcess."""
    return subprocess.run([sys.executable, "-I", str(path), *argv], capture_output=True,
                          text=True, env=env, timeout=60)


def stdlib_only(path: Path) -> set:
    """Top-level imports of a script that are not stdlib (glapi is the shared sibling)."""
    import ast
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
    return names - set(sys.stdlib_module_names)
