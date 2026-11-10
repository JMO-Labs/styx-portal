"""Tests for scripts/license_register.py (issue #17). Never calls Trivy."""

import importlib.util
import json
import shutil
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures" / "license_register"
_spec = importlib.util.spec_from_file_location(
    "license_register", ROOT / "scripts" / "license_register.py"
)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def lib(name, version, lic=None, eco="npm", expr=None):
    c = {"type": "library", "name": name, "version": version,
         "purl": f"pkg:{eco}/{name}@{version}"}
    if lic:
        c["licenses"] = [{"license": {"id": lic}}]
    if expr:
        c["licenses"] = [{"expression": expr}]
    return c


def sbom(tmp, comps, name="s.cdx.json", serial="urn:uuid:1", ts="2026-01-01T00:00:00Z"):
    p = tmp / name
    p.write_text(json.dumps({"bomFormat": "CycloneDX", "serialNumber": serial,
                             "metadata": {"timestamp": ts}, "components": comps}))
    return p


def manifest(tmp, components=(), overrides=(), **extra):
    p = tmp / "components.yaml"
    p.write_text(yaml.safe_dump({"components": list(components),
                                 "overrides": list(overrides), **extra}))
    return p


def item(name="thing", lic="MIT", cost="free", scope="enterprise", **kw):
    return {"ecosystem": "image", "name": name, "version": "1.0", "license": lic,
            "source_url": "https://example.org", "cost": cost, "scope": scope, **kw}


def args(tmp, sboms, comps, cmd):
    return [cmd, "--sbom", *map(str, sboms), "--components", str(comps),
            "--policy", str(FIX / "license-policy.yaml"), "--out-dir", str(tmp / "out")]


def run(tmp, capsys, comps=(), components=(), overrides=()):
    """Generate a fresh register, then check it. Returns (exit code, output)."""
    s = sbom(tmp, list(comps))
    m = manifest(tmp, components, overrides)
    assert lr.main(args(tmp, [s], m, "generate")) == 0
    capsys.readouterr()
    code = lr.main(args(tmp, [s], m, "check"))
    return code, capsys.readouterr().out


def test_allowed_license_passes(tmp_path, capsys):
    code, out = run(tmp_path, capsys, [lib("left-pad", "1.3.0", "MIT")])
    assert code == 0, out
    assert "ERROR" not in out


def test_denied_license_fails(tmp_path, capsys):
    code, out = run(tmp_path, capsys, [lib("mongo-thing", "2.0.0", "SSPL-1.0")])
    assert code == 1
    line = next(ln for ln in out.splitlines() if "mongo-thing" in ln)
    assert line.startswith("ERROR") and "SSPL-1.0" in line


def test_unknown_license_fails_without_override(tmp_path, capsys):
    code, out = run(tmp_path, capsys, [lib("fuzzy", "0.1.3")])
    assert code == 1
    assert "fuzzy" in out and "unknown license" in out


def test_override_resolves_unknown(tmp_path, capsys):
    ov = {"name": "fuzzy", "version": "0.1.3", "license": "MIT",
          "source_url": "https://github.com/mattyork/fuzzy/blob/master/LICENSE-MIT"}
    code, out = run(tmp_path, capsys, [lib("fuzzy", "0.1.3")], overrides=[ov])
    assert code == 0, out

    del ov["source_url"]
    code, out = run(tmp_path, capsys, [lib("fuzzy", "0.1.3")], overrides=[ov])
    assert code != 0
    assert "source_url" in out


@pytest.mark.parametrize("expr,ok", [("MIT OR SSPL-1.0", True),
                                     ("SSPL-1.0 OR Elastic-2.0", False)])
def test_or_expression_passes_if_any_branch_allowed(tmp_path, capsys, expr, ok):
    code, out = run(tmp_path, capsys, [lib("x", "1.0.0", expr=expr)])
    assert (code == 0) is ok, out


