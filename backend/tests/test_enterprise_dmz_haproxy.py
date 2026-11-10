"""Static checks for the DMZ HAProxy pair IaC (issue #7, ADR-0012, ADR-0050). No HAProxy needed."""

import re

import pytest

from tests.dmz_haproxy_checks import (
    ADR_0050, DEFAULTS, DMZ, DOCS_README, FILES, RUNBOOK, TASKS, TEMPLATES, directives,
    host_vars, load_yaml, render, section, strip_comments,
)

STRIPPED = ["Client-Cert", "Client-Cert-Chain", "X-Forwarded-For", "X-Forwarded-Proto",
            "X-Forwarded-Host", "Forwarded"]
TLS_VARS = ["dmz_tls_ciphers", "dmz_tls_ciphersuites", "dmz_tls_min_ver", "dmz_tls_curves"]
CURVES = re.compile(r"X25519|X448|P-256|P-384|P-521|prime256v1|secp\d+r1", re.I)


@pytest.fixture(scope="module")
def cfg() -> str:
    return render("haproxy.cfg.j2")


@pytest.fixture(scope="module")
def fe(cfg) -> str:
    return section(strip_comments(cfg), "frontend fe_https")


@pytest.fixture(scope="module")
def crt_list() -> dict[str, str]:
    """Rendered crt-list: SNI filter -> the whole line."""
    out = {}
    for ln in strip_comments(render("crt-list.j2")).splitlines():
        if ln.strip():
            for sni in ln.split("]", 1)[1].split():
                out[sni] = ln
    return out


def test_files_exist():
    missing = [str(p.relative_to(DMZ)) for p in FILES if not p.is_file()]
    assert not missing


def test_haproxy_version_pinned():
    ver = str(load_yaml(DEFAULTS)["dmz_haproxy_version"])
    m = re.match(r"^(\d+)\.(\d+)\.\d+$", ver)
    assert m, ver
    major, minor = int(m[1]), int(m[2])
    assert (major, minor) >= (3, 2) and minor % 2 == 0, f"{ver} is not an LTS"
    tasks = TASKS.read_text()
    assert "latest" not in tasks
    assert "dmz_haproxy_version" in tasks and "dmz_keepalived_version" in tasks


def test_tls_settings_are_variables(cfg):
    for name in ("haproxy.cfg.j2", "crt-list.j2"):
        src = (TEMPLATES / name).read_text()
        for bad in ("ECDHE", "AES", "CHACHA", "TLSv1."):
            assert bad not in src, f"{bad} literal in {name}"
        assert not CURVES.search(src), name
    v = host_vars()
    src = (TEMPLATES / "haproxy.cfg.j2").read_text()
    for var in TLS_VARS:
        assert var in src, var
        assert str(v[var]) in cfg, var
    crt = render("crt-list.j2")
    for var in ("dmz_piv_ca_file", "dmz_openbao_ca_file", "dmz_domain"):
        assert str(v[var]) in crt, var


def test_crt_list_verify_modes(crt_list):
    d = host_vars()["dmz_domain"]
    login, prov = crt_list[f"login.{d}"], crt_list[f"provision.{d}"]
    assert "verify optional" in login and "no-tls-tickets" in login
    assert f"ca-file {host_vars()['dmz_piv_ca_file']}" in login
    assert "verify required" in prov
    assert f"ca-file {host_vars()['dmz_openbao_ca_file']}" in prov
    for h in ("banner", "portal"):
        line = crt_list[f"{h}.{d}"]
        assert "verify none" in line and "ca-file" not in line, h


def test_no_ignore_err_or_crl():
    for path in TEMPLATES.iterdir():
        text = path.read_text()
        for bad in ("ca-ignore-err", "crt-ignore-err", "crl-file"):
            assert bad not in text, f"{bad} in {path.name}"


def test_strip_before_set(fe):
    rules = directives(fe, "http-request")
    dels = [i for i, r in enumerate(rules) if r.startswith("http-request del-header")]
    assert dels == list(range(len(STRIPPED))), "del-header must be the first http-request rules"
    deleted = {rules[i].split()[2] for i in dels}
    assert deleted == set(STRIPPED)
    first_set = next(i for i, r in enumerate(rules) if r.startswith("http-request set-header"))
    assert max(dels) < first_set


def test_cert_headers_only_on_verified_login(cfg, fe):
    flat = strip_comments(cfg)
    for header, fetch in (("Client-Cert", "ssl_c_der,base64"),
                          ("Client-Cert-Chain", "ssl_c_chain_der,base64")):
        lines = [ln.strip() for ln in flat.splitlines()
                 if re.search(rf"set-header {header}\s", ln)]
        assert len(lines) == 1, header
        line = lines[0]
        assert f"%[{fetch}]" in line
        cond = line.split(" if ", 1)[1]
        assert "is_login" in cond and "ssl_c_used" in cond and "ssl_c_verify 0" in cond
        assert " or " not in cond and "||" not in cond
        assert line in fe


def test_no_card_403(fe):
    rule = next(r for r in directives(fe, "http-request return") if "no-card.html" in r)
    assert "status 403" in rule
    cond = rule.split(" if ", 1)[1]
    assert "is_login" in cond and "!" in cond
    assert "ssl_c_used" in fe and "ssl_c_verify 0" in fe


