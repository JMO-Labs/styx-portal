# ADR-0042: Secrets: OpenBao with External Secrets, auto-unseal and offline escrow

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D42
- Related controls: SC-12, SC-13, SC-28, IA-5, SC-17

## Context

App secrets, PKI, backup keys and break-glass escrow need a secrets manager without license ambiguity.

Source: docs/enterprise/design.md section 5.

## Decision

Use OpenBao for app secrets (delivered by External Secrets), internal PKI, backup keys and break-glass escrow. Auto-unseal with a TPM or key-file on the control plane, so restarts need no humans. Shamir recovery keys are held by 3 people for disaster only. Break-glass credentials and backup encryption keys are also escrowed offline, sealed in the safe. DB credentials are CNPG-managed roles, not Vault dynamic leases (ADR-0056).

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- HashiCorp Vault - BSL license ambiguity.
- Kubernetes secrets alone - no rotation/PKI.

## Consequences

Positive:

- Open-source with MPL license; central key management.

Negative:

- Auto-unseal key material on the control plane must be protected (SC-12).
- Recovery procedure depends on 3 people (disaster only).
- Project maturity relative to Vault.

Follow-up work:

- Auto-unseal design, rotation policy and escrow custody in phase 1.
- Auto-unseal is a `seal "static"` key file, escrowed in both escrow sets (C1, #14).
- Static seal implemented in #4 (`deploy/enterprise/openbao/`, runbook `runbooks/openbao.md`), recovery threshold 2-of-3 (owner to confirm with escrow custody).
