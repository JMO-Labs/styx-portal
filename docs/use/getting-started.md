# Getting started

You will sign in, optionally add a second factor, and find your way around the portal.

**Prerequisites:** the portal address (for example `https://styx.example.com`) and either an invite link from an admin or an SSO account.

## The ways in

![Sign-in options: invite link, password or SSO, then the dashboard](../assets/diagrams/use-getting-started-1-light.svg#only-light)
![Sign-in options: invite link, password or SSO, then the dashboard](../assets/diagrams/use-getting-started-1-dark.svg#only-dark)

## Accept an invite

1. Open the invite link an admin sent you. It is single-use and valid for 72 hours.
2. Choose a username and password. The form shows the password rules the admin configured (minimum length, required character classes) and a strength meter.
3. You are signed in.

## Sign in

![Styx sign-in page](../assets/screens/ui-login.png)

- **Password:** enter your username and password.
- **SSO:** if the admin configured a provider (Google, GitHub, Authentik, Keycloak or any OIDC/OAuth2 provider), its button appears on the sign-in page. SSO only works for people who already have an account or an open invite whose email matches the provider's verified email.
- **Session expiry:** a prompt warns you shortly before your session ends. Choose **Stay signed in** to refresh it.

!!! note "Repeated failures lock the account"
    Too many wrong passwords lock the account for a while, and too many failures from one address ban that address. Ask an admin to **Unlock** you if you cannot wait. See [Security](../operate/security.md).

## Add a sign-in card (2FA)

A sign-in card is a printed grid of codes used as a second step after your password.

1. Open **My account → Sign-in card** (the **Settings** tab, or **Admin** for admins) and choose **Generate card**. Enter your account password.
2. The 10 × 5 card (columns A–E, rows 1–10) is shown **once**. Download the PNG or print it.
3. Enter the cell the portal asks for (for example `C7`) to activate the card.

From then on, password sign-in asks for three random cells.

![Sign-in card prompt](../assets/screens/ui-login-2fa.png)

- **Lost card:** if you can still sign in, **Regenerate** (needs your password) or **Remove** it. If you cannot, ask an admin to **Reset sign-in card** for you.
- **Session length:** a card sign-in is a session-only login. It ends when you close the browser and after a fixed maximum age (default 12 hours, set by the admin), even in proxied apps and workstations.
- A wrong current password on **Change password** counts as a failed sign-in.

## Link an SSO account

Under **My account → Connected accounts** you can link or unlink a provider to your account. Linking always needs a verified email. You cannot unlink your only way to sign in. Admins link providers while signed in; SSO sign-in never auto-links to an admin account.

## Find your way around

| Place | What it is |
|---|---|
| **Home → Recent** | Live thumbnails of what you opened lately; click one to resume |
| **Home → Desktops** | Workstations you may use, with live previews and **Connect** |
| **Home → Apps** | Tiles for the proxied apps your groups allow |
| **Home → Containers** | Your containerized desktops, plus the **New container** button |
| **Account menu** (top right) | The **Opening** preference (new tab, this tab or ask) for desktops and apps |
| **Settings** tab | Your account: sign-in card, connected accounts, profiles. Admins see this tab as **Admin**, with the portal's own sections too |
Admins also see a status panel pinned to the right of Home (CPU, memory, disk). It collapses to a strip.

![Home dashboard](../assets/screens/ui-dashboard-light.png)

!!! note "Coming soon: phone layout (PR #106)"
    A mobile layout pass adds a one-line header with **Log out** and the theme toggle in the account menu, a compact Home, full-screen drawers and larger touch targets. The status panel is hidden on narrow screens.

Next: [Desktops](desktops.md) or [Workstations](workstations.md).
