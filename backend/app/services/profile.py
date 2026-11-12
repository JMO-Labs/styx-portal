"""Deployment profile (ADR-0053, CM-7): enterprise hard-disables homelab features."""
import re
from pathlib import Path

PROFILES = ("homelab", "enterprise")

# feature -> path regexes (matched against request.url.path)
ENTERPRISE_DISABLED: dict[str, tuple[re.Pattern, ...]] = {
    # login + every route that creates or sets a local password
    "password_login": (re.compile(r"^/api/auth/(login|setup|change-password|accept-invite)$"),
                       re.compile(r"^/api/users/[^/]+/(reset-password|force-password-change)$")),
    "matrix_2fa": (re.compile(r"^/api/auth/(login/)?matrix(/|$)"),
                   re.compile(r"^/api/users/[^/]+/matrix$")),
    "generic_oidc": (re.compile(r"^/api/auth/(oauth|link)(/|$)"),
                     re.compile(r"^/api/oauth-providers(/|$)")),
    "workstation_enrollment": (re.compile(r"^/api/(enroll|agent|workstations)(/|$)"),
                               re.compile(r"^/internal/workstations(/|$)")),
    "docker_routers": (re.compile(r"^/api/(images|registry)(/|$)"),
                       re.compile(r"^/api/services/[^/]+/mount(/|$)")),
}
ALL_FEATURES = tuple(ENTERPRISE_DISABLED)


def disabled_features(s) -> list[str]:
    return list(ENTERPRISE_DISABLED) if s.STYX_PROFILE == "enterprise" else []


def blocked_feature(s, path: str) -> str | None:
    if s.STYX_PROFILE != "enterprise":
        return None
    for feature, pats in ENTERPRISE_DISABLED.items():
        if any(p.search(path) for p in pats):
            return feature
    return None


def validate_profile(s) -> None:
    """Raise RuntimeError on an unknown profile or enterprise + homelab runtime."""
    if s.STYX_PROFILE not in PROFILES:
        raise RuntimeError(f"STYX_PROFILE must be one of {PROFILES} (got {s.STYX_PROFILE!r})")
    if s.STYX_PROFILE != "enterprise":
        return
    if s.ROUTE_BACKEND != "k8s":
        raise RuntimeError("STYX_PROFILE=enterprise requires ROUTE_BACKEND=k8s")
    sock = s.DOCKER_SOCKET.removeprefix("unix://")
    if sock and Path(sock).exists():
        raise RuntimeError(
            f"STYX_PROFILE=enterprise refuses a Docker socket ({sock}): unmount it")
