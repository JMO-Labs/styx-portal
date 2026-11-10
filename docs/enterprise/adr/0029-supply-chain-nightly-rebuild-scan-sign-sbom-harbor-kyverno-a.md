# ADR-0029: Supply chain: nightly rebuild, scan, sign, SBOM, Harbor, Kyverno admission

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D29
- Related controls: SR-3, SR-4, SI-2, SI-7, RA-5, CM-7

## Context

Security updates must apply automatically and only trusted images may run.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Rebuild nightly, scan with Trivy, sign with cosign and produce an SBOM, store in Harbor, and have Kyverno admit only signed, allowlisted images.

Owner amendment: high-severity CVEs have a fix deadline of 7 days.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Manual patch cycles - slow.
- Registry without admission control - unsigned images could run.

## Consequences

Positive:

- Automatic secure updates; verifiable provenance.

Negative:

- Harbor and Kyverno become dependencies for launches.
- Scan false positives need triage.

Follow-up work:

- Define vulnerability SLAs (see D30) and key custody for cosign in phase 3.
- Phase 3 ADR: cosign key custody (OpenBao, CI-only) and the medium/low CVE fix deadlines.

## Implementation note (Phase 1, #5)

Phase 1 covers the Harbor part only, as IaC in `deploy/enterprise/harbor/` (not deployed). It uses the upstream `goharbor/harbor` chart 1.19.4 (Harbor 2.15.4) with a dedicated CNPG cluster `harbor-db`, Ceph RGW S3 blobs, chart-internal Valkey, ESO secrets from OpenBao, `db_auth` with only `admin` and robot accounts, and internal-only exposure through Traefik. Trivy, cosign, SBOM and Kyverno admission are later phases. Runbook: docs/operate/harbor-enterprise.md.
