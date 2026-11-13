import json
import logging
import os
import secrets as _secrets
from pathlib import Path

from pydantic_settings import BaseSettings

logger = logging.getLogger("styx-portal")

PLACEHOLDER_SECRETS = {
    "change-me-to-a-long-random-string-min-32-bytes",
    "dev-insecure-secret-do-not-use-in-prod",
}


class Settings(BaseSettings):
    # homelab | enterprise (ADR-0053): enterprise hard-disables homelab features
    STYX_PROFILE: str = "homelab"
    DOMAIN: str = "localhost"
    POSIX_UID_MIN: int = 100000  # first allocated POSIX UID (ADR-0052)
    # Provisioning webhook auth (ADR-0020 / D20): mTLS (forwarded Client-Cert) + bearer
    PROVISION_HOST: str = ""
    PROVISION_BEARER_TOKEN: str = ""
    PROVISION_CLIENT_CERT_FINGERPRINTS: str = ""  # comma-separated SHA-256 hex of DER
    KEYCLOAK_ADMIN_GROUPS: str = ""  # comma-separated; never grantable via the webhook
    PROVISION_GROUP_MANAGERS: str = ""  # JSON {"group-slug": ["manager@email", ...]}
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/styx-portal.db"
    # Leader election: dedicated session connection, straight to the primary
    # (never a pooler). Empty = same as DATABASE_URL.
    LEADER_DATABASE_URL: str = ""
    LEADER_RETRY_S: float = 5.0
    LEADER_HEARTBEAT_S: float = 5.0
    LEADER_HEARTBEAT_TIMEOUT_S: float = 3.0
    LEADER_FENCE_S: float = 15.0  # must stay below server-side detection (~25 s)
    # Internal Prometheus port (never Traefik-routed). 0 = metrics server off.
    METRICS_PORT: int = 0
    DOCKER_SOCKET: str = "unix:///var/run/docker.sock"
    DOCKER_NETWORK: str = "styx-portal"
    # Proxied docker-local services join this network; only Traefik shares it
    # (backend/frontend do not), so an app container cannot reach Styx directly.
    SERVICES_NETWORK: str = "styx-services"
    TRAEFIK_CONTAINER: str = "styx-traefik"  # attached to per-user/service networks
    # Compose project whose containers are "ours" (hidden from discovery).
    # Empty = derive it from the Traefik container's compose label.
    COMPOSE_PROJECT: str = ""
    SELKIES_DEFAULT_PORT: int = 3001
    TEMPLATES_DIR: str = "/app/templates"
    SERVICE_PRESETS_DIR: str = "/app/templates/services"
    WIKI_URL: str = ""     # enterprise: seeds a "My services" link when set
    ELEMENT_URL: str = ""  # enterprise: same, for Element
    SCREENSHOT_CACHE_DIR: str = "/app/data/screenshots"
    SCREENSHOT_INTERVAL_SECONDS: int = 30
    SERVICE_THUMBNAIL_MAX_BYTES: int = 1_048_576  # reject larger service thumbnails
    MOUNT_BACKUP_DIR: str = "./data/mount-backups"
    MOUNT_PROBE_IMAGE: str = "busybox:1.36"
    TRAEFIK_DYNAMIC_DIR: str = "/app/traefik-dynamic"
    ROUTE_BACKEND: str = "file"   # file | k8s
    K8S_NAMESPACE: str = "styx"
    K8S_INSTANCE_NAMESPACE: str = "styx-instances"
    HARBOR_URL: str = ""   # empty = no digest pinning (ADR-0030)
    HARBOR_USER: str = ""
    HARBOR_PASSWORD: str = ""
    DIGEST_CACHE_S: int = 60  # per-ref cache of resolved Harbor digests (0 = off)
    PREPULL_INTERVAL_S: int = 3600  # image prepull sync loop
    CVE_RECYCLE_INTERVAL_S: int = 3600  # critical-CVE scan loop (ADR-0030)
    CVE_RECYCLE_GRACE_H: int = 24
    SESSION_REAPER_INTERVAL_S: int = 60  # leader-only session reaper (ADR-0039)
    SESSION_DISCONNECT_MAX_H: float = 2
    SESSION_MAX_H: float = 12
    SESSION_WARN_MIN: int = 15
    GATEWAY_PORT: int = 8080  # in-pod gateway serving /styx/state
    K8S_DESKTOP_IMAGE: str = "ghcr.io/jmo-labs/styx-desktop:latest"
    EGRESS_PROXY_HOST: str = "squid.egress-proxy.svc.cluster.local"
    EGRESS_PROXY_PORT_CATEGORY: int = 3128
    EGRESS_PROXY_PORT_ALLOWLIST: int = 3129
    INSTANCE_STORAGE_CLASS: str = "longhorn"
    INSTANCE_VOLUME_SIZE: str = "20Gi"
    HOME_STORAGE_CLASS: str = "ceph-cephfs"
    HOME_QUOTA: str = "10Gi"
    HOME_MOUNT_PATH: str = "/home/user"
    PROMETHEUS_URL: str = ""  # kube-prometheus-stack, for home usage (ADR-0044)
    PROFILE_QUOTA: str = "2Gi"
    CPU_TIER_RESOLUTION: str = "1920x1080"  # ADR-0031 CPU-tier launch defaults
    CPU_TIER_FPS: int = 30
    CPU_TIER_HIDPI: bool = False
    CPU_TIER_CPU: str = "3"
    CPU_TIER_MEMORY: str = "4Gi"
    PROFILE_VOLUME_SIZE: str = "20Gi"
    K8S_CLUSTER_CIDRS: str = "10.42.0.0/16,10.43.0.0/16"   # pod,service ranges
    K8S_UPSTREAM_DENY_NAMESPACES: str = (
        "kube-system,kube-public,kube-node-lease,default,longhorn-system,"
        "cert-manager,metallb-system,argocd")
    # Base for every forwardAuth/errors address Traefik calls back to
    BACKEND_INTERNAL_URL: str = "http://backend:8000"
    # "<namespace>:<labelSelector>", e.g. cloudflared:pod=cloudflared; empty = disabled
    TUNNEL_PEER_K8S: str = ""
    DEPLOY_MODE: str = "tunnel"   # tunnel | direct
    # Direct peers whose CF-Connecting-IP / X-Forwarded-For are believed
    # (Traefik). Default: loopback only; peers on the subnets of the backend's own interfaces
    # (snapshotted once at startup, see middleware/rate_limit.py) are trusted in addition.
    # LAN clients and networks joined later (screenshots) are not proxies.
    TRUSTED_PROXY_CIDRS: str = "127.0.0.1/32,::1/128"
    # Only peers in this subnet (compose network `styx-tunnel`, shared solely by cloudflared and
    # Traefik) may vouch for CF-Connecting-IP. Traefik also sits in it, but is never its own peer.
    TUNNEL_PEER_CIDRS: str = "172.31.254.0/28"
    # Workstation lan_ip must be inside one of these (comma-separated CIDRs); empty = any
    # routable address. k8s: keeps an enrolled agent from aiming Traefik at in-cluster IPs.
    WORKSTATION_ALLOW_CIDRS: str = ""
    JWT_SECRET: str = ""
    ACCESS_TTL: int = 900          # 15 minutes
    REFRESH_TTL: int = 604800      # 7 days
    SESSION_MAX_AGE: int = 2592000  # 30 days: absolute cap on a refresh family
    MATRIX_SESSION_MAX_HOURS: int = 12  # absolute cap on a session-only (card) family
    MATRIX_DIGEST_WEBHOOK_URL: str = ""  # daily new-account digest target; unset = skipped
    MATRIX_NOTIFY_HOMESERVER: str = ""  # Matrix notify adapter; any of the three empty = off
    MATRIX_NOTIFY_ROOM_ID: str = ""
    MATRIX_NOTIFY_TOKEN: str = ""
    COOKIE_SECURE: bool = True
    DEV_CORS: bool = False          # allow the Vite dev origin (http://localhost:5173) with credentials
    ENABLE_DOCS: bool = False       # expose /docs, /redoc, /openapi.json (dev only)
    COOKIE_DOMAIN: str | None = None
    RATE_LIMIT_AUTH: str = "5/60"        # 5 requests per 60s on /auth/*
    RATE_LIMIT_DEFAULT: str = "120/60"   # 120 requests per 60s otherwise
    RATE_LIMIT_INSTANCE_CREATE: str = "10/3600"  # 10 creates per hour per user
    # --- Brute-force protection ---
    LOCKOUT_THRESHOLD: int = 10           # failed logins per username before lock
    LOCKOUT_DURATION: int = 900           # lock duration seconds (15 min)
    LOGIN_GLOBAL_THRESHOLD: int = 30      # failures per username (any IP) before 1 check/10 s
    BAN_FAIL_THRESHOLD: int = 20          # failed logins per IP in window before ban
    BAN_FAIL_WINDOW: int = 600            # abuse-detector window seconds (10 min)
    BAN_DURATION: int = 3600              # IP ban duration seconds (1 h)
    BAN_CACHE_TTL: int = 30               # ban-set cache refresh interval seconds
    TRAEFIK_RATELIMIT_AVERAGE: int = 100  # L1 proxy avg req/s per IP
    TRAEFIK_RATELIMIT_BURST: int = 50     # L1 proxy burst per IP
    # --- Password policy ---
    PASSWORD_MIN_LENGTH: int = 12
    PASSWORD_REQUIRE_UPPER: bool = False
    PASSWORD_REQUIRE_LOWER: bool = False
    PASSWORD_REQUIRE_DIGIT: bool = False
    PASSWORD_REQUIRE_SYMBOL: bool = False
    MAX_INSTANCES_PER_USER: int = 3      # 0 = unlimited; admins exempt
    OAUTH_REDIRECT_BASE: str = ""   # e.g. https://s.jmolabs.dev ; defaults to https://{DOMAIN}
    BANNER_URL: str = ""            # enterprise: unauthenticated login page redirects here when set
    SECRETS_FILE: str = "/app/data/secrets.json"
    # --- Workstation streaming (physical machines) ---
    SERVER_LAN_URL: str = ""        # e.g. https://192.168.1.10 — used in enrollment one-liner
    SERVER_CA_PIN: str = ""         # optional sha256:<hex fp> for self-signed LAN TLS
    # Legacy source tarball. selkies 2.0 ships as PyPI wheels (see
    # scripts/build_agent_artifacts.sh); agents >= 0.5.0 do not use this.
    SELKIES_APP_URL: str = (
        "https://github.com/selkies-project/selkies/archive/"
        "0d134b6e1ffe42a579bc66363b0e7159ab22aacc.tar.gz"
    )
    ARTIFACT_CACHE_DIR: str = "/app/data/artifacts"
    AGENT_DIR: str = "/app/agent"   # mounted from repo ./agent; dev fallback in enroll router
    ENROLL_TOKEN_TTL_HOURS: int = 1
    WORKSTATION_OFFLINE_AFTER_S: int = 90
    WORKSTATION_DEFAULT_PORT: int = 8443
    WORKSTATION_HEARTBEAT_S: int = 30
    WORKSTATION_IDLE_TIMEOUT_S: int = 900
    WORKSTATION_IDLE_WARN_LEAD_S: int = 60
    WORKSTATION_IDLE_TIMEOUT_ENABLED: bool = True
    WORKSTATION_SEAT_WIDTH: int = 2560
    WORKSTATION_SEAT_HEIGHT: int = 1440
    LAN_CERT_DIR: str = "/app/data/lan-certs"      # backend-side path (lan-certs volume)
    TRAEFIK_LAN_CERT_DIR: str = "/lan-certs"       # same volume as seen by Traefik

    # Keycloak admin client (offboarding); all empty = disabled (calls skipped).
    KC_ADMIN_URL: str = ""
    KC_ADMIN_REALM: str = ""
    KC_ADMIN_CLIENT_ID: str = ""
    KC_ADMIN_CLIENT_SECRET: str = ""
    # Comma-separated Keycloak group ids (not names) the admin client must never add users to.
    KEYCLOAK_ADMIN_GROUPS: str = ""
    # FederatedIdentity.provider name whose subjects are Keycloak user ids.
    KC_PROVIDER_NAME: str = "keycloak"
    # Days after disable before the account and its homes are deleted (ADR-0022).
    ACCOUNT_DELETION_RETENTION_DAYS: int = 90

    # Home archive on S3/RGW; disabled when archive_s3_endpoint is empty.
    archive_s3_endpoint: str = ""
    archive_s3_bucket: str = ""
    archive_s3_access_key: str = ""
    archive_s3_secret_key: str = ""
    homes_root: str = "/homes"

    LIFECYCLE_INACTIVITY_DAYS: int = 35   # auto-disable after this many idle days (ADR-0022)

    # extra="ignore": the repo-root .env is shared with docker-compose,
    # cloudflared, and authentik, so it carries keys the backend does not
    # declare (CF_TUNNEL_TOKEN, AUTHENTIK_HOST, COMPOSE_PROFILES, ...).
    # Ignore them instead of failing to start.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def leader_url(self) -> str:
        return self.LEADER_DATABASE_URL or self.DATABASE_URL

    def jwt_secret_or_raise(self) -> str:
        if self.JWT_SECRET:
            if self.JWT_SECRET in PLACEHOLDER_SECRETS:
                raise RuntimeError(
                    "JWT_SECRET is a placeholder value. Generate a real one: "
                    "openssl rand -base64 48"
                )
            if len(self.JWT_SECRET) < 32:
                raise RuntimeError(
                    f"JWT_SECRET must be at least 32 characters (got {len(self.JWT_SECRET)}). "
                    "Generate one: openssl rand -base64 48"
                )
            return self.JWT_SECRET
        if self.DATABASE_URL.startswith("postgres"):
            raise RuntimeError(
                "JWT_SECRET is required when DATABASE_URL is PostgreSQL: a per-pod "
                "secrets.json would differ between replicas and tokens would fail. "
                "Set the same JWT_SECRET on every replica (openssl rand -base64 48)."
            )
        return self._load_or_create_secret()

    def _load_or_create_secret(self) -> str:
        path = Path(self.SECRETS_FILE)
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Secrets file %s unreadable/corrupt — regenerating", path)
                data = {}
            secret = data.get("jwt_secret")
            if isinstance(secret, str) and len(secret) >= 32:
                return secret
        secret = _secrets.token_urlsafe(48)
        data["jwt_secret"] = secret
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2))
        path.chmod(0o600)  # belt-and-suspenders if file pre-existed with wider mode
        logger.warning(
            "JWT_SECRET not set — generated one and saved to %s. "
            "Back this file up; losing it logs everyone out and invalidates "
            "stored OAuth client secrets.", path,
        )
        return secret

    def oauth_redirect_base(self) -> str:
        return self.OAUTH_REDIRECT_BASE or f"https://{self.DOMAIN}"

    def server_lan_url(self) -> str:
        return (self.SERVER_LAN_URL or f"https://{self.DOMAIN}").rstrip("/")


settings = Settings()
