#!/usr/bin/env python3
"""Component and license register for the enterprise build (issue #17).

Merges Trivy CycloneDX license SBOMs with the hand-kept docs/enterprise/components.yaml,
writes docs/enterprise/component-register.{md,json} and enforces license-policy.yaml.

  license_register.py generate --sbom repo.cdx.json venv.cdx.json
  license_register.py check    --sbom repo.cdx.json venv.cdx.json

Exit codes: 0 clean, 1 policy problems or stale register, 2 malformed input.
Only name, version, purl and licenses are read from CycloneDX (output varies by Trivy version).
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "enterprise"
SCOPES = {"enterprise", "build-only", "service", "homelab", "external"}
COSTS = {"free", "paid"}
COMPONENT_KEYS = {"ecosystem", "name", "version", "license", "source_url", "cost", "scope",
                  "adr", "note"}
COMPONENT_REQUIRED = COMPONENT_KEYS - {"adr", "note"}
OVERRIDE_KEYS = {"name", "version", "license", "source_url", "note"}
POLICY_KEYS = {"allow", "service_only", "deny", "proprietary", "accepted_adrs", "aliases"}
REGEN = ("backend/.venv/bin/python scripts/license_register.py generate "
         "--sbom repo.cdx.json venv.cdx.json")


class InputError(Exception):
    """Malformed input file: reported without a traceback, exit 2."""


# ---- loading -------------------------------------------------------------------------------
def _yaml(path):
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as e:
        raise InputError(f"{path}: {e}") from None
    if not isinstance(data, dict):
        raise InputError(f"{path}: expected a mapping at the top level")
    return data


def _keys(path, where, data, allowed, required=()):
    if not isinstance(data, dict):
        raise InputError(f"{path}: {where}: expected a mapping")
    if extra := set(data) - set(allowed):
        raise InputError(f"{path}: {where}: unknown key(s) {', '.join(sorted(extra))}")
    if missing := set(required) - set(data):
        raise InputError(f"{path}: {where}: missing key(s) {', '.join(sorted(missing))}")


def load_policy(path):
    data = _yaml(path)
    _keys(path, "policy", data, POLICY_KEYS, POLICY_KEYS - {"aliases"})
    data.setdefault("aliases", {})
    for key in POLICY_KEYS - {"aliases"}:
        if not isinstance(data[key], list) or not all(isinstance(x, str) for x in data[key]):
            raise InputError(f"{path}: {key}: expected a list of strings")
    if not isinstance(data["aliases"], dict):
        raise InputError(f"{path}: aliases: expected a mapping")
    data["accepted_adrs"] = {norm_adr(a) for a in data["accepted_adrs"]}
    return data


def _name(item):
    return item.get("name") if isinstance(item, dict) else repr(item)


def load_components(path):
    data = _yaml(path)
    _keys(path, "components.yaml", data, {"first_party", "components", "overrides"})
    data = {"first_party": data.get("first_party") or [],
            "components": data.get("components") or [],
            "overrides": data.get("overrides") or []}
    for key, val in data.items():
        if not isinstance(val, list):
            raise InputError(f"{path}: {key}: expected a list")
    for c in data["components"]:
        _keys(path, f"component {_name(c)}", c, COMPONENT_KEYS, COMPONENT_REQUIRED)
        c["version"] = str(c["version"])
        if c["scope"] not in SCOPES:
            raise InputError(f"{path}: component {c['name']}: bad scope {c['scope']!r}")
        if c["cost"] not in COSTS:
            raise InputError(f"{path}: component {c['name']}: bad cost {c['cost']!r}")
    for o in data["overrides"]:
        _keys(path, f"override {_name(o)}", o, OVERRIDE_KEYS, {"name", "version", "license"})
        o["version"] = str(o["version"])
    return data


def load_sbom(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise InputError(f"{path}: not a readable CycloneDX JSON file: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("components"), list):
        raise InputError(f"{path}: CycloneDX file has no 'components' list")
    for c in data["components"]:
        lics = c.get("licenses") or [] if isinstance(c, dict) else None
        if not isinstance(lics, list) or not all(
                isinstance(x, dict) and isinstance(x.get("license") or {}, dict) for x in lics):
            raise InputError(f"{path}: malformed CycloneDX component {c!r}")
    return data["components"]


# ---- SPDX ----------------------------------------------------------------------------------
def normalize(lic):
    """GPL-2.0-only / GPL-2.0-or-later / GPL-2.0+ -> GPL-2.0."""
    return re.sub(r"(-only|-or-later|\+)$", "", lic.strip())


def norm_adr(adr):
    """D37 / ADR-37 / ADR-0037 -> ADR-0037."""
    m = re.fullmatch(r"(?:ADR-?|D)(\d+)", str(adr).strip(), re.I)
    return f"ADR-{int(m.group(1)):04d}" if m else str(adr).strip()


def parse(expr):
    """SPDX expression -> nested ('OR'|'AND', [..]) tuples with license-id strings as leaves.

    `lic WITH exception` becomes ('WITH', [lic, exception]).
    """
    tokens = re.findall(r"\(|\)|[^\s()]+", expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def atom():
        if peek() is None or peek() in (")", "AND", "OR", "WITH"):
            raise ValueError(f"bad SPDX expression {expr!r}")
        if take() == "(":
            node = binary("OR")
            if peek() != ")":
                raise ValueError(f"unbalanced parentheses in {expr!r}")
            take()
            return node
        lic = tokens[pos - 1]
        if peek() == "WITH":
            take()
            if peek() in (None, "(", ")", "AND", "OR", "WITH"):
                raise ValueError(f"bad SPDX expression {expr!r}")
            return ("WITH", [lic, take()])
        return lic

    def binary(op):
        sub = (lambda: binary("AND")) if op == "OR" else atom
        parts = [sub()]
        while peek() is not None and peek().upper() == op:
            take()
            parts.append(sub())
        return parts[0] if len(parts) == 1 else (op, parts)

    node = binary("OR")
    if pos != len(tokens):
        raise ValueError(f"bad SPDX expression {expr!r}")
    return node


def leaf_problem(lic, comp, policy):
    """None if the single license is fine for this component, else the reason."""
    lic = normalize(policy["aliases"].get(lic, lic))
    if lic in {normalize(a) for a in policy["allow"]}:
        return None
    if lic in {normalize(a) for a in policy["service_only"]}:
        return None if comp["scope"] == "service" else f"{lic} is only allowed with scope: service"
    if any(fnmatch.fnmatch(lic, p) for p in policy["proprietary"]):
        if norm_adr(comp.get("adr", "")) in policy["accepted_adrs"]:
            return None
        return f"proprietary license {lic} without an ADR exception"
    if any(fnmatch.fnmatch(lic, normalize(p)) for p in policy["deny"]):
        return f"denied license {lic}"
    return f"unknown license {lic} (add an override)"


def expr_problem(node, comp, policy):
    if isinstance(node, str):
        return leaf_problem(node, comp, policy)
    op, parts = node
    if op == "WITH":  # the base license decides, unless the exception itself is denied
        lic, exc = parts
        if any(fnmatch.fnmatch(exc, p) for p in policy["deny"]):
            return f"denied license {exc}"
        return leaf_problem(lic, comp, policy)
    problems = [expr_problem(p, comp, policy) for p in parts]
    if op == "OR":
        return None if None in problems else " and ".join(problems)
    return next((p for p in problems if p), None)


# ---- merge ---------------------------------------------------------------------------------
def _license_text(c):
    out = set()
    for entry in c.get("licenses") or []:
        if entry.get("expression"):
            out.add(entry["expression"].strip())
        elif lic := (entry.get("license") or {}):
            text = (lic.get("id") or lic.get("name") or "").strip()
            if text:
                out.add(text if " " not in text else f"LicenseRef-{text.replace(' ', '-')}")
    return out


def npm_name(purl, fallback):
    """Scoped npm identity from the purl; the CycloneDX `name` drops the @scope."""
    path = unquote(purl[len("pkg:npm/"):].split("?", 1)[0].split("#", 1)[0])
    return path.rpartition("@")[0] or path or fallback


HOMELAB_DIRS = ("e2e/", "scripts/diagrams/")


def lockfile_origins(path):
    """bom-ref -> lockfile paths, from Trivy's application components and dependencies."""
    data = json.loads(Path(path).read_text())
    apps = {c.get("bom-ref"): c.get("name") or "" for c in data["components"]
            if c.get("type") == "application" and c.get("bom-ref")}
    out = {}
    for d in data.get("dependencies") or []:
        if isinstance(d, dict) and d.get("ref") in apps:
            for ref in d.get("dependsOn") or []:
                out.setdefault(ref, set()).add(apps[d["ref"]])
    return out


