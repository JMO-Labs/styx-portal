# Desktops

A **desktop** (an *instance*) is a containerized Linux desktop you launch from a template and use in a browser tab. Your files live in a persistent volume, so they survive stop, restart and rebuild.

**Prerequisites:** a signed-in account. Admins may cap how many desktops you can run at once (default 3).

## Launch one

![New container drawer](../assets/screens/ui-desktop-launch.png)

1. On **Home**, press **New container** in the **Containers** section. A drawer opens.
2. Pick what to run:
    - **Your setups** launch in one click with their saved settings (**Launch**), or open for tweaks (**Customise**). Admins create shared setups; see [Templates and instances](../operate/templates-instances.md).
    - The **LinuxServer catalog** lists Selkies desktop images. Search by name; categories filter the list.
    - For another image, type `registry/image:tag` in the custom field.
3. Choose a size, name and idle behaviour, then **Launch**. Options include **Keep my profile between sessions**, **Use GPU** and **Save as a setup for one-click launch**.
4. The portal pulls the image if needed, showing progress, then starts the container.
5. Press **Connect** on its row. The desktop opens at `/desktop/<name>`, in a new tab or this tab as set by the **Opening** preference in the account menu.

Each row shows a status badge, a **Start**, **Resume** or **Connect** button, and a **⋯** menu with **Details** (full controls in a side sheet) and **Stop**.

![Containers on Home](../assets/screens/ui-desktops.png)

!!! info "Images must be Selkies-based"
    Only [linuxserver.io `baseimage-selkies`](https://www.linuxserver.io/) images (or images derived from them) stream. A plain image starts, but shows 502 or SSL errors, a blank thumbnail and unreliable idle detection. See [Templates and instances](../operate/templates-instances.md).

## Keep it awake: idle and "I'm here"

Desktops stop themselves when nobody uses them, to free the host.

- After the template's **idle timeout** (14 minutes on Blank and Gaming, 60 on XFCE and Developer, 120 on Workstation) with no activity, the desktop turns **idle**.
- While idle, the desktop page shows a banner **"Pausing soon due to inactivity"** with an **I'm here** button. Press it, or use the desktop, to cancel the stop.
- If nothing happens for the **grace period** (1 to 15 minutes depending on the template), the container is stopped. Stopped desktops keep their data and can be started again.

What counts as activity: keyboard, mouse and touch input in the desktop tab, or visible motion on screen while the tab is in view. Audio-only playback is not detected, so press **Keep awake** in **Details** for long music or downloads. Templates can also be set to never time out.

Defaults are 14 minutes idle, then a 1 minute grace period before the action (stop). Some bundled templates use longer timeouts (for example 60 minutes for the XFCE and Dev desktops, 120 for Workstation); check the template's session settings.

### Desktop states

Every desktop is in one of these states. Pause is a manual action; idle and the automatic stop come from the idle timeout.

![Desktop instance states: pulling, starting, running, idle, paused, stopped and error](../assets/diagrams/use-desktops-1-light.svg#only-light)
![Desktop instance states: pulling, starting, running, idle, paused, stopped and error](../assets/diagrams/use-desktops-1-dark.svg#only-dark)

## Stop, restart, delete

From **Details** or the row's **⋯** menu you can stop, start, restart, recreate (new container, same volumes) or delete a desktop. Deleting removes the container and the instance's own volumes. The instance's own volumes are removed with it. A saved per-template profile is kept unless you tick the delete-profile option; you can also reset it under **My account → My profiles** (the **Settings** tab, or **Admin** for admins). A profile still used by another instance is never deleted.

## Next

- [Workstations](workstations.md) for streaming a real machine.
- [Troubleshooting](troubleshooting.md).
