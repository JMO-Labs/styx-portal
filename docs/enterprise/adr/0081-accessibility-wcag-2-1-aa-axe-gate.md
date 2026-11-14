# ADR-0081: Accessibility: WCAG 2.1 AA with an axe gate

- Status: Proposed
- Date: 2026-11-14
- Decision ID: D80
- Related controls: Section 508, WCAG 2.1 AA, SA-11

## Context

The ATO package needs evidence of Section 508 conformance. Section 508 points at WCAG 2.0 AA; we target WCAG 2.1 AA. Results are in the [conformance summary](../accessibility-conformance.md) and the [manual checklist](../accessibility-checklist.md).

## Decision

- **Tags.** The e2e scan (`e2e/tests/a11y.spec.ts`) runs axe-core with `wcag2a`, `wcag2aa`, `wcag21a` and `wcag21aa`. No best-practice or experimental tags, so findings map to a criterion.
- **Gate.** Violations with impact `serious` or `critical` fail the test. `moderate` and `minor` are written to `screenshots/a11y/report.json` and reviewed, not blocking.
- **Contrast in e2e, not jsdom.** The `color-contrast` rule needs real layout and computed styles. jsdom has neither, so unit tests skip it and the Playwright scan in a real browser checks it.
- **Coverage.** Every routed page plus all admin settings sections and `/shell.html`, with API calls mocked for stable data.
- **CI.** An `a11y` job in `.github/workflows/ci.yml` runs the spec.
- **Manual checks.** Axe cannot judge focus order, traps or announcement quality, so keyboard and NVDA/Orca checks live in the checklist and are repeated before each ATO submission.

## Alternatives considered

- Gate on all impacts: rejected, moderate findings are often false positives and would block unrelated changes.
- Check contrast in jsdom unit tests: rejected, the results would be wrong or empty.
- Manual testing only: rejected, regressions go unseen between audits.

## Consequences

- New pages must be added to the spec or they are not scanned.
- Moderate and minor findings need a periodic look at the report.
- Manual results can go stale; the checklist carries a sign-off table.