def test_sni_host_mismatch_421(fe):
    assert "ssl_fc_sni" in fe and "strcmp" in fe and "lower" in fe
    assert re.search(r"req\.hdr\(host\),field\(1,:\),lower", fe), "Host must be lowercased, port stripped"
    deny = [r for r in directives(fe, "http-request deny") if "deny_status 421" in r]
    assert deny
    # 421 must fire before any header is set.
    rules = directives(fe, "http-request")
    assert rules.index(deny[0]) < next(i for i, r in enumerate(rules) if "set-header" in r)


def test_provision_source_allowlist(fe):
    v = host_vars()
    assert v["dmz_provision_allowed_cidrs"]
    for cidr in v["dmz_provision_allowed_cidrs"]:
        assert cidr in fe
    src = (TEMPLATES / "haproxy.cfg.j2").read_text()
    assert "dmz_provision_allowed_cidrs" in src
    assert any("is_provision" in r and "!" in r for r in directives(fe, "http-request deny"))


def test_rate_limits_and_peers(cfg, fe):
    v = host_vars()
    flat = strip_comments(cfg)
    peers = section(flat, "peers")
    for h, hv in v["hostvars"].items():
        assert re.search(rf"peer {h} {re.escape(hv['dmz_peer_addr'])}:\d+", peers), h
    tables = re.findall(r"stick-table .*", flat)
    assert len(tables) >= 2 and all("peers" in t and "http_req_rate" in t for t in tables)
    for host, var in (("is_login", "dmz_login_rate_limit"), ("is_provision", "dmz_provision_rate_limit")):
        assert any("track-sc" in r and host in r for r in directives(fe, "http-request"))
        assert any(host in r and f"gt {v[var]}" in r for r in directives(fe, "http-request deny"))
        assert var in (TEMPLATES / "haproxy.cfg.j2").read_text()


def test_backend_reencrypt_mtls(cfg):
    flat = strip_comments(cfg)
    v = host_vars()
    servers = [ln.strip() for ln in flat.splitlines() if ln.strip().startswith("server ")]
    assert servers
    for s in servers:
        assert " ssl " in f"{s} " and "verify required" in s, s
        assert f"ca-file {v['dmz_cluster_ca_file']}" in s and f"crt {v['dmz_haproxy_client_cert']}" in s
        assert "verify none" not in s
    assert "ssl-server-verify none" not in flat


def test_healthz_local_only(cfg):
    fe = section(strip_comments(cfg), "frontend fe_healthz")
    bind = directives(fe, "bind")[0]
    assert bind.split()[1].startswith(("127.", "[::1]")), bind
    assert "/healthz" in fe


def test_keepalived_unicast_and_check():
    src = (TEMPLATES / "keepalived.conf.j2").read_text()
    out = render("keepalived.conf.j2")
    hv = host_vars()
    assert "unicast_peer" in out and "mcast" not in out
    assert re.search(r"vrrp_script \S*haproxy", out) and "track_script" in out
    assert "{{ dmz_vip }}" in src and hv["dmz_vip"] in out
    assert re.search(r"auth_pass\s+\{\{\s*dmz_vrrp_auth_pass\s*\}\}", src)
    assert "{{ dmz_vrrp_priority }}" in src and "{{ dmz_vrrp_state }}" in src
    peer = next(h for h in hv["hostvars"] if h != hv["inventory_hostname"])
    assert hv["hostvars"][peer]["dmz_peer_addr"] in out
    assert f"unicast_src_ip {hv['dmz_peer_addr']}" in out


def test_tasks_validate_and_no_log():
    tasks = load_yaml(TASKS)
    tpl = [t for t in tasks if "haproxy.cfg" in str(t.get("ansible.builtin.template", {}).get("dest", ""))]
    assert len(tpl) == 1 and "haproxy -c -f %s" in tpl[0]["ansible.builtin.template"]["validate"]
    assert all("notify" in t for t in tasks if "ansible.builtin.template" in t)
    key_words = re.compile(r"key|cert|pki|pem|auth_pass|keepalived\.conf", re.I)
    for t in tasks:
        if key_words.search(str({k: v for k, v in t.items() if k != "name"})):
            assert t.get("no_log") is True, t["name"]
    assert any("systemd" in str(t) and "Protect" in str(t) for t in tasks), "hardening drop-in"
    handlers = load_yaml(TASKS.parent.parent / "handlers/main.yml")
    assert any("reloaded" in str(h) for h in handlers)


def test_no_secrets_committed():
    hits = [p for p in DMZ.rglob("*") if p.is_file()
            and re.search(r"BEGIN .*PRIVATE KEY", p.read_text(errors="ignore"))]
    assert not hits


def test_docs_and_adr_followup():
    assert RUNBOOK.is_file()
    assert "runbooks/dmz-haproxy.md" in DOCS_README.read_text()
    adr = ADR_0050.read_text()
    assert "- Status: Accepted" in adr
    for s in ("Client-Cert", "ssl_c_der", "runbooks/dmz-haproxy.md"):
        assert s in adr, s
    readme = (DMZ / "README.md").read_text()
    for s in ("--spi-x509cert-lookup--provider=haproxy", "--haproxy--ssl-client-cert=Client-Cert",
              "--haproxy--ssl-cert-chain=Client-Cert-Chain", "--haproxy--certificate-chain-length=",
              "--proxy-trusted-addresses=", "RequireAndVerifyClientCert", "trustedIPs", "Cilium", "R05"):
        assert s in readme, s


def test_files_under_500_lines():
    for p in [*DMZ.rglob("*"), RUNBOOK]:
        if p.is_file():
            assert len(p.read_text().splitlines()) < 500, p
