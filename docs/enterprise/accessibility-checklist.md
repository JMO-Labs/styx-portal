# Accessibility checklist (manual)

Manual keyboard-only and screen-reader checks that complement the automated axe scan ([conformance summary](accessibility-conformance.md), [ADR-0081](adr/0081-accessibility-wcag-2-1-aa-axe-gate.md)). Axe finds roughly a third of issues; this list covers the rest.

## How to run

- Build under test: the release candidate, enterprise profile, signed in as an admin and as a plain user.
- Keyboard: unplug or ignore the mouse. Tab, Shift+Tab, Enter, Space, Arrow keys, Escape only.
- Screen readers: NVDA on Windows with Firefox or Chrome; Orca on Linux with Firefox.
- Record the result per row: Pass/Fail/N/A (use Pending until tested). Put the tester, date, build and any defect link in Notes.

Result legend: **Pass** meets the check, **Fail** does not (open a defect, link it in Notes), **N/A** the page has no such element, **Pending** not yet run.

## Keyboard-only

### `/setup` (Setup)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/login` (Login)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/accept-invite/<token>` (Accept invite)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/change-password` (Change password)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/connecting` (Connecting)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/` (Desktop (home))

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `settings:* (15 admin sections)` (Admin settings)

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

### `/shell.html` (Styx shell (frame, edge tab, dock))

| Check | What to verify | Result | Notes |
|---|---|---|---|
| Tab order | Tab order follows visual order; no positive tabindex | Pending | |
| Focus visible | Every focusable control shows a visible focus indicator | Pending | |
| No keyboard trap | Focus can always leave the page or component with keys alone | Pending | |
| Skip | Skip link or landmark jump reaches main content | Pending | |
| Escape | Escape closes menus, popovers and dialogs and returns focus to the trigger | Pending | |
| Dialogs | Focus moves into a dialog, is contained, and is restored on close | Pending | |

## Screen reader (NVDA, Orca)

### `/setup` (Setup)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/login` (Login)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/accept-invite/<token>` (Accept invite)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/change-password` (Change password)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/connecting` (Connecting)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/` (Desktop (home))

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `settings:* (15 admin sections)` (Admin settings)

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

### `/shell.html` (Styx shell (frame, edge tab, dock))

| Check | What to verify | NVDA | Orca | Notes |
|---|---|---|---|---|
| Landmarks | header, nav, main are announced once and named when repeated | Pending | Pending | |
| Headings | One h1; levels do not skip | Pending | Pending | |
| Accessible names | Buttons, links, inputs and icons have a name and role; errors are tied to fields | Pending | Pending | |
| Live regions | Toasts, status and errors are announced without moving focus | Pending | Pending | |

## Sign-off

| Tester | Date | Build | Scope | Outcome |
|---|---|---|---|---|
| | | | | |
