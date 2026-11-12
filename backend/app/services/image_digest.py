"""Resolve repo:tag to the newest cosign-signed digest in Harbor (ADR-0030).

Called at launch only; running instances keep the digest they started with.
"""
import logging
from urllib.parse import quote

import httpx

from app.config import Settings

logger = logging.getLogger("styx-portal")


def digest_of(ref: str) -> str | None:
    return ref.split("@", 1)[1] if "@" in ref else None


def _is_signed(art: dict) -> bool:
    return any("cosign" in (a.get("type") or "") or "signature" in (a.get("type") or "")
               for a in art.get("accessories") or [])


def resolve_digest(ref: str, cfg: Settings | None = None,
                   client: httpx.Client | None = None) -> str:
    """Return repo@sha256:... for the newest signed artifact, else `ref` unchanged."""
    cfg = cfg or Settings()
    if not cfg.HARBOR_URL or "@" in ref:
        return ref
    path, _, tag = ref.rpartition(":")
    if "/" not in path or "/" in tag:  # no tag (colon was a registry port)
        path, tag = ref, "latest"
    parts = path.split("/")
    if len(parts) < 3:
        return ref
    project, repo = parts[1], "/".join(parts[2:])
    url = (f"{cfg.HARBOR_URL.rstrip('/')}/api/v2.0/projects/{project}/repositories/"
           f"{quote(quote(repo, safe=''), safe='')}/artifacts")
    auth = (cfg.HARBOR_USER, cfg.HARBOR_PASSWORD) if cfg.HARBOR_USER else None
    own = client is None
    client = client or httpx.Client(timeout=5.0)
    try:
        r = client.get(url, params={"q": f"tags={tag}", "with_accessory": "true",
                                    "sort": "-push_time", "page_size": 50}, auth=auth)
        r.raise_for_status()
        arts = [a for a in r.json() if _is_signed(a)]
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("harbor digest lookup failed for %s (%s); using configured ref",
                       ref, e.__class__.__name__)
        return ref
    finally:
        if own:
            client.close()
    if not arts:
        logger.warning("harbor has no signed artifact for %s; using configured ref", ref)
        return ref
    newest = max(arts, key=lambda a: a.get("push_time") or "")
    return f"{path}@{newest['digest']}"
