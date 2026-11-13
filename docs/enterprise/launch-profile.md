# K8s launch profile

Each Kubernetes launch logs one line when the instance first reports running:

```
launch_phases digest_s=… apply_s=… ready_s=… total_s=…
```

No user, instance or image names appear in the line.

## Phases

| Phase | What it covers |
|---|---|
| `digest_s` | `resolve_digest()`: Harbor artifact lookup (5 s timeout). Cached per ref for `DIGEST_CACHE_S` (default 60). |
| `apply_s` | Server-side apply of the Deployment, Service and related objects. |
| `ready_s` | `start_container` (replicas 0 → 1) until the Deployment first reports running: scheduling, image pull, container start, readiness probe. |
| `total_s` | First phase start to first running status (includes DB, volume and network work between phases that is not separately timed). |

## Largest three (estimates from the code path, not measurements)

1. **`ready_s`**: node scheduling, image pull (large desktop image) and the readiness probe. Pre-pull reduces it; warm pools are out of scope (D46).
2. **`digest_s`** (cold): one synchronous Harbor call, up to 5 s on a slow or failing Harbor. Now cached for 60 s, so only the first launch per ref pays it. Errors are not cached.
3. **`apply_s`**: several sequential API round trips (one per object), typically tens to hundreds of ms.

Verify against real `launch_phases` lines before optimising further.
