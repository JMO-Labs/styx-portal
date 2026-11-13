"""Monthly takeover review report as CSV (ADR-0060, AU-6)."""
import csv
import io
import re
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import SessionTakeover, User

HEADER = ["actor", "user", "instance", "mode", "reason", "start", "end", "duration"]
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return [start, next-month start) for `YYYY-MM`; ValueError if malformed."""
    if not _MONTH.match(month) or month.startswith("0000"):
        raise ValueError("month must be YYYY-MM")
    y, m = int(month[:4]), int(month[5:])
    return datetime(y, m, 1), datetime(y + (m == 12), m % 12 + 1, 1)


def _cell(v: str) -> str:
    # Neutralise spreadsheet formula injection in user-supplied text.
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


async def build_report(session: AsyncSession, month: str) -> str:
    lo, hi = month_bounds(month)
    rows = (await session.exec(select(SessionTakeover).where(
        SessionTakeover.started_at >= lo, SessionTakeover.started_at < hi)
        .order_by(SessionTakeover.started_at))).all()
    ids = {i for t in rows for i in (t.actor_id, t.user_id) if i}
    names = {}
    if ids:
        names = {u.id: u.username for u in (await session.exec(
            select(User).where(User.id.in_(ids)))).all()}
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(HEADER)
    for t in rows:
        dur = int((t.ended_at - t.started_at).total_seconds()) if t.ended_at else ""
        w.writerow([_cell(names.get(t.actor_id, t.actor_id)),
                    _cell(names.get(t.user_id, t.user_id or "")), t.instance_id, t.mode,
                    _cell(t.reason), t.started_at.isoformat(),
                    t.ended_at.isoformat() if t.ended_at else "", dur])
    return out.getvalue()
