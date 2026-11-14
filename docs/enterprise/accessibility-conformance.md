# Accessibility conformance summary (WCAG 2.1 AA / Section 508)

Scope: the Styx portal web UI (routed pages, admin settings sections, Styx shell). The remote desktop stream content is out of scope; it shows whatever the user runs.

Status: **draft**. The automated rows reflect the e2e scan. Manual rows stay as stated until the [checklist](accessibility-checklist.md) is completed; update this table with those results before the ATO package is submitted.

## Method

- Automated: axe-core via `@axe-core/playwright` with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`. Serious and critical violations fail the test. See [ADR-0081](adr/0081-accessibility-wcag-2-1-aa-axe-gate.md).
- Manual: keyboard-only and NVDA/Orca checks in the [checklist](accessibility-checklist.md).

## Evidence

- e2e spec: [`e2e/tests/a11y.spec.ts`](https://github.com/JMO-Labs/styx-portal/blob/enterprise/e2e/tests/a11y.spec.ts) scans every routed page and all admin settings sections; it writes `screenshots/a11y/report.json`.
- CI job: `a11y` in `.github/workflows/ci.yml`, added by [PR #392](https://github.com/JMO-Labs/styx-portal/pull/392) (link until that PR merges).

## Section 508

Section 508 (2018 refresh) incorporates WCAG 2.0 A and AA for web content (E205.4). WCAG 2.1 AA is a superset, so the table below covers both. Chapter 3 functional performance criteria are met through the same keyboard and screen-reader checks.

## Summary (selected criteria)

Levels: Supports, Partially Supports, Does not support. Currently no criterion is rated Does not support.

| Criterion | Name | Level | Conformance | Remarks |
|---|---|---|---|---|
| 1.1.1 | Non-text Content | A | Supports | Icons carry names; decorative images hidden. Axe `image-alt`, `svg-img-alt`, `button-name`. |
| 1.3.1 | Info and Relationships | A | Supports | Landmarks, headings, labels checked by axe; manual checklist covers reading order. |
| 1.3.5 | Identify Input Purpose | AA | Supports | Autocomplete tokens on login and setup fields (`autocomplete-valid`). |
| 1.4.3 | Contrast (Minimum) | AA | Supports | `color-contrast` runs in the e2e scan; jsdom cannot compute it (ADR-0081). |
| 1.4.4 | Resize Text | AA | Partially Supports | Layout holds to 200% in manual checks; not automated. |
| 1.4.10 | Reflow | AA | Partially Supports | Mobile audit e2e covers 320 px for routed pages; the remote desktop canvas does not reflow. |
| 1.4.11 | Non-text Contrast | AA | Partially Supports | Focus rings and controls reviewed manually; axe does not test it. |
| 2.1.1 | Keyboard | A | Partially Supports | Portal is keyboard operable. Keys inside the remote desktop go to the remote session by design. |
| 2.1.2 | No Keyboard Trap | A | Partially Supports | Portal chrome has no traps; the desktop stream captures keys while focused, with an escape shortcut documented in the checklist. |
| 2.4.1 | Bypass Blocks | A | Supports | `bypass`, `region` rules and landmarks. |
| 2.4.2 | Page Titled | A | Supports | `document-title` rule. |
| 2.4.3 | Focus Order | A | Supports | Manual tab-order check per page. |
| 2.4.7 | Focus Visible | AA | Supports | Manual check per page. |
| 3.1.1 | Language of Page | A | Supports | `html-has-lang`, `html-lang-valid`. |
| 3.3.1 | Error Identification | A | Supports | Errors tied to fields; live region checks in checklist. |
| 3.3.2 | Labels or Instructions | A | Supports | `label` rule. |
| 4.1.1 | Parsing | A | Supports | Obsolete in WCAG 2.2; duplicate ids caught by `duplicate-id*`. |
| 4.1.2 | Name, Role, Value | A | Supports | `aria-*`, `button-name`, `link-name` rules. |
| 4.1.3 | Status Messages | AA | Partially Supports | Toasts use live regions; confirmed manually with NVDA and Orca. |

Criteria not listed are not applicable (no audio, video, time limits or flashing content in the portal) or are covered by the rows above. The full criterion list is produced for the VPAT at submission.
