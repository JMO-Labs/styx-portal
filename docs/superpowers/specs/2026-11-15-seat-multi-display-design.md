# Seat multi-display (extended desktop) design

Date: 2026-11-15. Status: draft for approval. Spike: GAME-01, 2026-11-15 (memory `seat-multi-display`).

## Intent

A user on a GNOME seat presses Selkies' **Add Screen**, a second browser window opens, and the
remote GNOME desktop extends onto it: its own picture at that window's size, placed where the user
put it (above, left, ...), with the pointer and window drags crossing the shared edge the way two
physical monitors do. The user keeps their real GNOME desktop; we do not switch to upstream's
built-in desktop.

Long-term goal: the screen-growing part lives **upstream in pixelflux** as a general feature
("a second display on a host-capture session"), so Styx carries little of its own and benefits
from upstream fixes. Styx contributes it.

## What the spike proved (and what it cost)

The spike works end to end on GAME-01 (stacked layout, correct clicks and drags). It needed four
pieces, two of which this design removes:

| Spike piece | Fate |
|---|---|
| pixelflux: capacity counts screens not views; screen reposition moves its views' host layout | Kept. Upstream PR in progress (bug fixes, general) |
| pixelflux: layout written to a file for a Styx helper | **Replaced** by pixelflux arranging Mutter itself |
| `seat_portal.py`: always-present monitor 2, layout watcher, Selkies restart after resize | **Replaced** by portal virtual sources |
| Gateway: `#displayN` window bypasses the one-tab seat hold | Kept, productionized |

Spike costs this design removes: a monitor nobody sees (windows land there), a 2-3 s Selkies
restart on every size change of the second window, two screens hardcoded.

## Key facts (verified 2026-11-15)

- Selkies only offers Add Screen in host capture when pixelflux's `output_capacity()` (host
  `wl_output` count) is at least 2 (`webrtc_mode._second_screen_availability`; websockets mode
  mirrors it). pixelflux then maps display ids to host outputs by rank and pairs portal streams
  with outputs by position.
- The ScreenCast portal has a **virtual** source type (`types` bit 4). `xdg-desktop-portal-gnome`
  implements it (`SCREEN_CAST_SOURCE_TYPE_VIRTUAL` -> Mutter `RecordVirtual`); KDE's portal has an
  equivalent. A virtual monitor exists exactly as long as its stream, and its size follows the
  stream consumer's negotiated format.
- Mutter 50 gates `org.gnome.Mutter.ScreenCast` only by "caller created the session"
  (`check_permission`); `org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig` arranges monitors.
  A new virtual monitor is not placed in the layout until a config is applied.
