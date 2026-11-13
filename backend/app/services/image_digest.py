"""Resolve repo:tag to the newest cosign-signed digest in Harbor (ADR-0030).

Called at launch only; running instances keep the digest they started with.
Candidates are the repo's artifacts by push time, not only the current tag
holder: in Harbor a tag sits on one artifact, so once it moves to an unsigned
push the older signed artifact is untagged but still the one to run.
"""
import logging
import time
from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings

logger = logging.getLogger("styx-portal")

_cache: dict[str, tuple[float, str]] = {}  # ref -> (expires monotonic, resolved)


def clear_cache() -> None:
    _cache.clear()


def digest_of(ref: str) -> str | None:
    return ref.split("@", 1)[1] if "@" in ref else None


def _is_signed(art) -> bool:
    if not isinstance(art, dict):
        return False
    return any("cosign" in (a.get("type") or "") or "signature" in (a.get("type") or "")
               for a in art.get("accessories") or [] if isinstance(a, dict))


def _split(ref: str, harbor_host: str) -> tuple[str, str, str] | None:
    """(path, project, repo) for a ref hosted on Harbor, else None."""
    path, _, tag = ref.rpartition(":")
    if "/" not in path or "/" in tag:  # no tag (colon was a registry port)
        path = ref
    parts = path.split("/")
    if len(parts) < 3 or parts[0].lower() != harbor_host:
        return None
    return path, parts[1], "/".join(parts[2:])


def resolve_digest(ref: str, cfg: Settings | None = None,
                   client: httpx.Client | None = None) -> str:
    """Return repo@sha256:... for the newest signed artifact, else `ref` unchanged."""
    cfg = cfg or Settings()
    if not cfg.HARBOR_URL or "@" in ref:
        return ref
    split = _split(ref, urlsplit(cfg.HARBOR_URL).netloc.lower())
    if not split:  # not a Harbor ref (e.g. ghcr.io): never mix registries
        return ref
    hit = _cache.get(ref)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    path, project, repo = split
    url = (f"{cfg.HARBOR_URL.rstrip('/')}/api/v2.0/projects/{project}/repositories/"
           f"{quote(quote(repo, safe=''), safe='')}/artifacts")
    auth = (cfg.HARBOR_USER, cfg.HARBOR_PASSWORD) if cfg.HARBOR_USER else None
    own = client is None
    client = client or httpx.Client(timeout=5.0)
    try:
        r = client.get(url, params={"with_accessory": "true", "sort": "-push_time",
                                    "page_size": 50}, auth=auth)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("harbor digest lookup failed for %s (%s); using configured ref",
                       ref, e.__class__.__name__)
        return ref
    finally:
        if own:
            client.close()
    arts = [a for a in data if _is_signed(a) and a.get("digest")] \
        if isinstance(data, list) else []
    if not arts:
        logger.warning("harbor has no signed artifact for %s; using configured ref", ref)
        return ref
    newest = max(arts, key=lambda a: a.get("push_time") or "")
    resolved = f"{path}@{newest['digest']}"
    if cfg.DIGEST_CACHE_S > 0:  # only successes are cached; errors/unsigned retry
        _cache[ref] = (time.monotonic() + cfg.DIGEST_CACHE_S, resolved)
    return resolved
