"""Postgres abuse store: lockout, brake, IP-fail and rate-limit state shared across replicas.

Every time comparison uses the database clock (`now()`), never the app's, so replicas with
skewed clocks agree. Each call is one short transaction. Errors propagate: callers own the
fail policy (lockout/ban/strict-auth deny, default rate limit allows).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.services.abuse import ip_key

BRAKE_SECONDS = 10

_COUNT = text("SELECT count(*) FROM auth_fail_events WHERE kind = :kind AND key = :key "
              "AND at > now() - make_interval(secs => :win)")
_ADD = text("INSERT INTO auth_fail_events (kind, key, username, at) "
            "VALUES (:kind, :key, :username, now())")
_DROP_EVENTS = text("DELETE FROM auth_fail_events WHERE kind = :kind AND key = :key")
_BLOCK = text("INSERT INTO auth_blocks (kind, key, username, until) "
              "VALUES (:kind, :key, :username, now() + make_interval(secs => :dur)) "
              "ON CONFLICT (kind, key) DO UPDATE SET until = EXCLUDED.until, "
              "username = EXCLUDED.username")
_BRAKE = text("INSERT INTO auth_blocks (kind, key, username, until) "
              "VALUES ('brake', CAST(:key AS text), CAST(:key AS text), now() + make_interval(secs => :dur)) "
              "ON CONFLICT (kind, key) DO UPDATE SET until = EXCLUDED.until "
              "WHERE auth_blocks.until <= now() RETURNING 1")
_BLOCKED = text("SELECT 1 FROM auth_blocks WHERE kind = :kind AND key = :key AND until > now()")
_RATE = text("""
INSERT INTO rate_counters (key, window_start, count, expires_at)
SELECT CAST(:key AS text), to_timestamp(t.ws), 1, to_timestamp(t.ws + 2 * CAST(:win AS double precision))
FROM (SELECT floor(extract(epoch FROM now()) / CAST(:win AS double precision))
             * CAST(:win AS double precision) AS ws) t
ON CONFLICT (key, window_start) DO UPDATE SET count = rate_counters.count + 1
RETURNING count,
  extract(epoch FROM now() - window_start) / CAST(:win AS double precision) AS frac,
  COALESCE((SELECT p.count FROM rate_counters p WHERE p.key = :key
            AND p.window_start = rate_counters.window_start
                - make_interval(secs => CAST(:win AS double precision))), 0) AS prev
""")


def _name(username: str) -> str:
    return username.strip().lower()


class PgAbuseStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def _fail(self, conn, kind, key, username, threshold, window) -> bool:
        """Record one failure; True when the window now holds >= threshold."""
        await conn.execute(_ADD, {"kind": kind, "key": key, "username": username})
        n = (await conn.execute(_COUNT, {"kind": kind, "key": key, "win": float(window)})).scalar_one()
        return n >= threshold

    async def is_locked(self, username, ip):
        key = f"{_name(username)}|{ip_key(ip)}"
        async with self._engine.connect() as conn:
            return (await conn.execute(_BLOCKED, {"kind": "user_ip", "key": key})).first() is not None

    async def locked_for(self, username):
        async with self._engine.connect() as conn:
            return float((await conn.execute(text(
                "SELECT COALESCE(max(extract(epoch FROM until - now())), 0) FROM auth_blocks "
                "WHERE kind = 'user_ip' AND username = :u AND until > now()"),
                {"u": _name(username)})).scalar_one())

    async def record_fail(self, username, ip, threshold, duration):
        name = _name(username)
        key = f"{name}|{ip_key(ip)}"
        async with self._engine.begin() as conn:
            await conn.execute(_ADD, {"kind": "user", "key": name, "username": name})
            if not await self._fail(conn, "user_ip", key, name, threshold, duration):
                return False
            await conn.execute(_DROP_EVENTS, {"kind": "user_ip", "key": key})
            await conn.execute(_BLOCK, {"kind": "user_ip", "key": key, "username": name,
                                        "dur": float(duration)})
            return True

    async def clear(self, username, ip):
        p = {"kind": "user_ip", "key": f"{_name(username)}|{ip_key(ip)}"}
        async with self._engine.begin() as conn:
            await conn.execute(_DROP_EVENTS, p)
            await conn.execute(text("DELETE FROM auth_blocks WHERE kind = :kind AND key = :key"), p)

    async def clear_user(self, username):
        async with self._engine.begin() as conn:
            p = {"u": _name(username)}
            await conn.execute(text("DELETE FROM auth_fail_events WHERE username = :u "
                                    "AND kind IN ('user_ip', 'user')"), p)
            await conn.execute(text("DELETE FROM auth_blocks WHERE username = :u "
                                    "AND kind IN ('user_ip', 'brake')"), p)

    async def throttled(self, username, threshold, duration):
        name = _name(username)
        async with self._engine.begin() as conn:
            n = (await conn.execute(_COUNT, {"kind": "user", "key": name,
                                             "win": float(duration)})).scalar_one()
            if n < threshold:
                return False
            # Atomic: a row comes back only for the one caller that moved `until` forward.
            won = (await conn.execute(_BRAKE, {"key": name, "dur": float(BRAKE_SECONDS)})).first()
            return won is None

    async def device_blocked(self, rnd):
        async with self._engine.connect() as conn:
            return (await conn.execute(_BLOCKED, {"kind": "device", "key": rnd})).first() is not None

    async def device_fail(self, rnd, threshold, duration):
        async with self._engine.begin() as conn:
            if await self._fail(conn, "device", rnd, None, threshold, duration):
                await conn.execute(_DROP_EVENTS, {"kind": "device", "key": rnd})
                await conn.execute(_BLOCK, {"kind": "device", "key": rnd, "username": None,
                                            "dur": float(duration)})

    async def device_clear(self, rnd):
        async with self._engine.begin() as conn:
            await conn.execute(_DROP_EVENTS, {"kind": "device", "key": rnd})
            await conn.execute(text("DELETE FROM auth_blocks WHERE kind = 'device' AND key = :key"),
                               {"key": rnd})

    async def ip_fail(self, ip, threshold, window):
        key = ip_key(ip)
        async with self._engine.begin() as conn:
            if not await self._fail(conn, "ip", key, None, threshold, window):
                return False
            await conn.execute(_DROP_EVENTS, {"kind": "ip", "key": key})
            return True

    async def rate_allow(self, key, limit, window):
        """Two fixed windows: this one's count plus the previous one weighted by overlap."""
        async with self._engine.begin() as conn:
            count, frac, prev = (await conn.execute(_RATE, {"key": key, "win": float(window)})).one()
        return count + prev * (1 - min(float(frac), 1.0)) <= limit
