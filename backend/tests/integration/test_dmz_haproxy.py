"""Real HAProxy behaviour for the DMZ pair config (issue #7). Opt-in: HAPROXY_IT=1, `haproxy` on PATH
(or HAPROXY_BIN). CI runs it in the digest-pinned official haproxy image.

Throwaway CAs and leaves are generated per run. The backend is a Python TLS echo server standing
in for Traefik: it requires the HAProxy client cert and returns the request headers as JSON.
"""

import base64
import datetime as dt
import http.client
import ipaddress
import json
import os
import pwd
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.dmz_haproxy_checks import ROLE, render

pytestmark = pytest.mark.skipif(os.environ.get("HAPROXY_IT") != "1",
                                reason="set HAPROXY_IT=1 to run the HAProxy integration test")

HAPROXY = os.environ.get("HAPROXY_BIN") or shutil.which("haproxy") or "haproxy"
DOMAIN = "example.test"
LOGIN, PROVISION = f"login.{DOMAIN}", f"provision.{DOMAIN}"
PORTAL, BANNER = f"portal.{DOMAIN}", f"banner.{DOMAIN}"
NO_CARD = (ROLE / "files/errors/no-card.html").read_bytes()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---- PKI ------------------------------------------------------------------------------------


class Pki:
    def __init__(self, base: Path):
        self.base = base

    def _write(self, name: str, cert: x509.Certificate, key=None) -> Path:
        pem = cert.public_bytes(serialization.Encoding.PEM)
        if key is not None:
            pem += key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
        path = self.base / f"{name}.pem"
        path.write_bytes(pem)
        return path

    def ca(self, name: str):
        key = ec.generate_private_key(ec.SECP256R1())
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Test {name}")])
        cert = (self._builder(subj, subj, key.public_key())
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                               critical=True)
                .sign(key, hashes.SHA256()))
        return cert, key, self._write(f"{name}-ca", cert)

    def leaf(self, name: str, ca, sans: list[str] | None = None, client: bool = False):
        ca_cert, ca_key, _ = ca
        key = ec.generate_private_key(ec.SECP256R1())
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        b = (self._builder(subj, ca_cert.subject, key.public_key())
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .add_extension(x509.ExtendedKeyUsage(
                 [ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH]),
                 critical=False))
        if sans:
            names = [x509.IPAddress(ipaddress.ip_address(s)) if s[0].isdigit() else x509.DNSName(s)
                     for s in sans]
            b = b.add_extension(x509.SubjectAlternativeName(names), critical=False)
        cert = b.sign(ca_key, hashes.SHA256())
        return cert, self._write(name, cert, key)

    @staticmethod
    def _builder(subj, issuer, pub):
        now = dt.datetime.now(dt.UTC)
        return (x509.CertificateBuilder().subject_name(subj).issuer_name(issuer).public_key(pub)
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5))
                .not_valid_after(now + dt.timedelta(days=1)))


# ---- echo backend (stands in for Traefik) ---------------------------------------------------


