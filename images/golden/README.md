# Golden images (ADR-0028)

Each image inherits the enterprise base (`ARG BASE_IMAGE=styx-enterprise-base:latest`) and ends as `USER 1000:1000`.

| Image | Adds |
|---|---|
| browser-only | Firefox (Mozilla apt deb, not snap); policy homepage `https://portal.office365.us` (M365 GCC High) |
| base-office | Firefox + same policy, Evince PDF viewer |
| developer | git, xfce4-terminal, VS Code (Microsoft apt repo) |

Build: `docker build --build-arg BASE_IMAGE=... images/golden/<name>`.
