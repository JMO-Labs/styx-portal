import uuid
from urllib.parse import urlsplit
from datetime import datetime, timezone
from typing import Any

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON, BigInteger, LargeBinary, DateTime, Index, Integer, String, UniqueConstraint

from app.db_types import NAMING_CONVENTION, UTCDateTime

SQLModel.metadata.naming_convention = NAMING_CONVENTION


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=_uuid, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str | None = Field(default=None, index=True)
    password_hash: str
    role: str = "user"  # admin | user
    is_active: bool = True
    must_change_pw: bool = False
    token_version: int = 0   # bumped on password/role/disable; access JWTs carry it ("tv")
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    last_login: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    failed_count: int = 0
    locked_until: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    open_workspaces: str | None = None  # None = ask | new_tab | same_tab
    open_apps: str | None = None
    matrix_card: str | None = None       # Fernet-sealed JSON card (active)
    matrix_pending: str | None = None    # sealed card awaiting activation
    matrix_challenge: str | None = None  # JSON list of pending challenge cells
    matrix_serial: int = 0
    end_date: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    disabled_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    disabled_reason: str | None = None
    reviewed_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)


class BannedIP(SQLModel, table=True):
    __tablename__ = "banned_ip"

    ip: str = Field(primary_key=True)
    reason: str = ""
    banned_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    expires_at: NaiveDatetime = Field(sa_type=UTCDateTime)


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"

    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(JSON))
    updated_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    updated_by: str | None = None