- Mutter stalls (never closes) a `RecordMonitor` stream whose monitor is resized; pixelflux does
  not reopen a closed portal session. A display whose stream IS the virtual monitor's own stream
  has no `RecordMonitor` in between, so in-place resize by consumer renegotiation is expected to
  work (the agent's `Monitor.resize` does exactly this for the primary). **To be proven.**
- Upstream precedent: `kdeclient.rs` grows/removes/arranges screens for a nested KWin through
  KWin's virtual-output API. There is no host-capture counterpart yet.

## Goals

1. Add Screen works on every GNOME seat (agent seat mode), WebRTC and WebSockets.
2. Monitor 2 exists only while the second window is open; closing it gives the space back and
   GNOME moves its windows to the primary.
3. Resizing or moving the second window resizes/re-places monitor 2 without restarting Selkies.
4. Placement follows Selkies' layout (the side the user picked) on GNOME.
5. pixelflux changes are upstreamable: detected, never default; general (GNOME, and KDE where its
   portal serves virtual sources); no Styx-specific contracts.
6. Single-screen sessions behave exactly as today.

## Non-goals

- More than one extra screen (Selkies itself offers only `display2`).
- X11 mirror-mode seats (separate, upstream X11 path).
- Physical-monitor workstations sharing their real desktop (mirror mode).
- Fixing the primary's own resize restart (separate work; same root cause, noted below).

## Anti-goals (failure even if it "works")

- A monitor exists that no window shows.
- Any extra restart or reconnect for users who never press Add Screen.
- A second window can take over or evict the owner's session, or bypass auth.

## Approaches considered

| | How | Verdict |
|---|---|---|
| A. Always-on monitor 2 | Seat creates it permanently | Rejected: invisible screen |
| B. Styx sidebar switch | Agent adds/removes monitor 2 + Selkies restart, then Add Screen appears | Rejected for now: Styx-only, restart per resize |
| **C. pixelflux grows screens through the portal** | pixelflux opens a virtual source per extra display, arranges via Mutter DisplayConfig | **Chosen** (user, 2026-11-15): general, upstreamable, removes the restarts and the invisible screen |

## Design

### pixelflux (fork `JMO-Labs/pixelflux`, then upstream to `selkies-project/selkies` `crates/pixelflux`)

1. **Capacity.** In host capture, when the live portal's `AvailableSourceTypes` includes virtual,
   `output_capacity()` reports host outputs **+ 1** (one growable screen, matching Selkies' single
   `display2`). Selkies needs no change: it already offers Add Screen when capacity >= 2.
2. **Grow.** A display created beyond the host's real outputs (`create_output_on` in host mode)
   opens a **second portal ScreenCast session** with `types = virtual`, consumes its stream at the
   display's requested size, and backs that display with it. Rank mapping treats it as the next
   output. Closing the display closes that session; the host removes the monitor.
3. **Size.** A size change of a grown display renegotiates its own PipeWire consumer format (no new
   session). Never touches the primary's stream.
4. **Arrange.** When the host lacks `zwlr_output_manager_v1` but exposes
   `org.gnome.Mutter.DisplayConfig` on the session bus, `apply_layout` applies Selkies' union
   layout with `ApplyMonitorsConfig` (method temporary; each monitor's current mode and scale;
   positions in logical px = union px / scale; normalized to start at 0,0; primary flag on rank
   0). A refusal is logged and capture follows the host, as today. Grown and physical outputs are
   arranged alike. This replaces the spike's layout file.
5. **Input.** Pointer and keys keep going through the primary session's RemoteDesktop/libei. With
   libei, absolute motion is in the compositor's global logical space (stream position + point),
   so a second session's monitor is reachable once arranged. **To be proven** (risk 1).
6. **Fixes already made** (separate upstream PR): capacity counts screens not views; screen
   reposition moves its views' host layout entries.

### Styx agent

1. **Seat portal backend** (`seat_portal.py`): advertise virtual in `AvailableSourceTypes`; on a
   session whose `SelectSources` asked for virtual, `Start` calls Mutter `RecordVirtual`
   (`is-platform`, cursor metadata) and returns that stream with its position/size. No consent
   dialog (our backend). Remove all spike code: always-present monitor 2, layout-file watcher,
   kill-flag restart. Keep per-stream routing of `NotifyPointerMotionAbsolute` (node -> stream
   path) for the Notify fallback.
2. **Gateway** (`gateway_html.py`, `gateway_webrtc.py`, and the websockets path in `gateway.py`):
   a page whose fragment starts `#display` tags its stream socket `styx_sub=1` and sends no refit
   beacons; the gateway proxies it after the normal auth/origin checks, **only while the owner
   session is live** (a sub-display cannot exist alone or take the seat), with no seat hold, no
   viewer record, no idle expiry of its own; it closes when the owner session ends. The gateway
   does no stream routing: each window opens its own signaling socket and Selkies binds it to
   `display2` from the page's own hello; the gateway only proxies bytes (as the spike did).
3. **Engine** (`engine.py`): `--second-screen=true` on seat mode (still `false` for mirror mode).
   No layout-file env var.
4. **Wheelhouse**: patched pixelflux `2.2.2+styx7` via `EXTRA_WHEELS` until an upstream release
   carries the feature; `docs/build/upstream.md` lists the carrier and its upstream PR.
5. **Version**: agent minor bump (new feature); CHANGELOG entry; docs: `docs/use/` short
   "Two screens" section, `docs/build/agent.md` seat-portal + gateway notes.

### Order of work

1. Prove risks 1-3 on GAME-01 with the smallest pixelflux change (grow via virtual session +
   DisplayConfig arrange) before polishing anything.
2. pixelflux feature with tests, in the fork; wheel `styx7`.
3. Styx agent changes with tests; remove spike code; live verify on GAME-01; PR.
4. Upstream pixelflux PR (after the bug-fix PR lands or alongside it).

## Risks / open questions for the builder

1. **Input to a second session's monitor.** Does Mutter's EIS (primary RemoteDesktop session)
   cover a virtual monitor created by another ScreenCast session? If not: pair the virtual
   session with the RemoteDesktop session (`remote-desktop-session-id`, as `seat_portal` already
   does for the primary) in our backend, and in pixelflux open the grown screen inside the
   primary's RemoteDesktop session if the portal allows it.
2. **In-place resize of a virtual stream** without stalls. If renegotiation stalls too, fall back
   to closing and reopening the grown display's own session (still no Selkies restart).
3. **Second portal session on stock GNOME** (not our backend): one more consent dialog unless a
   restore token covers virtual sources. Acceptable upstream if documented; not a Styx concern.
4. KDE: untested; the design only relies on the portal standard plus an optional arranger.
   Styx ships GNOME seats only; the upstream PR states KDE as untested (designer's call).

Risks 1-3 are answered by step 1 of the order of work, before any polish; the fallbacks named
under 1 and 2 are the plan if they fail.

## Spike results (2026-11-15, from the GAME-01 spike and source reads)

1. **Input reaches a virtual monitor from another session: yes.** In the spike, monitor 2 was a
   `RecordVirtual` in its own unpaired ScreenCast session, and pixelflux's input (libei through
   the primary's RemoteDesktop session) clicked and dragged on it correctly once arranged. The
   grown display needs no input of its own.
2. **In-place resize: yes, by reconnecting the consumer to the same node.** Reconnecting a
   PipeWire consumer to a virtual monitor's node with new size caps resizes that monitor in place
   in about 100 ms (`seat_portal.Monitor.resize`, used live for the primary). Only a *separate*
   `RecordMonitor` stream of a resized monitor stalls. pixelflux consumes the grown display's
   virtual stream directly, so it resizes by reconnecting its own consumer at the new size.
3. **Stock GNOME consent:** `xdg-desktop-portal-gnome` lists "Virtual Monitor" in the share
   dialog and serializes virtual sources into the restore token, so one dialog the first time,
   none after. Our seat backend shows none.

## Designer's calls (settled without the user)

- **Arrangement on Mutter is required, not optional.** Mutter leaves a new virtual monitor out of
  the layout until a config is applied, so on a Mutter host without a working `DisplayConfig`
  pixelflux does not offer the extra screen (capacity stays at the real output count). On hosts
  with no Mutter, the host's own placement is used.
- **Capacity headroom is exactly one** (Selkies offers only `display2`).
- **The gateway proxies, never routes** (see Styx agent, item 2).

## Left to the builder

Module layout inside pixelflux (a `mutterclient.rs` beside `kdeclient.rs` is the natural shape);
test strategy for portal/D-Bus pieces (fake portal on a private bus, as upstream's portal tests
do); exact gateway test cases; debounce of rapid second-window resizes if renegotiation is costly.

## Addendum B: capture screen 1 from its own virtual stream (2026-11-15, user-approved direction)

**Problem found live.** Screen 1 was captured with a `RecordMonitor` stream. Mutter 50.1 closes a
`RecordMonitor` stream whenever its monitor's rectangle changes, position included
(`meta-screen-cast-monitor-stream.c` `update_monitor`). Placing screen 2 above or left must move
screen 1 (Mutter refuses negative positions: "Invalid logical monitor position"), so screen 1
froze. In a RemoteDesktop-paired session the closed stream does not close the session, so nobody
noticed. A virtual monitor's own stream survives moves.

**Decision (user: "B is the right call").** Screen 1 is captured from the seat's virtual monitor's
own stream. No `RecordMonitor` anywhere.

**Spike facts (GAME-01).**
- A second reader on a virtual stream takes over the monitor's size if its caps differ (800x600 ->
  1280x720). With caps at exactly the current size, the size holds and the stream survives moves.
- The agent kills selkies before every resize (`styx_agent` refit loop), so pixelflux is never
  attached while the size changes. The agent's sizing consumer stays the size owner.

**Design.**
1. `seat_portal.Monitor` creates the seat's RemoteDesktop session, a ScreenCast session paired to
   it, and the virtual monitor (`RecordVirtual`) inside it, for the seat's life. Its fakesink
   consumer keeps sizing the monitor exactly as today (resize request file, ready file).
2. Portal sessions borrow that Mutter session; they never create or stop one:
   - Primary Start returns the monitor's existing node (source type virtual) with position/size.
   - A virtual (screen 2) Start records `RecordVirtual` in that same ScreenCast session; Close
     stops just that stream (as now).
   - `ConnectToEIS`, `Notify*`, and the clipboard use the seat's RemoteDesktop session. EIS regions
     then cover screen 1 and screen 2.
   - Mutter closing the seat session still ends the helper (heal path, unchanged).
3. pixelflux: a host-capture portal stream that is not a grown display is consumed at exactly the
   size the portal announced (`exact_size`), so it never resizes the host's monitor.

**Unchanged.** Agent refit chain, HiDPI scale path, gateway, Selkies.

**Costs if wrong.** If Mutter refuses a second `ConnectToEIS` on one RemoteDesktop session after a
selkies restart, input dies after the first restart: verify live by restarting selkies twice.
