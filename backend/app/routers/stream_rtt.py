"""POST /api/stream/rtt: client-reported RTT bucket counts into a fixed-cardinality histogram."""
import math
import threading
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import StreamSession, User
from app.security.deps import get_current_user
from app.services import slo_metrics

router = APIRouter()

BUCKET_KEYS = frozenset(slo_metrics.RTT_KEYS)
MAX_SAMPLES = 15
MAX_SAMPLE_SECONDS = 10.0
LIMIT, WINDOW = 2, 60.0
_hits: dict[str, deque] = {}
_lock = threading.Lock()


def reset_limiter() -> None:
    with _lock:
        _hits.clear()


def _allow(user_id: str) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(user_id, deque())
        while q and now - q[0] >= WINDOW:
            q.popleft()
        if len(q) >= LIMIT:
            return False
        q.append(now)
        return True


class RttReport(BaseModel):
    transport: Literal["webrtc", "websocket"]
    buckets: dict[str, StrictInt]
    sum: float = Field(allow_inf_nan=False)

    @field_validator("buckets")
    @classmethod
    def _buckets(cls, v: dict[str, int]) -> dict[str, int]:
        if not set(v) <= BUCKET_KEYS:
            raise ValueError("unknown bucket key")
        if any(n < 0 for n in v.values()):
            raise ValueError("counts must be >= 0")
        if sum(v.values()) > MAX_SAMPLES:
            raise ValueError(f"at most {MAX_SAMPLES} samples")
        return v

    @model_validator(mode="after")
    def _sum(self):
        total = sum(self.buckets.values())
        if not math.isfinite(self.sum) or self.sum < 0 or self.sum > total * MAX_SAMPLE_SECONDS:
            raise ValueError("sum out of range")
        return self


@router.post("/rtt", status_code=status.HTTP_204_NO_CONTENT)
async def report_rtt(body: RttReport, user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    open_row = (await session.exec(select(StreamSession.id).where(
        StreamSession.user_id == user.id, StreamSession.ended_at.is_(None)).limit(1))).first()
    if open_row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no open stream session")
    if not _allow(user.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limited",
                            headers={"Retry-After": str(int(WINDOW))})
    slo_metrics.observe_rtt_buckets(body.transport, body.buckets, body.sum)