class TurnUsage(SQLModel, table=True):
    """Relayed TURN bytes per month / workstation / user (user NULL = unattributed)."""
    __tablename__ = "turn_usage"
    __table_args__ = (UniqueConstraint("month", "workstation_id", "user_id",
                                       name="uq_turn_usage"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    month: str = Field(index=True)   # YYYY-MM (UTC)
    workstation_id: str = Field(foreign_key="workstations.id")
    user_id: str | None = Field(default=None, foreign_key="users.id")
    bytes: int = Field(default=0, sa_type=BigInteger)  # > 2 GiB; int32 overflows on PG


class TurnUsageDay(SQLModel, table=True):
    """Relayed TURN bytes per UTC day (all workstations)."""
    __tablename__ = "turn_usage_day"

    day: str = Field(primary_key=True)   # YYYY-MM-DD
    bytes: int = Field(default=0, sa_type=BigInteger)  # > 2 GiB; int32 overflows on PG


class MetricHour(SQLModel, table=True):
    """Hourly host metric rollup (kept 90 days). Percentages 0-100."""
    __tablename__ = "metric_hours"

    ts_hour: NaiveDatetime = Field(sa_type=UTCDateTime, primary_key=True)  # UTC hour start
    cpu_avg: float | None = None                  # None = no samples
    cpu_max: float | None = None
    ram_avg: float | None = None
    disk_pct: float = 0
    live_max: int = 0
    health: str | None = None                     # ok | warn | fail (None = no data)


class StreamSession(SQLModel, table=True):
    """One user's streaming stint on a workstation/instance (open while ended_at is NULL)."""
    __tablename__ = "stream_sessions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str | None = Field(default=None, index=True)
    target_kind: str                              # workstation | instance
    target_id: str = Field(index=True)
    started_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now, index=True)
    ended_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    transport: str | None = None
    codec: str | None = None
    relayed: bool = False
    relay_reason: str | None = None               # strict_nat | firewall | mobile | unknown


class Invite(SQLModel, table=True):
    __tablename__ = "invites"

    id: str = Field(default_factory=_uuid, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    email: str | None = None
    role: str = "user"
    created_by: str = Field(foreign_key="users.id")
    expires_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    used_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    jti: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    family_id: str = Field(default="", index=True)
    expires_at: NaiveDatetime = Field(sa_type=UTCDateTime)
    revoked: bool = False
    user_agent: str | None = None
    session_only: bool = False
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class RevokedAccessToken(SQLModel, table=True):
    """Denylist of access-token jtis invalidated before their exp (logout).
    Rows are purged once past expires_at — a revoked token is dead by then."""
    __tablename__ = "revoked_access_tokens"

    jti: str = Field(primary_key=True)
    expires_at: NaiveDatetime = Field(sa_type=UTCDateTime)
    revoked_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class OAuthProvider(SQLModel, table=True):
    __tablename__ = "oauth_providers"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(unique=True, index=True)        # "google" | "github" | "authentik"
    display_label: str
    kind: str = "oidc"                                 # "oidc" | "oauth2"
    issuer_url: str | None = None                      # oidc: discovery base
    authorize_url: str | None = None                   # oauth2: explicit endpoints
    token_url: str | None = None
    userinfo_url: str | None = None
    client_id: str
    client_secret_enc: str
    scopes: str = "openid email profile"
    icon_url: str | None = None                        # remote URL or base64 data URI
    trust_email: bool = False                          # treat missing email_verified as verified
    allow_signup: bool = False                          # auto-provision users without an invite
    auto_promote_admins: bool = True                   # IdP admin-group claim elevates role
    role_map: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = True
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    updated_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class FederatedIdentity(SQLModel, table=True):
    __tablename__ = "federated_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_provider_subject"),)

    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    provider: str = Field(index=True)
    subject: str = Field(index=True)
    email: str | None = None
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class ServiceTemplate(SQLModel, table=True):
    __tablename__ = "service_templates"

    id: str = Field(default_factory=_uuid, primary_key=True)
    owner_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    name: str = Field(unique=True, index=True)
    display_name: str
    image: str
    icon: str | None = None
    description: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    gpu_enabled: bool = False
    gpu_count: int = 0
    memory_limit: str | None = None
    cpu_limit: str | None = None
    shm_size: str | None = None
    dind: bool = False
    cap_add: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    security_opt: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tls_skip_verify: bool = False
    shared: bool = False
    restart_policy: str = "no"
    read_only_rootfs: bool = False
    tmpfs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    extra_hosts: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    ulimits: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    extra_ports: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    entrypoint: list[str] | None = Field(default=None, sa_column=Column(JSON))
    command: list[str] | None = Field(default=None, sa_column=Column(JSON))
    devices: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    privileged: bool = False
    extra_docker_args: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    volumes: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON))
    profile_mount: str | None = None
    internal_port: int = 3001
    internal_protocol: str = "https"
    category: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    session_config: dict[str, Any] = Field(
        default_factory=lambda: {
            "idle_timeout": "14m",
            "grace_period": "1m",
            "timeout_action": "stop",
            "never_timeout": False,
            "max_session_duration": None,
        },
        sa_column=Column(JSON),
    )
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    updated_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class Instance(SQLModel, table=True):
    __tablename__ = "instances"

    id: str = Field(default_factory=_uuid, primary_key=True)
    template_id: str = Field(foreign_key="service_templates.id")
    owner_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    name: str
    subdomain: str = Field(unique=True, index=True)
    container_id: str | None = None
    status: str = "created"
    error_message: str | None = None
    status_detail: str | None = None
    env_overrides: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    volume_names: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    profile_volume: str | None = None
    gpu: bool | None = None  # None = legacy: use template.gpu_enabled
    notice: str | None = None
    image_digest: str | None = None  # pinned at launch (k8s), never changed after
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    started_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    stopped_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    last_activity: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    session_config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class SessionEvent(SQLModel, table=True):
    __tablename__ = "session_events"

    id: int | None = Field(default=None, primary_key=True)
    # No FK: events are history and outlive their instance ("destroyed" is written on delete).
    instance_id: str
    event_type: str
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timestamp: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class PulledImage(SQLModel, table=True):
    __tablename__ = "pulled_images"

    id: str = Field(default_factory=_uuid, primary_key=True)
    image: str = Field(unique=True, index=True)
    size_mb: int | None = None
    pulled_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now, index=True)
    user_id: str | None = Field(default=None, index=True)
    actor_ip: str | None = None
    action: str = Field(index=True)
    resource: str | None = None
    detail: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Workstation(SQLModel, table=True):
    __tablename__ = "workstations"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    subdomain: str = Field(unique=True, index=True)
    hostname: str = ""
    lan_ip: str = ""
    port: int = 8443
    protocol: str = "http"               # selkies on the workstation; http for v1
    status: str = "pending"              # pending | online | offline | revoked
    display_server: str = "x11"          # x11 | wayland
    gpu_info: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    os_info: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    agent_version: str = ""
    agent_token_hash: str = Field(default="", index=True)
    selkies_password_enc: str = ""
    stream_settings: dict[str, Any] = Field(
        default_factory=lambda: {"encoder": "auto", "framerate": 60},
        sa_column=Column(JSON),
    )
    all_users: bool = False
    # None = auto badge; "emoji:<char>" or a "data:<mime>;base64,..." image.
    icon: str | None = None
    update_target: str = ""
    update_state: str = ""
    update_error: str | None = None
    update_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    last_heartbeat: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    last_error: str | None = None
    # Occupancy: live stream-connection count reported by the agent's
    # gateway each heartbeat; occupant identity recorded by forward-auth
    # when a websocket upgrade passes (single-user desktops).
    active_connections: int = 0
    occupied_by: str | None = Field(default=None, foreign_key="users.id")
    occupied_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    # One-shot flag: set when a user logs out with an active session; the next
    # agent heartbeat returns disconnect_clients=True and consumes the flag.
    disconnect_pending: bool = False
    # Latch so an idle force-disconnect fires once per session, not every
    # heartbeat. Without it, an idle browser that auto-reconnects keeps
    # active_connections > 0 while idle, so the backend re-issues a disconnect
    # each heartbeat → the agent restarts its gateway every cycle (502 loop).
    # Re-armed when active_connections returns to 0 (a genuinely new session).
    idle_disconnect_sent: bool = False
    created_by: str = Field(foreign_key="users.id")
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class WorkstationEnrollmentToken(SQLModel, table=True):
    __tablename__ = "workstation_enrollment_tokens"

    id: str = Field(default_factory=_uuid, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    created_by: str = Field(foreign_key="users.id")
    expires_at: NaiveDatetime = Field(sa_type=UTCDateTime)
    used_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class WorkstationAccess(SQLModel, table=True):
    __tablename__ = "workstation_access"
    __table_args__ = (UniqueConstraint("workstation_id", "user_id", name="uq_workstation_user"),)

    id: int | None = Field(default=None, primary_key=True)
    workstation_id: str = Field(foreign_key="workstations.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class ApprovedRequest(SQLModel, table=True):
    """Approved provisioning request from the webhook, awaiting card binding (#120)."""
    __tablename__ = "approved_requests"

    id: str = Field(default_factory=_uuid, primary_key=True)
    idempotency_key: str = Field(unique=True, index=True)
    body_hash: str                      # SHA-256 of the canonical body
    approval_id: str = Field(unique=True, index=True)
    external_id: str = Field(unique=True, index=True)
    approver_email: str
    groups: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    card_type: str
    person_type: str
    end_date: str | None = None
    status: str = "pending_binding"
    # Subject PII (name, email, EDIPI) kept for the binding step; never audited.
    subject: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class CardReview(SQLModel, table=True):
    """First-login card that matched no single approved request; held for admin (#122)."""
    __tablename__ = "card_review_queue"

    id: str = Field(default_factory=_uuid, primary_key=True)
    kc_user_id: str = Field(index=True)
    card_type: str
    # Sensitive card ids (EDIPI / card UUID): never logged, audited or returned by the API.
    claims: dict = Field(default_factory=dict, sa_column=Column(JSON))
    reason: str                         # no_match | multiple_matches | invalid_claims
    status: str = "pending"             # pending | approved | rejected
    resolved_by: str | None = None
    resolved_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class Group(SQLModel, table=True):
    __tablename__ = "groups"
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    allow_gpu: bool = False
    egress_mode: str = "category"
    # Per-group CPU-tier overrides (ADR-0031); None = use the global default.
    tier_resolution: str | None = None
    tier_fps: int | None = None
    tier_hidpi: bool | None = None
    tier_cpu: str | None = None
    tier_memory: str | None = None
    idp_managed: bool = False  # membership mirrored from the IdP groups claim; read-only in API
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class UserGroup(SQLModel, table=True):
    __tablename__ = "user_groups"
    user_id: str = Field(foreign_key="users.id", primary_key=True)
    group_id: str = Field(foreign_key="groups.id", primary_key=True)


class UserProfile(SQLModel, table=True):
    __tablename__ = "user_profiles"
    user_id: str = Field(foreign_key="users.id", primary_key=True)
    template_id: str = Field(foreign_key="service_templates.id", primary_key=True)
    volume_name: str
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class ServicePreset(SQLModel, table=True):
    """Routing preset seeded from templates/services/*.json (upserted on startup)."""
    __tablename__ = "service_presets"
    id: str = Field(primary_key=True)          # e.g. "sonarr"
    name: str
    icon: str | None = None
    default_port: int | None = None
    mount_mode: str = "path"
    auth_mode: str = "sso"
    bypass_rules: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    health_path: str | None = None
    verify_tls: bool = True
    base_url_hint: str | None = None
    warnings: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    subpath: dict | None = Field(default=None, sa_column=Column(JSON))


class ServiceThumbnail(SQLModel, table=True):
    """Shared service thumbnail (PNG): bytea on PG, BLOB on SQLite; any replica serves it."""
    __tablename__ = "service_thumbnails"
    service_id: str = Field(primary_key=True, foreign_key="proxied_services.id", ondelete="CASCADE")
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    updated_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


class ProxiedService(SQLModel, table=True):
    __tablename__ = "proxied_services"
    id: str = Field(default_factory=_uuid, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    icon: str | None = None
    kind: str = "url"                          # url | docker-local
    upstream_url: str | None = None            # url kind
    container: str | None = None               # docker-local kind
    container_port: int | None = None
    # Set when connecting the container to the styx network failed and we
    # fell back to host.docker.internal (see routers/services.py).
    upstream_fallback: str | None = None
    mount_mode: str = "path"                   # path | cookie-root
    auth_mode: str = "sso"                     # sso | sso-with-bypass | app-native
    bypass_rules: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    allowed_groups: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    verify_tls: bool = True
    upstream_is_proxy: bool = False            # url kind: send the URL hostname as Host/SNI
    health_path: str | None = None
    health_status: str = "unknown"             # healthy | unhealthy | unknown
    health_checked_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)
    preset_id: str | None = None
    enabled: bool = True
    mount_managed: bool = False   # base path confirmed: Styx set it, or found it already set (spec §3)
    icon_custom: bool = False     # admin set the icon by hand; auto-fetch never overwrites it
    pass_identity: bool = False   # forward X-Styx-User/Email/Groups upstream
    frame_ok: bool = True         # False = "Open without overlay"
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    updated_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)


def upstream_base(svc: "ProxiedService") -> str:
    """Base URL Traefik and the health loop use to reach the service."""
    if svc.kind == "docker-local":
        return svc.upstream_fallback or f"http://{svc.container}:{svc.container_port}"
    return (svc.upstream_url or "").rstrip("/")


def proxy_hostname(svc: "ProxiedService") -> str | None:
    """Lowercased URL hostname to send as Host/SNI to a name-based reverse proxy, else None."""
    if svc.kind != "url" or not svc.upstream_is_proxy or not svc.upstream_url:
        return None
    return urlsplit(svc.upstream_url).hostname


class MountJob(SQLModel, table=True):
    """One base-path apply run (spec §3.2). steps: [{id,label,state,detail}]."""
    __tablename__ = "mount_jobs"
    id: str = Field(default_factory=_uuid, primary_key=True)
    service_id: str = Field(index=True)
    state: str = "pending"        # pending|running|done|rolled_back|failed
    steps: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    changes: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    backup_dir: str | None = None
    changed: bool = False         # True once a write to the container may have landed
    log_excerpt: str | None = None
    created_at: NaiveDatetime = Field(sa_type=UTCDateTime, default_factory=_now)
    finished_at: NaiveDatetime | None = Field(default=None, sa_type=UTCDateTime)


_TSTZ = DateTime(timezone=True)


class AuthFailEvent(SQLModel, table=True):
    """One failed attempt (shared across replicas). kind: user_ip|user|ip|device."""
    __tablename__ = "auth_fail_events"
    __table_args__ = (Index("ix_auth_fail_events_kind_key_at", "kind", "key", "at"),)
    id: int | None = Field(default=None, sa_column=Column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    kind: str
    key: str
    username: str | None = Field(default=None, index=True)   # lowercased
    at: datetime = Field(sa_column=Column(_TSTZ, nullable=False))


class AuthBlock(SQLModel, table=True):
    """Active lock/brake/device block, written with DB time. kind: user_ip|brake|device."""
    __tablename__ = "auth_blocks"
    kind: str = Field(primary_key=True)
    key: str = Field(primary_key=True)
    username: str | None = Field(default=None, index=True)   # lowercased
    until: datetime = Field(sa_column=Column(_TSTZ, nullable=False, index=True))


class RateCounter(SQLModel, table=True):
    """Fixed-window request counter for the shared rate limit."""
    __tablename__ = "rate_counters"
    __table_args__ = {"postgresql_with": {"fillfactor": "70"}}
    key: str = Field(primary_key=True)
    window_start: datetime = Field(sa_column=Column(_TSTZ, primary_key=True))
    count: int = 0
    expires_at: datetime = Field(sa_column=Column(_TSTZ, nullable=False, index=True))


class PosixUid(SQLModel, table=True):
    """Immutable POSIX UID per user_key (ADR-0052). Rows are never updated or deleted."""
    __tablename__ = "posix_uids"
    uid: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    user_key: str = Field(sa_column=Column(String, nullable=False, unique=True))
    allocated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(_TSTZ, nullable=False))
