import re
from datetime import datetime, timedelta, timezone

from app.models import Instance, SessionEvent
from app.services.docker_manager import DockerManager
from app.services.session_audit import record_session_event

_DURATION_RE = re.compile(r"^(\d+)(s|m|h)$")


class SessionMonitor:
    def __init__(self, docker_manager: DockerManager):
        self._docker = docker_manager

    def _parse_duration(self, value: str) -> timedelta:
        match = _DURATION_RE.fullmatch(value)
        if not match:
            return timedelta(minutes=30)
        amount, unit = int(match.group(1)), match.group(2)
        if unit == "s":
            return timedelta(seconds=amount)
        if unit == "m":
            return timedelta(minutes=amount)
        return timedelta(hours=amount)

    def check_instance(self, instance: Instance, session) -> list[str]:
        if instance.status not in ("running", "idle"):
            return []

        config = instance.session_config or {}
        if config.get("never_timeout"):
            return []

        idle_timeout = self._parse_duration(config.get("idle_timeout", "14m"))
        grace_period = self._parse_duration(config.get("grace_period", "1m"))

        now = datetime.now(timezone.utc)
        last_activity = instance.last_activity or instance.started_at or now
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        idle_duration = now - last_activity

        actions = []

        if instance.status == "idle" and idle_duration > (idle_timeout + grace_period):
            self._docker.stop_container(instance.container_id)
            instance.status = "stopped"
            instance.stopped_at = now
            session.add(instance)
            actions.append("auto_stopped")

        elif instance.status == "running" and idle_duration > idle_timeout:
            instance.status = "idle"
            session.add(instance)
            event = SessionEvent(
                instance_id=instance.id,
                event_type="idle_warning",
                details={"idle_seconds": idle_duration.total_seconds()},
            )
            session.add(event)
            actions.append("idle_warning")

        return actions

    async def record_auto_stop(self, session, instance: Instance) -> None:
        """Row + ECS ``session.stop`` (reason idle) for an instance check_instance stopped."""
        last = instance.last_activity or instance.started_at or instance.stopped_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        idle = (instance.stopped_at - last).total_seconds() if last and instance.stopped_at else 0
        await record_session_event(session, instance, "auto_stopped", action="session.stop",
                                   reason="idle", details={"idle_seconds": idle})

    def check_all(self, session, instances: list[Instance]) -> dict[str, list[str]]:
        results = {}
        for instance in instances:
            actions = self.check_instance(instance, session)
            if actions:
                results[instance.id] = actions
        return results