class Echo(BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):  # noqa: N802
        Echo.hits.append(self.headers)
        body = json.dumps({k.lower(): self.headers.get_all(k) for k in self.headers.keys()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_echo(server_pem: Path, cluster_ca: Path) -> tuple[ThreadingHTTPServer, int]:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(server_pem)
    ctx.load_verify_locations(cluster_ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ---- fixture: PKI + echo + HAProxy ----------------------------------------------------------


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("dmz")
    pki = Pki(base)
    piv, bao, rogue, cluster = pki.ca("piv"), pki.ca("openbao"), pki.ca("rogue"), pki.ca("cluster")
    edge = pki.ca("edge")
    _, edge_pem = pki.leaf("edge-server", edge, [LOGIN, PROVISION, PORTAL, BANNER])
    _, traefik_pem = pki.leaf("traefik", cluster, ["traefik.test", "127.0.0.1"])
    _, hap_client = pki.leaf("haproxy-client", cluster, client=True)
    card, card_pem = pki.leaf("card-holder", piv, client=True)
    _, rogue_pem = pki.leaf("rogue-holder", rogue, client=True)
    _, bao_pem = pki.leaf("webhook", bao, client=True)
    srv, echo_port = start_echo(traefik_pem, cluster[2])
    port, hz = free_port(), free_port()
    run = base / "run"
    run.mkdir()
    overrides = {
        "dmz_domain": DOMAIN, "dmz_bind_addr": "127.0.0.1", "dmz_https_port": port,
        "dmz_healthz_bind": f"127.0.0.1:{hz}", "dmz_haproxy_dir": str(base),
        "dmz_haproxy_run_dir": str(run), "dmz_haproxy_user": "", "dmz_haproxy_log": "stdout format raw",
        "dmz_cert_public": str(edge_pem), "dmz_cert_login": str(edge_pem),
        "dmz_cert_provision": str(edge_pem), "dmz_piv_ca_file": str(piv[2]),
        "dmz_openbao_ca_file": str(bao[2]), "dmz_cluster_ca_file": str(cluster[2]),
        "dmz_haproxy_client_cert": str(hap_client), "dmz_traefik_sni": "traefik.test",
        "dmz_traefik_servers": [{"name": "traefik1", "addr": f"127.0.0.1:{echo_port}"}],
        "dmz_provision_allowed_cidrs": ["127.0.0.0/8"], "dmz_peers_port": free_port(),
        "dmz_login_rate_limit": 10000, "dmz_provision_rate_limit": 10000,
    }
    first, second = "dmz-proxy-01", "dmz-proxy-02"
    hosts = {first: {"dmz_peer_addr": "127.0.0.1"}, second: {"dmz_peer_addr": "127.0.0.2"}}
    (base / "errors").mkdir()
    (base / "errors/no-card.html").write_bytes(NO_CARD)
    (base / "crt-list.txt").write_text(render("crt-list.j2", overrides, first, hosts))
    cfg = base / "haproxy.cfg"
    cfg.write_text(render("haproxy.cfg.j2", overrides, first, hosts))
    check = subprocess.run([HAPROXY, "-c", "-f", str(cfg)], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    log = open(base / "haproxy.log", "wb")
    proc = subprocess.Popen([HAPROXY, "-db", "-f", str(cfg)], stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", hz, timeout=1)
            conn.request("GET", "/healthz")
            if conn.getresponse().status == 200:
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("haproxy did not start: " + (base / "haproxy.log").read_text())
    yield {"port": port, "card": card, "card_pem": card_pem, "rogue_pem": rogue_pem,
           "bao_pem": bao_pem, "edge_ca": edge[2], "echo_port": echo_port, "cfg": cfg}
    proc.terminate()
    proc.wait(10)
    srv.shutdown()


def client_ctx(env, cert: Path | None = None, max_ver=None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(env["edge_ca"])
    if cert:
        ctx.load_cert_chain(cert)
    if max_ver:
        ctx.maximum_version = max_ver
    return ctx


def get(env, sni: str, host: str | None = None, cert: Path | None = None, headers=None,
        ctx: ssl.SSLContext | None = None, session=None):
    """One HTTP/1.1 request over a fresh TLS connection. Returns (status, body, session, reused)."""
    ctx = ctx or client_ctx(env, cert)
    raw = socket.create_connection(("127.0.0.1", env["port"]), timeout=5)
    sock = ctx.wrap_socket(raw, server_hostname=sni, session=session)
    lines = ["GET / HTTP/1.1", f"Host: {host or sni}", "Connection: close"]
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    resp = http.client.HTTPResponse(sock)
    resp.begin()
    body = resp.read()
    session_out, reused = sock.session, sock.session_reused
    sock.close()
    return resp.status, body, session_out, reused


def echoed(body: bytes) -> dict:
    return json.loads(body)


SPOOF = {"Client-Cert": "AAAA", "Client-Cert-Chain": "AAAA", "X-Forwarded-For": "1.2.3.4",
         "X-Forwarded-Host": "evil.test", "Forwarded": "for=1.2.3.4"}


def card_der(env) -> bytes:
    return env["card"].public_bytes(serialization.Encoding.DER)


def test_valid_cert_sets_both_headers(env):
    status, body, *_ = get(env, LOGIN, f"{LOGIN}:443", cert=env["card_pem"])
    assert status == 200, body
    h = echoed(body)
    assert len(h["client-cert"]) == 1
    assert base64.b64decode(h["client-cert"][0]) == card_der(env)
    assert "client-cert-chain" in h and len(h["client-cert-chain"]) == 1
    assert h["x-forwarded-proto"] == ["https"]


@pytest.mark.parametrize("sni,cert", [(LOGIN, True), (LOGIN, False), (PORTAL, False),
                                      (BANNER, False), (PROVISION, "bao")])
def test_spoofed_header_stripped_on_every_host(env, sni, cert):
    pem = {True: env["card_pem"], "bao": env["bao_pem"], False: None}[cert]
    before = len(Echo.hits)
    status, body, *_ = get(env, sni, cert=pem, headers=SPOOF)
    if status != 200:  # login without a card: the 403 page, nothing reaches the backend
        assert (sni, cert, status) == (LOGIN, False, 403) and len(Echo.hits) == before
        return
    h = echoed(body)
    assert h.get("client-cert", ["-"])[0] != "AAAA" and h.get("client-cert-chain", ["-"])[0] != "AAAA"
    assert "1.2.3.4" not in json.dumps(h) and "evil.test" not in json.dumps(h)
    assert h["x-forwarded-for"] == ["127.0.0.1"]


def test_login_without_cert_gets_403_page(env):
    before = len(Echo.hits)
    status, body, *_ = get(env, LOGIN)
    assert status == 403 and body == NO_CARD
    assert len(Echo.hits) == before


def test_untrusted_ca_handshake_fails(env):
    with pytest.raises((ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected)):
        get(env, LOGIN, cert=env["rogue_pem"])


@pytest.mark.parametrize("sni", [PORTAL, BANNER])
def test_portal_and_banner_never_get_header(env, sni):
    status, body, *_ = get(env, sni, cert=env["card_pem"])
    assert status == 200
    h = echoed(body)
    assert "client-cert" not in h and "client-cert-chain" not in h


@pytest.mark.parametrize("sni,host", [(LOGIN, PORTAL), (PORTAL, LOGIN), (LOGIN, "LOGIN.other.test"),
                                      (PROVISION, LOGIN)])
def test_sni_host_mismatch_421(env, sni, host):
    cert = env["bao_pem"] if sni == PROVISION else env["card_pem"]
    before = len(Echo.hits)
    status, *_ = get(env, sni, host, cert=cert)
    assert status == 421 and len(Echo.hits) == before


def test_sni_host_match_is_case_and_port_insensitive(env):
    status, *_ = get(env, LOGIN, "Login.Example.Test:443", cert=env["card_pem"])
    assert status == 200


@pytest.mark.parametrize("max_ver", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
def test_resumed_session_never_half_set(env, max_ver):
    ctx = client_ctx(env, env["card_pem"], max_ver)
    _, _, session, _ = get(env, LOGIN, ctx=ctx)
    status, body, _, reused = get(env, LOGIN, ctx=ctx, session=session)
    if status == 403:
        assert body == NO_CARD
        return
    assert status == 200
    h = echoed(body)
    assert base64.b64decode(h["client-cert"][0]) == card_der(env), f"resumed={reused}"
    assert len(h["client-cert-chain"]) == 1


def test_provision_requires_cert(env):
    with pytest.raises((ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected)):
        get(env, PROVISION)
    with pytest.raises((ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected)):
        get(env, PROVISION, cert=env["card_pem"])  # PIV cert, wrong CA for provision
    status, body, *_ = get(env, PROVISION, cert=env["bao_pem"])
    assert status == 200
    assert "client-cert" not in echoed(body)


def test_backend_rejects_without_haproxy_client_cert(env):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with pytest.raises((ssl.SSLError, ConnectionResetError, http.client.RemoteDisconnected)):
        with ctx.wrap_socket(socket.create_connection(("127.0.0.1", env["echo_port"]), timeout=5),
                             server_hostname="traefik.test") as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            resp = http.client.HTTPResponse(s)
            resp.begin()


def test_config_check_production_values(tmp_path):
    """haproxy -c on the committed group_vars/defaults; only file paths point at a throwaway PKI."""
    pki = Pki(tmp_path)
    ca = pki.ca("any")
    _, pem = pki.leaf("edge", ca, [LOGIN])
    overrides = {"dmz_haproxy_dir": str(tmp_path), "dmz_haproxy_run_dir": str(tmp_path),
                 **{k: str(pem) for k in ("dmz_cert_public", "dmz_cert_login", "dmz_cert_provision",
                                          "dmz_haproxy_client_cert")},
                 **{k: str(ca[2]) for k in ("dmz_piv_ca_file", "dmz_openbao_ca_file",
                                            "dmz_cluster_ca_file")}}
    try:
        pwd.getpwnam("haproxy")
    except KeyError:
        overrides["dmz_haproxy_user"] = ""  # local runs without the haproxy user
    (tmp_path / "errors").mkdir()
    (tmp_path / "errors/no-card.html").write_bytes(NO_CARD)
    (tmp_path / "crt-list.txt").write_text(render("crt-list.j2", overrides))
    for host in ("dmz-proxy-01", "dmz-proxy-02"):
        cfg = tmp_path / f"{host}.cfg"
        cfg.write_text(render("haproxy.cfg.j2", overrides, host))
        check = subprocess.run([HAPROXY, "-c", "-f", str(cfg)], capture_output=True, text=True)
        assert check.returncode == 0, check.stdout + check.stderr
