"""The enterprise-base image must ship every agent module gateway.py imports."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
DOCKERFILE = ROOT / "images" / "enterprise-base" / "Dockerfile"
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", re.MULTILINE)


def _local_imports(module: str, seen: set[str]) -> set[str]:
    if module in seen or not (AGENT / f"{module}.py").is_file():
        return seen
    seen.add(module)
    for name in IMPORT_RE.findall((AGENT / f"{module}.py").read_text()):
        _local_imports(name, seen)
    return seen


def _copied_modules() -> set[str]:
    text = DOCKERFILE.read_text().replace("\\\n", " ")
    return set(re.findall(r"agent/(\w+)\.py", text))


def test_dockerfile_copies_all_gateway_imports():
    missing = _local_imports("gateway", set()) - _copied_modules()
    assert not missing, f"enterprise-base Dockerfile misses: {sorted(missing)}"
