# ADR-0069: Image supply chain implementation choices

- Status: Proposed
- Date: 2026-11-12
- Decision ID: D68
- Related controls: SI-2, SI-7, CM-14, RA-5
- Refines: ADR-0029, ADR-0030, ADR-0063

## Context

The supply chain issues (#145-#148) implemented the nightly build, Kyverno admission, launch-time digest resolution and the critical-CVE recycle. They left choices that no earlier ADR fixes. This records them for owner acceptance.

## Decision

1. **Nightly job gates the push.** `.github/workflows/images-nightly.yml` (02:17 UTC) builds with `no-cache` and `pull`, scans locally with Trivy (HIGH and CRITICAL, `ignore-unfixed: false`, `.trivyignore`), and only then pushes. A finding fails the job and nothing is pushed. After the push it creates a CycloneDX SBOM, then signs the digest and attests the SBOM with the OpenBao-held key (ADR-0063).
2. **Harbor digest resolution at launch.** `backend/app/services/image_digest.py` lists the repository's artifacts by push time and picks the newest one with a cosign accessory. It does not trust the tag, because a tag moves to an unsigned push while the older signed artifact stays valid. Only refs on the `HARBOR_URL` host are resolved. Running instances keep their digest.
3. **Resolution fails open to the configured ref.** An empty `HARBOR_URL`, a Harbor error or no signed artifact leaves the ref unchanged with a warning. Kyverno stays the enforcement point, so a blind spot cannot admit an unsigned image.
4. **Kyverno scope and allowlist.** `ClusterPolicy/styx-signed-images` (Enforce, `background: false`) applies to Pods in namespaces labelled `styx.io/desktop=true`. Two rules: images must match `harbor.example.internal/styx/*@sha256:*` (one allowlisted registry and project, digest required), and images under that prefix need a valid cosign signature for the configured public key. Tlog and SCT checks are off because signing is key-based and offline. Platform namespaces are out of scope.
5. **Recycle schedule.** `backend/app/services/cve_recycle.py` runs on the leader only every `CVE_RECYCLE_INTERVAL_S` (default 3600 s). It reads Harbor's vulnerability report for each running or idle instance's pinned digest. On the first CRITICAL it sets `recycle_deadline` to now plus `CVE_RECYCLE_GRACE_H` (default 24 h) and shows the user a notice. Later passes stop instances past the deadline. The deadline is not extended or cleared by later passes. Events `cve_warned` and `cve_recycled` are recorded.
6. **Recycle fails open.** A Harbor error or a non-Harbor image changes nothing: sessions are never stopped on a blind spot. The cost is that an outage longer than the grace period delays a recycle.

## Alternatives considered

- Resolve by tag: wrong after an unsigned push.
- Fail closed on Harbor errors at launch: users cannot launch during a Harbor outage; Kyverno already blocks unsigned images.
- Per-instance timers instead of a polling loop: more state, no gain at this scale.

## Consequences

Positive:

- Failed scans never reach Harbor; launches use the newest signed digest.
- At most about one hour plus the 24 h grace between a critical finding and a stop.

Negative:

- Hourly polling means a new critical CVE can wait up to one interval for its warning.
- A fail open recycle needs the Harbor alerts to be watched (see the runbook).

Follow-up work:

- Owner acceptance of this ADR.
- Harbor is not deployed; Trivy in Harbor stays off until Phase 3.