def _homelab(origins):
    """True when every known lockfile origin is an e2e or diagrams one."""
    return bool(origins) and all(o.startswith(HOMELAB_DIRS) for o in origins)


def build(sbom_paths, manifest):
    """Merged, sorted register entries."""
    first_party = set(manifest["first_party"])
    found, origins = {}, {}
    for path in sbom_paths:
        by_ref = lockfile_origins(path)
        for c in load_sbom(path):
            purl = c.get("purl") or ""
            if c.get("type") != "library" or not purl.startswith("pkg:"):
                continue
            eco = purl[4:].split("/", 1)[0]
            name = c.get("name") or ""
            if eco == "npm":
                name = npm_name(purl, name)
            if eco == "pypi":  # PEP 503: dist-info and lockfile spell names differently
                name = re.sub(r"[-_.]+", "-", name).lower()
            if not name or name in first_party:
                continue
            key = (eco, name, str(c.get("version") or ""))
            found.setdefault(key, set()).update(_license_text(c))
            origins.setdefault(key, set()).update(by_ref.get(c.get("bom-ref"), {""}))
    overrides = {(o["name"].lower(), o["version"]): o for o in manifest["overrides"]}
    entries = []
    for (eco, name, version), lics in found.items():
        e = {"ecosystem": eco, "name": name, "version": version,
             "license": " AND ".join(f"({x})" if " " in x and len(lics) > 1 else x
                                     for x in sorted(lics)),
             "source_url": f"pkg:{eco}/{name}@{version}", "cost": "free",
             "scope": "enterprise", "origin": "sbom"}
        if eco == "npm" and _homelab(origins[(eco, name, version)]):
            e["scope"] = "homelab"
        if o := overrides.get((name.lower(), version)):
            e.update(license=o["license"], source_url=o.get("source_url", ""), origin="override")
        entries.append(e)
    for c in manifest["components"]:
        e = {k: c[k] for k in sorted(COMPONENT_REQUIRED)}
        if c.get("adr"):
            e["adr"] = norm_adr(c["adr"])
        entries.append({**e, "origin": "manifest"})
    return sorted(entries, key=lambda e: (e["ecosystem"], e["name"], e["version"]))