@pytest.mark.parametrize("expr,ok", [("MIT AND SSPL-1.0", False),
                                     ("MIT AND Apache-2.0", True)])
def test_and_expression_fails_if_any_part_denied(tmp_path, capsys, expr, ok):
    code, out = run(tmp_path, capsys, [lib("x", "1.0.0", expr=expr)])
    assert (code == 0) is ok, out


@pytest.mark.parametrize("expr", ["(MIT OR Apache-2.0) AND BSD-3-Clause",
                                  "GPL-2.0-only WITH Classpath-exception-2.0",
                                  "GPL-2.0-or-later"])
def test_spdx_parsing_parentheses_and_with(tmp_path, capsys, expr):
    code, out = run(tmp_path, capsys, [lib("x", "1.0.0", expr=expr)])
    assert code == 0, out
    assert lr.normalize("GPL-2.0-only") == "GPL-2.0"


def test_paid_without_adr_fails(tmp_path, capsys):
    code, out = run(tmp_path, capsys, components=[item(cost="paid")])
    assert code == 1
    assert "thing" in out and "adr" in out.lower()


def test_paid_with_unaccepted_adr_fails(tmp_path, capsys):
    code, out = run(tmp_path, capsys, components=[item(cost="paid", adr="ADR-0007")])
    assert code == 1
    assert "ADR-0007" in out


@pytest.mark.parametrize("adr", ["ADR-0037", "D37"])
def test_paid_with_accepted_adr_passes(tmp_path, capsys, adr):
    code, out = run(tmp_path, capsys, components=[item(cost="paid", adr=adr)])
    assert code == 0, out


def test_agpl_only_allowed_for_service_scope(tmp_path, capsys):
    code, out = run(tmp_path, capsys, components=[item("grafana", "AGPL-3.0-only",
                                                       scope="service")])
    assert code == 0, out
    code, out = run(tmp_path, capsys, [lib("agpl-lib", "1.0.0", "AGPL-3.0")])
    assert code == 1
    assert "agpl-lib" in out and "service" in out
    code, out = run(tmp_path, capsys, [lib("agpl-py", "1.0.0", "AGPL-3.0", eco="pypi")])
    assert code == 1


def test_proprietary_in_enterprise_scope_fails(tmp_path, capsys):
    code, out = run(tmp_path, capsys, components=[item("chrome", "LicenseRef-proprietary")])
    assert code == 1
    assert "chrome" in out and "proprietary" in out
    code, out = run(tmp_path, capsys, components=[item("chrome", "LicenseRef-proprietary",
                                                       scope="homelab")])
    assert code == 0, out
    assert any(ln.startswith("WARN:") and "chrome" in ln for ln in out.splitlines())
    code, out = run(tmp_path, capsys, components=[
        item("chrome", "LicenseRef-proprietary", adr="ADR-0041")])
    assert code == 0, out


def test_external_scope_not_gated(tmp_path, capsys):
    code, out = run(tmp_path, capsys, components=[item("elastic", "Elastic-2.0",
                                                       scope="external")])
    assert code == 0, out
    assert "elastic" in (tmp_path / "out" / "component-register.md").read_text()


def test_generate_is_deterministic(tmp_path):
    comps = [lib("zeta", "1.0.0", "MIT"), lib("alpha", "2.0.0", "MIT"),
             lib("PyYAML", "6.0.3", "MIT", eco="pypi")]
    m = manifest(tmp_path, [item()])
    outs = []
    for i, (serial, ts) in enumerate([("urn:uuid:1", "2026-01-01T00:00:00Z"),
                                      ("urn:uuid:2", "2026-02-02T00:00:00Z")]):
        s = sbom(tmp_path, comps if i == 0 else comps[::-1], serial=serial, ts=ts)
        assert lr.main(args(tmp_path, [s], m, "generate")) == 0
        out = tmp_path / "out"
        outs.append(((out / "component-register.md").read_bytes(),
                     (out / "component-register.json").read_bytes()))
    assert outs[0] == outs[1]
    md, js = outs[0]
    assert b"2026-0" not in md + js and b"urn:uuid" not in md + js
    entries = json.loads(js)["components"]
    keys = [(e["ecosystem"], e["name"], e["version"]) for e in entries]
    assert keys == sorted(keys)
    assert ("pypi", "pyyaml", "6.0.3") in keys  # PEP 503 name normalisation


