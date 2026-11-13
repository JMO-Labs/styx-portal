"""Pure age-off planning: find stale files and decide notice/wait/move."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class Plan:
    action: str  # "none" | "notice" | "wait" | "move"
    files: list[str] = field(default_factory=list)


def stale_files(home: Path, now: datetime, days: int = 90) -> list[str]:
    """Relpaths of regular files with mtime and atime older than `days`."""
    cutoff = (now - timedelta(days=days)).replace(tzinfo=timezone.utc).timestamp()
    out: list[str] = []
    for dirpath, _dirs, names in os.walk(home):
        rel_dir = Path(dirpath).relative_to(home)
        in_cache = bool(rel_dir.parts) and rel_dir.parts[0] == ".cache"
        for name in names:
            if in_cache and name.startswith("."):
                continue
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_mtime < cutoff and st.st_atime < cutoff:
                out.append(str(rel_dir / name))
    return out


def plan(
    stale: list[str],
    notice_due_at: datetime | None,
    now: datetime,
    notice_days: int = 14,
    home: Path | None = None,
) -> Plan:
    """Decide the next step. `notice_due_at` is when the notice was issued
    (None if none). With `home`, files touched after the notice are dropped."""
    if not stale:
        return Plan("none")
    if notice_due_at is None:
        return Plan("notice", list(stale))
    if now - notice_due_at < timedelta(days=notice_days):
        return Plan("wait", list(stale))
    files = list(stale)
    if home is not None:
        sent = notice_due_at.replace(tzinfo=timezone.utc).timestamp()
        keep = []
        for rel in files:
            try:
                st = os.lstat(home / rel)
            except OSError:
                continue
            if st.st_mtime <= sent and st.st_atime <= sent:
                keep.append(rel)
        files = keep
    return Plan("move", files) if files else Plan("none")