# ---- policy --------------------------------------------------------------------------------
def problems_for(e, policy):
    out = []
    if e["origin"] == "override" and not e["source_url"]:
        out.append("override has no source_url")
    if not e["license"]:
        out.append("unknown license (no license data, add an override)")
    else:
        try:
            if p := expr_problem(parse(e["license"]), e, policy):
                out.append(p)
        except ValueError as err:
            out.append(str(err))
    if e["cost"] == "paid":
        if not e.get("adr"):
            out.append("cost: paid without an adr")
        elif e["adr"] not in policy["accepted_adrs"]:
            out.append(f"cost: paid with {e['adr']}, which is not an accepted ADR")
    return out


def unused_overrides(entries, manifest):
    used = {(e["name"].lower(), e["version"]) for e in entries if e["origin"] == "override"}
    return [f"unused override {o['name']}@{o['version']}" for o in manifest["overrides"]
            if (o["name"].lower(), o["version"]) not in used]


def check(entries, policy):
    """(errors, warnings) as printable lines."""
    errors, warnings = [], []
    for e in entries:
        if e["scope"] == "external":
            continue
        label = f"{e['ecosystem']} {e['name']}@{e['version']}"
        sink = warnings if e["scope"] == "homelab" else errors
        sink += [f"{label} [{e['scope']}]: {p}" for p in problems_for(e, policy)]
    return errors, warnings