def test_stale_register_fails(tmp_path, capsys):
    m = manifest(tmp_path)
    old = sbom(tmp_path, [lib("a", "1.0.0", "MIT")], name="old.json")
    new = sbom(tmp_path, [lib("a", "1.0.0", "MIT"), lib("b", "1.0.0", "MIT")])
    assert lr.main(args(tmp_path, [old], m, "generate")) == 0
    capsys.readouterr()
    assert lr.main(args(tmp_path, [new], m, "check")) == 1
    assert "stale" in capsys.readouterr().out


def test_duplicate_component_versions_listed_separately(tmp_path):
    s1 = sbom(tmp_path, [lib("ms", "2.0.0", "MIT"), lib("ms", "2.1.3", "MIT")], name="1.json")
    s2 = sbom(tmp_path, [lib("ms", "2.1.3", "MIT")], name="2.json")
    assert lr.main(args(tmp_path, [s1, s2], manifest(tmp_path), "generate")) == 0
    md = (tmp_path / "out" / "component-register.md").read_text()
    rows = [ln for ln in md.splitlines() if ln.startswith("| npm | ms |")]
    assert len(rows) == 2


@pytest.mark.parametrize("case", ["empty", "no_components", "bad_key", "bad_json"])
def test_malformed_inputs(tmp_path, capsys, case):
    s = sbom(tmp_path, [lib("a", "1.0.0", "MIT")])
    m = manifest(tmp_path)
    if case == "empty":
        s.write_text("")
    elif case == "bad_json":
        s.write_text("{nope")
    elif case == "no_components":
        s.write_text(json.dumps({"bomFormat": "CycloneDX"}))
    else:
        m = manifest(tmp_path, [item(colour="blue")])
    assert lr.main(args(tmp_path, [s], m, "check")) == 2
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert (out.out + out.err).strip()


def test_repo_policy_files_valid():
    policy = lr.load_policy(ROOT / "docs" / "enterprise" / "license-policy.yaml")
    manifest_ = lr.load_components(ROOT / "docs" / "enterprise" / "components.yaml")
    accepted = set(policy["accepted_adrs"])
    for c in manifest_["components"]:
        if c["cost"] == "paid":
            assert lr.norm_adr(c.get("adr", "")) in accepted, c["name"]
    names = {(c["ecosystem"], c["name"], c["version"]) for c in manifest_["components"]}
    charts = sorted((ROOT / "deploy" / "enterprise").glob("*/charts/*.tgz"))
    assert charts
    for tgz in charts:
        with tarfile.open(tgz) as t:
            meta = next(m for m in t.getmembers() if m.name.endswith("/Chart.yaml"))
            chart = yaml.safe_load(t.extractfile(meta))
        assert ("helm", chart["name"], chart["version"]) in names, tgz.name
    overridden = {o["name"] for o in manifest_["overrides"]}
    assert {"qrcode-terminal", "fuzzy", "khroma"} <= overridden


def test_fixture_files_load(tmp_path, capsys):
    shutil.copy(FIX / "sbom-basic.cdx.json", tmp_path / "b.json")
    a = ["--sbom", str(tmp_path / "b.json"), "--components", str(FIX / "components.yaml"),
         "--policy", str(FIX / "license-policy.yaml"), "--out-dir", str(tmp_path / "out")]
    assert lr.main(["generate", *a]) == 0
    assert lr.main(["check", *a]) == 0, capsys.readouterr().out
    md = (tmp_path / "out" / "component-register.md").read_text()
    assert "styx-portal-backend" not in md  # first-party packages are not listed
    assert "| helm | openbao |" in md
