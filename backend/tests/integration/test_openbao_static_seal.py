"""Real OpenBao 2.7.2 static seal (issue #4, C1). Opt-in: OPENBAO_IT=1 and `bao` on PATH.

Single-node raft on 127.0.0.1 with a throwaway 32-byte key from os.urandom. CI installs the
sha256-pinned release binary (same build as the pinned image), so the runner needs no Docker.
TLS is off on this loopback-only test listener; the deployed config is checked elsewhere.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(os.environ.get("OPENBAO_IT") != "1",
                                reason="set OPENBAO_IT=1 to run the OpenBao integration test")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Node:
    def __init__(self, base: Path, name: str):
        self.dir = base / name
        (self.dir / "data").mkdir(parents=True)
        self.port, self.cport = free_port(), free_port()
        self.addr = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.token = ""

    def write_key(self, kid: str, raw: bytes) -> Path:
        path = self.dir / f"{kid}.key"
        path.write_bytes(raw)
        path.chmod(0o400)
        return path

    def config(self, kid: str, key: Path, prev: tuple[str, Path] | None) -> Path:
        previous = (f'  previous_key_id = "{prev[0]}"\n  previous_key = "file://{prev[1]}"\n'
                    if prev else "")
        cfg = self.dir / "config.hcl"
        cfg.write_text(f"""
