"""Ops alert storage (Alertmanager webhook)."""
from datetime import datetime, timezone

from pydantic import NaiveDatetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OpsAlert(SQLModel, table=True):
    __tablename__ = "ops_alert"
    fingerprint: str = Field(primary_key=True)
    status: str = Field(index=True)  # firing | resolved
    labels: dict = Field(default_factory=dict, sa_column=Column(JSON))
    annotations: dict = Field(default_factory=dict, sa_column=Column(JSON))
    starts_at: NaiveDatetime | None = None
    ends_at: NaiveDatetime | None = None
    updated_at: NaiveDatetime = Field(default_factory=_now)


class OpsState(SQLModel, table=True):
    """Single row (id=1): Watchdog dead-man switch."""
    __tablename__ = "ops_state"
    id: int = Field(default=1, primary_key=True)
    last_watchdog_at: NaiveDatetime | None = None
