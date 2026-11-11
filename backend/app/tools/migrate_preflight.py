"""Read-only source scan: lists data PostgreSQL would reject (never writes).

Findings: orphan FK rows, NULL in NOT NULL, booleans not 0/1, NUL in text,
unparseable datetimes, undecodable JSON. Orphans can be skipped with
drop_orphans (transitively: children of a skipped row become orphans too);
every other finding always blocks.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers tables on SQLModel.metadata)


@dataclass(frozen=True)
class Finding:
    kind: str  # orphan | null | boolean | nul | datetime | json
    table: str
    pk: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind} {self.table} pk={self.pk}: {self.detail}"


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    skipped: dict[str, set[tuple]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.kind != "orphan"]


def _impl(col: sa.Column):
    return getattr(col.type, "impl", col.type)


def _bad_value(col: sa.Column, v) -> tuple[str, str] | None:
    """Return (kind, detail) if v is not acceptable for col in PostgreSQL."""
    if v is None:
        return ("null", f"{col.name} is NULL but NOT NULL") if not col.nullable else None
    t = _impl(col)
    if isinstance(t, sa.Boolean):
        if v not in (0, 1) or isinstance(v, str):
            return "boolean", f"{col.name}={v!r} is not 0/1"
    elif isinstance(t, sa.DateTime):
        try:
            datetime.fromisoformat(str(v))
        except ValueError:
            return "datetime", f"{col.name}={v!r} does not parse"
    elif isinstance(t, sa.JSON):
        try:
            json.loads(v) if isinstance(v, (str, bytes)) else None
        except ValueError:
            return "json", f"{col.name} is not valid JSON"
    if isinstance(t, sa.String) and isinstance(v, str) and "\x00" in v:
        return "nul", f"{col.name} contains a NUL byte"
    return None


def _pk_cols(table: sa.Table) -> list[str]:
    return [c.name for c in table.primary_key.columns]


def _scan_values(con, table: sa.Table, res: ScanResult) -> list[tuple]:
    """Check values; return every row as (pk_tuple, row_dict)."""
    pks = _pk_cols(table)
    cols = [c.name for c in table.columns]
    sel = ", ".join(f'"{c}"' for c in cols)
    rows = []
    for raw in con.execute(f'SELECT rowid, {sel} FROM "{table.name}"'):  # nosec B608 - identifiers from SQLModel metadata
        row = dict(zip(cols, raw[1:]))
        pk = tuple(row[c] for c in pks) if pks else (raw[0],)
        rows.append((pk, row))
        for col in table.columns:
            bad = _bad_value(col, row[col.name])
            if bad:
                res.findings.append(Finding(bad[0], table.name, ",".join(map(str, pk)), bad[1]))
    return rows


def _fk_groups(table: sa.Table):
    for fk in table.foreign_key_constraints:
        yield ([e.parent.name for e in fk.elements], fk.referred_table.name,
               [e.column.name for e in fk.elements])


def scan(path: Path, drop_orphans: bool = False, metadata: sa.MetaData | None = None) -> ScanResult:
    md = metadata or SQLModel.metadata
    res = ScanResult()
    con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        data = {}
        for table in md.sorted_tables:
            if table.name in present:
                data[table.name] = _scan_values(con, table, res)
                res.counts[table.name] = len(data[table.name])
    finally:
        con.close()
    _scan_orphans(md, data, res, drop_orphans)
    return res


def _scan_orphans(md, data, res: ScanResult, drop: bool) -> None:
    gone: dict[str, set[tuple]] = {}  # rows skipped (only when drop) -> children cascade
    for table in md.sorted_tables:  # parents first, so cascades propagate
        if table.name not in data:
            continue
        for ccols, parent, pcols in _fk_groups(table):
            if parent not in data:
                continue
            keys = {tuple(r[c] for c in pcols) for _, r in data[parent]}
            if parent in gone:
                keys -= {tuple(r[c] for c in pcols) for pk, r in data[parent] if pk in gone[parent]}
            for pk, row in data[table.name]:
                val = tuple(row[c] for c in ccols)
                if any(v is None for v in val) or val in keys:
                    continue
                res.findings.append(Finding(
                    "orphan", table.name, ",".join(map(str, pk)),
                    f"{'/'.join(ccols)}={'/'.join(map(str, val))} has no parent in {parent}"))
                if drop:
                    gone.setdefault(table.name, set()).add(pk)
    if drop:
        res.skipped = gone
        res.counts = {t: n - len(gone.get(t, ())) for t, n in res.counts.items()}
