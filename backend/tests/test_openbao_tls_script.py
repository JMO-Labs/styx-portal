"""gen-bootstrap-tls.sh (issue #4): offline bootstrap CA and OpenBao server cert."""

import shutil
import stat
import subprocess

import pytest

from tests.openbao_checks import OPENBAO, ROOT

SCRIPT = OPENBAO / "gen-bootstrap-tls.sh"
pytestmark = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl missing")


def run(outdir):
    return subprocess.run(["bash", str(SCRIPT), str(outdir)], capture_output=True, text=True,
                          timeout=60)


def test_refuses_outdir_in_repo():
    out = ROOT / "deploy/enterprise/openbao/tls-out"
    res = run(out)
    assert res.returncode != 0
    assert not out.exists()


def test_refuses_missing_outdir_arg():
    res = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode != 0


def test_generates_ca_and_server_cert(tmp_path):
    out = tmp_path / "tls"
    res = run(out)
    assert res.returncode == 0, res.stderr
    for key in ("ca.key", "tls.key"):
        assert stat.S_IMODE((out / key).stat().st_mode) == 0o600, key
    v = subprocess.run(["openssl", "verify", "-CAfile", "ca.crt", "tls.crt"], cwd=out,
                       capture_output=True, text=True)
    assert v.returncode == 0, v.stderr
    text = subprocess.run(["openssl", "x509", "-in", "tls.crt", "-noout", "-text"], cwd=out,
                          capture_output=True, text=True, check=True).stdout
    for san in ("DNS:openbao-active.openbao.svc", "DNS:*.openbao-internal",
                "DNS:openbao.openbao.svc.cluster.local", "IP Address:127.0.0.1"):
        assert san in text, san
    ca = subprocess.run(["openssl", "x509", "-in", "ca.crt", "-noout", "-text"], cwd=out,
                        capture_output=True, text=True, check=True).stdout
    assert "secp384r1" in ca or "P-384" in ca
    assert "CA:TRUE" in ca
    assert "PRIVATE KEY" not in res.stdout + res.stderr
    for cmd in ("kubectl create secret generic openbao-tls -n openbao",
                "kubectl create secret generic openbao-ca -n external-secrets"):
        assert cmd in res.stdout, cmd
