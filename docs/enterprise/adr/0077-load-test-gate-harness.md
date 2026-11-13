# ADR-0077: Load-test gate harness

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D76
- Related controls: CA-2, CA-7, SA-11, SC-5
- Refines: ADR-0047, ADR-0009, ADR-0031

## Context

ADR-0047 (D47) gates the all-users rollout on a 200-session synthetic soak. This records how the harness implements that gate and what is proven where. The 200-session run needs real hardware and is an owner action: [runbooks/load-test-gate.md](../runbooks/load-test-gate.md).

## Decision

1. **Thresholds are the D47 values, fixed in code.** `e2e/stream-ab/gate.py` (`DEFAULTS`): launch p95 < 10 s with zero failed launches, stream RTT p95 < 80 ms (client-side presented latency), zero drops. Any missed metric, or no data, is a fail. The soak window for the gate is 240 minutes.
2. **One entry point.** `e2e/stream-ab/soak.py --sessions N --minutes M --probe stream|http` launches N sessions through the portal API (`soak_fleet.py`, via `fleet.py`), probes all in parallel (`session_probe.py`), evaluates the gate and writes `results/gate-<stamp>.{json,md}`. Exit 0 on pass, 1 on fail. Sessions are always torn down, including on SIGTERM or interrupt.
3. **Two probes, one per purpose.** `stream` drives a real browser stream (`latency.mjs` rounds) and measures RTT; a failed round or a missed sample is a drop. This is the only probe that can pass the gate. `http` is a timed GET once a second with no browser: it proves the harness plumbing (launch, parallel probe, gate, report, teardown) cheaply, but does not measure stream latency and is not gate evidence.
4. **Fake-portal kind smoke.** `scripts/kind/30-loadtest-smoke.sh` (CI job `kind-spike`) runs `soak.py --sessions 3 --minutes 1 --probe http` against `test/kind/fake-portal.py` in kind and requires verdict `pass` and a report. It guards the harness against regressions without hardware. It says nothing about capacity.
5. **The 200-session run is not in CI.** It needs the production-like cluster (ADR-0006, 0009), takes 4 h plus launch time, and is run by the owner per the runbook. Its report is the D47 evidence attached to the rollout decision.

## Alternatives considered

- HTTP probe for the gate: cheap, but blind to encode, network and client latency; cannot back the 80 ms stream claim.
- Stream probe in CI smoke: needs a browser and a real Selkies session per run; too heavy for kind.
- Gate thresholds as CLI flags: invites tuning to pass; `gate.evaluate` accepts overrides only from code and tests.

## Consequences

Positive:

- The same code path is exercised in CI (3 sessions, `http`) and at gate time (200 sessions, `stream`).
- The report is machine-readable (JSON) and human-readable (markdown).

Negative:

- A green kind smoke is not a capacity statement; only the owner run is.
- The stream probe launches a browser per session on the load generator, which must be sized for it (see runbook).
