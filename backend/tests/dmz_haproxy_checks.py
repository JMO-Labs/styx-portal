"""Shared helpers for the DMZ HAProxy pair IaC (issue #7): paths and an Ansible-like render.

render() layers role defaults < group_vars/dmz.yml < inventory host vars < overrides, resolves
"{{ }}" inside string vars, then renders a role template with plain Jinja2 (no Ansible needed).
"""

import re
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[2]
DMZ = ROOT / "deploy/enterprise/dmz-haproxy"
ANSIBLE = DMZ / "ansible"
ROLE = ANSIBLE / "roles/dmz_haproxy"
TEMPLATES = ROLE / "templates"
DEFAULTS = ROLE / "defaults/main.yml"
GROUP_VARS = ANSIBLE / "group_vars/dmz.yml"
INVENTORY = ANSIBLE / "inventory.example.yml"
TASKS = ROLE / "tasks/main.yml"
RUNBOOK = ROOT / "docs/enterprise/runbooks/dmz-haproxy.md"
DOCS_README = ROOT / "docs/enterprise/README.md"
ADR_0050 = next((ROOT / "docs/enterprise/adr").glob("0050-*.md"))

FILES = [
    DMZ / "README.md", DMZ / ".ansible-lint", ANSIBLE / "site.yml", INVENTORY, GROUP_VARS,
    TASKS, ROLE / "handlers/main.yml", DEFAULTS, TEMPLATES / "haproxy.cfg.j2",
    TEMPLATES / "crt-list.j2", TEMPLATES / "keepalived.conf.j2", ROLE / "files/errors/no-card.html",
]
# Test-only stand-in for the vault-encrypted VRRP secret (group_vars points at vault_*).
TEST_VAULT = {"vault_dmz_vrrp_auth_pass": "t3stpass"}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def dmz_hosts() -> dict[str, dict]:
    return load_yaml(INVENTORY)["all"]["children"]["dmz"]["hosts"]


def _resolve(env: jinja2.Environment, vars_: dict) -> dict:
    out = dict(vars_)
    for _ in range(5):  # nested "{{ a }}" -> "{{ b }}" chains are short
        out = {k: env.from_string(v).render(out) if isinstance(v, str) and "{{" in v else v
               for k, v in out.items()}
    return out


def host_vars(host: str | None = None, overrides: dict | None = None,
              hosts: dict[str, dict] | None = None) -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    inv = dmz_hosts()
    host = host or next(iter(inv))
    base = {**load_yaml(DEFAULTS), **load_yaml(GROUP_VARS), **TEST_VAULT, **(overrides or {})}
    hostvars = {}
    for name, hv in inv.items():
        merged = {**base, **(hv or {}), **(overrides or {}), **((hosts or {}).get(name) or {})}
        hostvars[name] = _resolve(env, {**merged, "inventory_hostname": name})
    return {**hostvars[host], "hostvars": hostvars, "groups": {"dmz": list(inv)}}


def render(template: str, overrides: dict | None = None, host: str | None = None,
           hosts: dict[str, dict] | None = None) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES),
                             undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    return env.get_template(template).render(host_vars(host, overrides, hosts))


def section(cfg: str, header: str) -> str:
    """Body of one haproxy.cfg section, e.g. section(cfg, "frontend fe_https")."""
    m = re.search(rf"^{re.escape(header)}\b.*?(?=^\S|\Z)", cfg, re.M | re.S)
    assert m, f"{header} missing"
    return m.group(0)


def directives(body: str, keyword: str) -> list[str]:
    return [ln.strip() for ln in body.splitlines() if ln.strip().startswith(keyword)]


def strip_comments(text: str) -> str:
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