api_addr = "{self.addr}"
cluster_addr = "https://127.0.0.1:{self.cport}"
listener "tcp" {{
  address = "127.0.0.1:{self.port}"
  cluster_address = "127.0.0.1:{self.cport}"
  tls_disable = true
}}
storage "raft" {{
  path = "{self.dir / 'data'}"
  node_id = "{self.dir.name}"
}}
seal "static" {{
  current_key_id = "{kid}"
  current_key = "file://{key}"
{previous}}}
""")
        return cfg

    def start(self, kid: str, key: Path, prev: tuple[str, Path] | None = None) -> None:
        cfg = self.config(kid, key, prev)
        log = open(self.dir / "server.log", "ab")
        self.proc = subprocess.Popen(["bao", "server", f"-config={cfg}"], stdout=log,
                                     stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return
            if self.bao("status", check=False).returncode in (0, 2):
                return
            time.sleep(0.3)
        raise AssertionError("bao server did not start: " + self.log())

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=30)

    def log(self) -> str:
        return (self.dir / "server.log").read_text(errors="replace")[-3000:]

    def bao(self, *args, check=True, token=None) -> subprocess.CompletedProcess:
        env = {**os.environ, "BAO_ADDR": self.addr, "BAO_TOKEN": token or self.token}
        res = subprocess.run(["bao", *args], env=env, capture_output=True, text=True, timeout=60)
        if check and res.returncode != 0:
            raise AssertionError(f"bao {args[:3]} failed: {res.stderr}\n{self.log()}")
        return res

    def status(self) -> dict:
        res = self.bao("status", "-format=json", check=False)
        return json.loads(res.stdout) if res.stdout.strip() else {}

    def wait_unsealed(self, timeout=30) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.status()
            if st.get("sealed") is False and st.get("initialized"):
                return st
            time.sleep(0.5)
        raise AssertionError(f"not unsealed: {self.status()}\n{self.log()}")

    def init(self) -> dict:
        out = json.loads(self.bao("operator", "init", "-recovery-shares=3",
                                  "-recovery-threshold=2", "-format=json").stdout)
        self.token = out["root_token"]
        self.wait_unsealed()
        self.wait_leader()
        return out

    def wait_leader(self, timeout=30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = self.bao("secrets", "list", "-format=json", check=False)
            if res.returncode == 0:
                return
            time.sleep(0.5)
        raise AssertionError("no active node: " + self.log())

    def put_secret(self) -> None:
        self.bao("secrets", "enable", "-path=kv", "kv-v2")
        self.bao("kv", "put", "kv/app", "answer=42")

    def read_secret(self) -> str:
        return self.bao("kv", "get", "-field=answer", "kv/app").stdout.strip()


@pytest.fixture
def nodes(tmp_path):
    assert shutil.which("bao"), "OPENBAO_IT=1 needs the pinned bao binary on PATH"
    made: list[Node] = []

    def make(name: str) -> Node:
        n = Node(tmp_path, name)
        made.append(n)
        return n

    yield make
    for n in made:
        n.stop()


def test_auto_unseals_after_restart(nodes):
    n = nodes("n1")
    key = n.write_key("k1", os.urandom(32))
    n.start("k1", key)
    out = n.init()
    assert len(out["recovery_keys_b64"]) == 3 and out["recovery_keys_threshold"] == 2
    n.stop()
    n.start("k1", key)
    st = n.wait_unsealed()
    assert st["sealed"] is False and st["type"] == "static"


def test_wrong_key_stays_sealed(nodes):
    n = nodes("n1")
    key = n.write_key("k1", os.urandom(32))
    n.start("k1", key)
    n.init()
    n.stop()
    wrong = n.dir / "wrong" / "k1.key"
    wrong.parent.mkdir()
    wrong.write_bytes(os.urandom(32))
    n.start("k1", wrong)
    time.sleep(3)
    if n.proc.poll() is None:
        assert n.status().get("sealed") is not False, n.log()
    else:
        assert n.proc.returncode != 0


def test_rotation_previous_key(nodes):
    n = nodes("n1")
    old = n.write_key("k1", os.urandom(32))
    n.start("k1", old)
    n.init()
    n.put_secret()
    n.stop()
    new = n.write_key("k2", os.urandom(32))
    n.start("k2", new, prev=("k1", old))
    st = n.wait_unsealed()
    assert st["type"] == "static"
    n.wait_leader()
    assert n.read_secret() == "42"


def test_snapshot_restore_needs_matching_key(nodes):
    a = nodes("a")
    raw = os.urandom(32)
    key_a = a.write_key("k1", raw)
    a.start("k1", key_a)
    a.init()
    a.put_secret()
    snap = a.dir / "openbao.snap"
    a.bao("operator", "raft", "snapshot", "save", str(snap))
    a.stop()

    b = nodes("b")
    key_b = b.write_key("k1", raw)
    b.start("k1", key_b)
    b.init()
    b.bao("operator", "raft", "snapshot", "restore", "-force", str(snap))
    b.token = a.token  # the restored data carries cluster A's tokens
    b.wait_unsealed()
    b.wait_leader()
    assert b.read_secret() == "42"


def test_deployed_config_boots(tmp_path):
    """The real values.yaml HCL (TLS, static seal, declarative audit) starts and auto-unseals.

    Only paths and ports are rewritten; service_registration needs a cluster and is dropped.
    """

    repo = Path(__file__).resolve().parents[3] / "deploy/enterprise/openbao"
    hcl = yaml.safe_load((repo / "values.yaml").read_text())["server"]["ha"]["raft"]["config"]
    tls = tmp_path / "tls"
    subprocess.run(["bash", str(repo / "gen-bootstrap-tls.sh"), str(tls)], check=True,
                   capture_output=True)
    seal, data = tmp_path / "seal", tmp_path / "data"
    seal.mkdir()
    data.mkdir()
    kid = re.search(r'current_key_id = "([^"]+)"', hcl).group(1)
    (seal / f"{kid}.key").write_bytes(os.urandom(32))
    port, cport = free_port(), free_port()
    hcl = (hcl.replace("/openbao/tls/", f"{tls}/").replace("/openbao/seal/", f"{seal}/")
           .replace('"/openbao/data"', f'"{data}"').replace("[::]:8200", f"127.0.0.1:{port}")
           .replace("[::]:8201", f"127.0.0.1:{cport}")
           .replace('service_registration "kubernetes" {}', ""))
    hcl += f'\napi_addr = "https://127.0.0.1:{port}"\ncluster_addr = "https://127.0.0.1:{cport}"\n'
    cfg = tmp_path / "config.hcl"
    cfg.write_text(hcl)
    env = {**os.environ, "BAO_ADDR": f"https://127.0.0.1:{port}", "BAO_CACERT": str(tls / "ca.crt"),
           "BAO_RAFT_NODE_ID": "openbao-0"}
    log = open(tmp_path / "server.log", "wb")
    proc = subprocess.Popen(["bao", "server", f"-config={cfg}"], stdout=log,
                            stderr=subprocess.STDOUT, env=env)
    try:
        def bao(*args):
            return subprocess.run(["bao", *args], env=env, capture_output=True, text=True,
                                  timeout=60)
        deadline = time.time() + 30
        while bao("status").returncode not in (0, 2):
            assert proc.poll() is None and time.time() < deadline, (
                (tmp_path / "server.log").read_text())
            time.sleep(0.3)
        out = json.loads(bao("operator", "init", "-recovery-shares=3", "-recovery-threshold=2",
                             "-format=json").stdout)
        env["BAO_TOKEN"] = out["root_token"]
        deadline = time.time() + 30
        while bao("audit", "list", "-format=json").returncode != 0:
            assert time.time() < deadline, (tmp_path / "server.log").read_text()
            time.sleep(0.5)
        st = json.loads(bao("status", "-format=json").stdout)
        assert st["sealed"] is False and st["type"] == "static"
        audit = json.loads(bao("audit", "list", "-format=json").stdout)
        assert audit["stdout/"]["type"] == "file"
        assert audit["stdout/"]["options"]["file_path"] == "stdout"
    finally:
        proc.terminate()
        proc.wait(timeout=30)
