# ADR-0032: GPU tier later: SR-IOV-capable cards, no vGPU license

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D32
- Related controls: SA-4, SC-6

## Context

GPU funding is pending; per-user licensing is unacceptable.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Plan the GPU tier around SR-IOV-capable cards (Intel Flex class) with no vGPU licensing.

Owner amendment: CPU caps become final only after the D47 load test (ADR-0047). No GPU hardware is bought until the SR-IOV proof of concept passes.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- NVIDIA vGPU - per-user license fee.
- Whole-GPU passthrough - poor density.

## Consequences

Positive:

- No licensing fees; additive hardware.

Negative:

- Hardware/driver maturity must be validated.
- Selkies encoder support for the chosen cards is unverified.

Follow-up work:

- Proof of concept when funded (phase 6).