# ---- output --------------------------------------------------------------------------------
MD_HEAD = f"""# Component and license register

Generated by `scripts/license_register.py`; do not edit by hand. Policy:
[license-policy.yaml](license-policy.yaml). Curated items and overrides:
[components.yaml](components.yaml). Per-image OS-package SBOMs stay with ADR-0029 phase 3.

## How to update the register

1. Build the backend venv from `backend/uv.lock` (see the `license-register` CI job).
2. Scan with the pinned Trivy (version and sha256 in the CI job): `scripts/license_scan.sh`.
   It writes `repo.cdx.json` (repo lockfiles) and `venv.cdx.json` (installed backend venv).
3. Regenerate: `{REGEN}`, then commit both register files.
4. Unknown or wrong license: add an `overrides:` entry to `components.yaml`
   (`name`, `version`, SPDX `license`, `source_url` of the license text; PyPI names in
   PEP 503 form, e.g. `typing-extensions`). New image, chart or apt app: add a
   `components:` entry with `cost`, `scope` and, when `cost: paid`, an accepted `adr`.

`check` fails on denied or unknown licenses, paid items without an accepted ADR, AGPL-3.0
outside `scope: service`, proprietary licenses without an ADR exception and a stale register.
`homelab` items only warn; `external` items are listed but not checked.

"""
COLUMNS = ["ecosystem", "name", "version", "license", "scope", "cost", "adr", "source_url"]


def _cell(v):
    return str(v).replace("|", "\\|")


def render(entries):
    lines = [f"| {' | '.join(c.replace('_', ' ').capitalize() for c in COLUMNS)} |",
             "|" + "---|" * len(COLUMNS)]
    lines += [f"| {' | '.join(_cell(e.get(c, '')) for c in COLUMNS)} |" for e in entries]
    md = MD_HEAD + f"{len(entries)} components.\n\n" + "\n".join(lines) + "\n"
    rows = ",\n  ".join(json.dumps(e, sort_keys=True) for e in entries)  # one line per entry
    js = '{"components": [\n  ' + rows + "\n]}\n"
    return {"component-register.md": md, "component-register.json": js}


# ---- CLI -----------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("command", choices=["generate", "check"])
    ap.add_argument("--sbom", nargs="+", required=True, help="Trivy CycloneDX JSON file(s)")
    ap.add_argument("--components", default=DOCS / "components.yaml")
    ap.add_argument("--policy", default=DOCS / "license-policy.yaml")
    ap.add_argument("--out-dir", default=DOCS, type=Path)
    a = ap.parse_args(argv)
    try:
        policy = load_policy(a.policy)
        manifest = load_components(a.components)
        entries = build(a.sbom, manifest)
        files = render(entries)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.command == "generate":
        a.out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (a.out_dir / name).write_text(text)
        return 0
    errors, warnings = check(json.loads(files["component-register.json"])["components"], policy)
    for name, text in files.items():
        path = a.out_dir / name
        if not path.is_file() or path.read_text() != text:
            errors.append(f"stale register: {path} differs from a fresh generate; run {REGEN}")
    warnings += unused_overrides(entries, manifest)
    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"license-register: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
