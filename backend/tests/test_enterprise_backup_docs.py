import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs/operate/backup-schedules.md"


def _nav_values(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _nav_values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nav_values(v)


def test_backup_schedules_page_exists_and_in_nav():
    assert PAGE.is_file()
    cfg = tomllib.loads((ROOT / "zensical.toml").read_text())
    nav = cfg.get("project", cfg)["nav"]
    assert "operate/backup-schedules.md" in _nav_values(nav)


def test_backup_schedules_page_content():
    t = PAGE.read_text()
    assert "93600" in t and "26 h" in t
    assert "04:30" in t
    for s in ("01:00", "02:00", "03:00", "Object Lock", "cephx"):
        assert s in t


def test_backup_readme_exists():
    assert "04:30" in (ROOT / "deploy/enterprise/backup/README.md").read_text()


def test_control_matrix_cp9_and_adr():
    cm = (ROOT / "docs/enterprise/control-matrix.md").read_text()
    row = next(ln for ln in cm.splitlines() if ln.startswith("| CP-9 "))
    assert "Planned (IaC done, not run)" in row and "deploy/enterprise/backup" in row
    adr = next((ROOT / "docs/enterprise/adr").glob("0037-*.md")).read_text()
    assert "SC-28" in adr.split("## Consequences")[1]
