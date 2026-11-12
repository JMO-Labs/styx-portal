#!/usr/bin/env python3
"""Fail if a patch in patches/selkies/series lacks a complete upstream note."""
import re
import sys
from pathlib import Path

FIELDS = ("Upstream project", "Offered", "Status", "Reason kept locally")
STATUSES = {"offered", "merged", "rejected", "local-only"}


def _field(text: str, name: str) -> str | None:
    m = re.search(rf"^\s*[-*]?\s*\**{re.escape(name)}\**\s*:\s*\**\s*(.*)$", text, re.M)
    return m.group(1).strip(" *") if m else None


def check(root: Path) -> list[str]:
    root = Path(root)
    series = root / "patches/selkies/series"
    if not series.is_file():
        return [f"missing {series}"]
    errs: list[str] = []
    for line in series.read_text().splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        if not (root / "patches/selkies" / name).is_file():
            errs.append(f"{name}: missing patch file")
        stem = name.removesuffix(".patch")
        note = root / "docs/upstream" / f"{stem}.md"
        if not note.is_file():
            errs.append(f"{stem}: missing note docs/upstream/{stem}.md")
            continue
        text = note.read_text()
        for f in FIELDS:
            v = _field(text, f)
            if not v:
                errs.append(f"{stem}: missing or empty field '{f}'")
            elif f == "Status" and v not in STATUSES:
                errs.append(f"{stem}: Status '{v}' not in {sorted(STATUSES)}")
    return errs


if __name__ == "__main__":
    errors = check(Path(__file__).resolve().parents[1])
    print("\n".join(errors) or "patch notes ok")
    sys.exit(1 if errors else 0)
