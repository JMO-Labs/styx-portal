"""Pure checks for deploy/enterprise/harbor/values.yaml (issue #5).

Each check takes the parsed values dict and returns a list of error messages.
"""

import json
import re

DIGEST_REF = re.compile(r"^harbor\.example\.internal/.+@sha256:[0-9a-f]{64}$")
DEFAULT_SECRETS = ("Harbor12345", "not-a-secure-key")
PRIVATE_KEY = re.compile(r"BEGIN .*PRIVATE KEY")
HA_COMPONENTS = ("portal", "core", "jobservice", "registry")


def image_refs(node, path=""):
    """Yield (path, ref) for every dict that has a 'repository' key."""
    if isinstance(node, dict):
        if "repository" in node:
            yield path, f"{node['repository']}:{node.get('tag', '')}".rstrip(":")
        for key, val in node.items():
            yield from image_refs(val, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from image_refs(val, f"{path}[{i}]")


def check_images(v):
    return [f"image {p} not pinned by digest under harbor.example.internal: {ref}"
            for p, ref in image_refs(v) if not DIGEST_REF.match(ref)]


def check_database(v):
    db = v.get("database", {})
    ext = db.get("external", {})
    errs = []
    if db.get("type") != "external":
        errs.append("database.type must be external")
    if ext.get("sslmode") != "verify-full":
        errs.append(f"database.external.sslmode must be verify-full, got {ext.get('sslmode')}")
    if ext.get("existingSecret") != "harbor-db-app":
        errs.append("database.external.existingSecret must be harbor-db-app")
    if v.get("caBundleSecretName") != "harbor-db-ca":
        errs.append("caBundleSecretName must be harbor-db-ca")
    return errs


def check_storage(v):
    st = v.get("persistence", {}).get("imageChartStorage", {})
    errs = []
    if st.get("type") != "s3":
        errs.append(f"imageChartStorage.type must be s3, got {st.get('type')}")
    if st.get("disableredirect") is not True:
        errs.append("imageChartStorage.disableredirect must be true")
    if st.get("s3", {}).get("existingSecret") != "harbor-s3":
        errs.append("imageChartStorage.s3.existingSecret must be harbor-s3")
    if v.get("jobservice", {}).get("jobLoggers") != ["database"]:
        errs.append("jobservice.jobLoggers must be [database]")
    return errs


def check_ha(v):
    return [f"{c}.replicas must be >= 2" for c in HA_COMPONENTS
            if (v.get(c, {}).get("replicas") or 0) < 2]


def check_toggles(v):
    errs = []
    if v.get("trivy", {}).get("enabled") is not False:
        errs.append("trivy.enabled must be false")
    if v.get("internalTLS", {}).get("enabled") is not False:
        errs.append("internalTLS.enabled must be false")
    metrics = v.get("metrics", {})
    if metrics.get("enabled") is not True:
        errs.append("metrics.enabled must be true")
    if metrics.get("serviceMonitor", {}).get("enabled") is not False:
        errs.append("metrics.serviceMonitor.enabled must be false (#8 overlay)")
    return errs


# Chart secrets that `helm template` would regenerate (lookup is empty), each from ESO.
COMPONENT_SECRETS = {
    "core.existingSecret": "harbor-core-secret",
    "core.secretName": "harbor-core-token",
    "core.existingXsrfSecret": "harbor-core-xsrf",
    "jobservice.existingSecret": "harbor-jobservice-secret",
    "registry.existingSecret": "harbor-registry-http",
    "registry.credentials.existingSecret": "harbor-registry-credentials",
}


def check_secrets(v):
    errs = []
    if v.get("existingSecretAdminPassword") != "harbor-admin":
        errs.append("existingSecretAdminPassword must be harbor-admin")
    if v.get("existingSecretAdminPasswordKey") != "HARBOR_ADMIN_PASSWORD":
        errs.append("existingSecretAdminPasswordKey must be HARBOR_ADMIN_PASSWORD")
    if v.get("existingSecretSecretKey") != "harbor-secret-key":
        errs.append("existingSecretSecretKey must be harbor-secret-key")
    for path, want in COMPONENT_SECRETS.items():
        got = v
        for k in path.split("."):
            got = got.get(k, {}) if isinstance(got, dict) else {}
        if got != want:
            errs.append(f"{path} must be {want}; the chart regenerates it on every render")
    for key in ("harborAdminPassword", "secretKey"):
        if key in v:
            errs.append(f"{key} must not be set; use the existing Secret")
    return errs


def check_auth(v):
    raw = v.get("core", {}).get("configureUserSettings")
    try:
        cfg = json.loads(raw)
    except (TypeError, ValueError):
        return ["core.configureUserSettings must be a JSON string"]
    errs = []
    if cfg.get("auth_mode") != "db_auth":
        errs.append(f"auth_mode must be db_auth in Phase 1, got {cfg.get('auth_mode')}")
    if cfg.get("self_registration") is not False:
        errs.append("self_registration must be false")
    if cfg.get("project_creation_restriction") != "adminonly":
        errs.append("project_creation_restriction must be adminonly")
    if not cfg.get("audit_log_forward_endpoint"):
        errs.append("audit_log_forward_endpoint must be set (#11)")
    return errs


def check_expose(v):
    ex = v.get("expose", {})
    errs = []
    if ex.get("type") != "ingress":
        errs.append("expose.type must be ingress")
    if ex.get("ingress", {}).get("hosts", {}).get("core") != "harbor.example.internal":
        errs.append("expose.ingress.hosts.core must be harbor.example.internal")
    if ex.get("tls", {}).get("certSource") != "secret":
        errs.append("expose.tls.certSource must be secret")
    if not str(v.get("externalURL", "")).startswith("https://"):
        errs.append("externalURL must use https")
    return errs


CHECKS = (check_images, check_database, check_storage, check_ha, check_toggles,
          check_secrets, check_auth, check_expose)


def errors(values):
    return [e for check in CHECKS for e in check(values)]


def leaks(text, docs=()):
    """Default secrets, private keys or inline Secret data in a file."""
    errs = [f"default secret {s!r} present" for s in DEFAULT_SECRETS if s in text]
    if PRIVATE_KEY.search(text):
        errs.append("private key present")
    for d in docs:
        if isinstance(d, dict) and d.get("kind") == "Secret" and (
                "data" in d or "stringData" in d):
            errs.append(f"Secret {d.get('metadata', {}).get('name')} has inline data")
    return errs
