# Seat Multi-Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Selkies' Add Screen extends a GNOME seat onto a second browser window, with monitor 2 created by pixelflux through the portal's virtual source only while that window is open.

**Architecture:** pixelflux (our fork, then upstream) grows one extra display in host capture by opening a portal ScreenCast session with the virtual source type and arranges Mutter with `org.gnome.Mutter.DisplayConfig`. The Styx seat portal backend serves virtual sources with Mutter `RecordVirtual`; the agent gateway lets a `#display` window join the owner's session.

**Tech Stack:** Rust (pixelflux, zbus 6, PipeWire), Python 3.12 (agent: aiohttp, dbus-python, GStreamer), selkies 2.2.0.

**Spec:** `docs/superpowers/specs/2026-11-15-seat-multi-display-design.md`

## Global Constraints

- Two repos. Styx: worktree `/home/user/code/remote-access-multidisplay`, branch `feat/seat-multi-display`. pixelflux: durable clone `/home/user/code/pixelflux` of `JMO-Labs/pixelflux`, branch `styx/multi-display` (already holds `d23c43a`, `3fb3274`, `6b369b6`, `f569d27`).
- pixelflux code follows its `AGENTS.md`: no inline comments, no history comments, American English, commit subjects like `fix(wayland): Count screens, not views, against the host's output capacity`.
- pixelflux: an optional host path is taken only when detected, never as the default. Single-display sessions must behave exactly as today.
- Capacity headroom is exactly one extra display (Selkies offers only `display2`).
- On a Mutter host without a working `DisplayConfig`, no extra display is offered.
- No new toolchain on enrolled boxes; wheels are built on the dev host (`cibuildwheel==4.3.5`, `CIBW_BUILD=cp314-manylinux_x86_64`).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Semantic commits; semantic versioning.
- Never read or print the agent's `config.json` on any box (holds the TURN token).
- GAME-01: `ssh -i ~/.ssh/id_gen_key user@192.168.1.64`, install `~/.local/share/styx-agent`, logs in `logs/{seat,selkies,gateway}.log`. Agent restart closes seat apps; the user has approved restarts on GAME-01 for this work.

## Commands

- pixelflux tests (no local Rust): build once `docker build -f .oss-scanner/Dockerfile -t pf-test .` in `/home/user/code/pixelflux`, then `docker run --rm -v "$PWD":/src -v pf-cargo:/usr/local/cargo/registry -v pf-target:/src/pixelflux/target -w /src pf-test cargo test --manifest-path pixelflux/Cargo.toml --lib <filter>`; same for `cargo fmt --check` and `cargo clippy --lib`.
- pixelflux wheel: in `/home/user/code/pixelflux`, `CIBW_BUILD=cp314-manylinux_x86_64 CIBW_ARCHS=x86_64 pipx run cibuildwheel==4.3.5 --platform linux --output-dir <dir>` (~7 min).
- Agent tests: `cd agent && /home/user/code/remote-access/backend/.venv/bin/python -m pytest tests/<file> -q`; full suite `... -m pytest tests -q`.

## Review Focus

1. Owner tab closes or reloads while the second window is open: the second window's socket closes, its portal session ends, monitor 2 disappears, and no orphan virtual monitor survives (Task 6 test `test_sub_closes_with_owner`; Task 4 test `grown_display_removed_on_destroy`).
2. Second window resized rapidly (window drag): no Selkies restart, at most one renegotiation in flight (Task 4 test `resize_coalesces_while_pending`).
3. Primary resize/refit while display 2 is open (agent restarts Selkies): after reconnect exactly one virtual monitor exists (Task 8 live check 7).
4. HiDPI seat (scale 2): positions sent to Mutter are logical (`union / scale`) and monitors stay adjacent (Task 3 test `config_divides_by_scale`).
5. A `#display` page arriving with no owner session: refused, cannot take the seat (Task 6 test `test_sub_refused_without_owner`).

---

### Task 1: Prove the three risks on GAME-01 (spike, throwaway)

**Files:**
- Create (throwaway): pixelflux branch `spike/virtual-display` from `styx/multi-display`; scratch `seat_portal.py` copy under the session scratchpad.
- Modify: `docs/superpowers/specs/2026-11-15-seat-multi-display-design.md` (add a "Spike results" section)

**Interfaces:**
- Produces: the recorded answers below; Tasks 2-4 follow the default path unless the results select a named fallback.

- [ ] **Step 1:** Clone `JMO-Labs/pixelflux` to `/home/user/code/pixelflux`, check out `styx/multi-display`, build the `pf-test` image (Commands).
- [ ] **Step 2:** In the scratch `seat_portal.py`, serve `types` bit 4 by `RecordVirtual` (`is-platform` true, `cursor-mode` metadata) inside the session's ScreenCast session paired with its RemoteDesktop session (`remote-desktop-session-id`), returning that stream with `position`/`size`; advertise `AvailableSourceTypes` = 5. Remove the spike's always-present monitor 2 and layout watcher.
- [ ] **Step 3:** On the spike branch, hard-wire the minimum: when a display beyond the host outputs is created, open a second `PortalSession` with `types` = 4 and back that display with its stream; report capacity host outputs + 1.
- [ ] **Step 4:** Deploy wheel + portal to GAME-01, restart the agent, press Add Screen (user). Record:
  - Risk 1: does pointer/keyboard reach monitor 2 through the primary's libei/RemoteDesktop session? (`grep -a "libei\|EIS" logs/selkies.log`; user clicks on screen 2.) If not, retry with the virtual stream added to the primary's own session.
  - Risk 2: resize the second window; does the stream keep delivering frames (`first portal frame` / no `delivered no frame in 5 s`) after the consumer renegotiates? If not, record that closing and reopening the grown display's own session is required.
  - Risk 3: note which calls the GNOME portal would prompt for (read `xdg-desktop-portal-gnome` `src/screencast.c` persistence for virtual sources); no stock-GNOME box test is required.
- [ ] **Step 5:** Write the answers into the spec's new "Spike results" section and commit: `docs(spec): record multi-display spike results`.

### Task 2: pixelflux portal virtual source

**Files:**
- Modify: `pixelflux/src/wayland/portal.rs`
- Test: `pixelflux/src/wayland/portal.rs` (`#[cfg(test)] mod tests`, line ~610)

**Interfaces:**
- Produces: `pub const SOURCE_VIRTUAL: u32 = 4;`, `pub fn source_types_options(virtual_only: bool) -> u32` (returns 4 or 1), `PortalSession::open_virtual(devices: u32, cursor_mode: u32) -> Result<PortalSession, String>` (one stream, no input devices unless Task 1 chose the paired fallback), `PortalSession::available_source_types(&self) -> u32` (read once at connect, `AvailableSourceTypes`, default 1).

- [ ] **Step 1:** Tests `source_types_monitor_by_default` (`source_types_options(false) == 1`) and `source_types_virtual` (`source_types_options(true) == 4`).
- [ ] **Step 2:** Run them; expect compile failure.
- [ ] **Step 3:** Implement; `start` takes the types from `source_types_options`; `multiple` stays true only for monitors.
- [ ] **Step 4:** Run tests, `cargo fmt --check`, `cargo clippy --lib`; expect pass.
- [ ] **Step 5:** Commit `feat(wayland): Open a portal session on a virtual source`.

### Task 3: pixelflux Mutter arranger (replaces the layout file)

**Files:**
- Create: `pixelflux/src/wayland/mutterclient.rs` (mod in `wayland/mod.rs`)
- Modify: `pixelflux/src/wayland/host.rs` (`apply_layout`: use mutterclient when no `zwlr_output_manager_v1`; delete `write_layout_request` and the `PIXELFLUX_HOST_LAYOUT_FILE` branch)
- Test: `mutterclient.rs` test module

**Interfaces:**
- Produces: `pub fn available() -> bool` (`org.gnome.Mutter.DisplayConfig` owned on the session bus), `pub struct MonitorState { connector: String, mode_id: String, x: i32, y: i32, scale: f64, transform: u32 }`, `pub fn layout_config(current: &[MonitorState], want: &[(String, i32, i32)]) -> Vec<MonitorState>` (pure), `pub fn apply(want: &[(String, i32, i32)]) -> Result<(), String>` (GetCurrentState, `layout_config`, `ApplyMonitorsConfig` method 1).

- [ ] **Step 1:** Tests for `layout_config`: `config_stacks_above` (want `Meta-0 (0,1318)`, `Meta-1 (0,0)` -> same positions), `config_normalizes_origin` (want `(100,50)`/`(2656,50)` -> `(0,0)`/`(2556,0)`), `config_divides_by_scale` (scale 2, want `(0,1318)` -> `(0,659)`), `config_keeps_unlisted_monitor`, `config_primary_is_rank_zero`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement with zbus (already a dependency); deadline-bound every call like `kdeclient.rs`.
- [ ] **Step 4:** Run tests, fmt, clippy; expect pass.
- [ ] **Step 5:** Commit `feat(wayland): Arrange a Mutter host's monitors through DisplayConfig`, then a separate commit removing the layout-file hook: `refactor(wayland): Drop the layout request file`.

### Task 4: pixelflux host capture grows one display

**Files:**
- Modify: `pixelflux/src/wayland/host.rs` (`output_count`, `output_index_for`, `PortalCtl`), `pixelflux/src/lib.rs` (`create_output_on` host branch, output destroy path)
- Test: same files' test modules

**Interfaces:**
- Consumes: Task 2 `PortalSession::open_virtual`, `available_source_types`; Task 3 `mutterclient::available() -> bool`.
- Produces: `fn host_capacity(real_outputs: usize, virtual_ok: bool, arranger_ok: bool) -> usize` (real + 1 only when both flags), `HostCapture::grow(display_id: u32, size: (i32, i32)) -> Result<(), String>`, `HostCapture::shrink(display_id: u32)`, `HostCapture::resize_grown(display_id: u32, size: (i32, i32))`. A grown display's frames come from its own session's stream; rank mapping places it after the real outputs.

- [ ] **Step 1:** Tests: `capacity_adds_one_with_virtual_and_arranger` (`host_capacity(1, true, true) == 2`), `capacity_unchanged_without_arranger` (`(1, true, false) == 1`), `capacity_unchanged_without_virtual` (`(1, false, true) == 1`), `grown_display_removed_on_destroy` (grow then shrink leaves no grown entry and drops the session handle), `resize_coalesces_while_pending` (three `resize_grown` calls while one renegotiation is pending leave exactly one pending, at the last size).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. `output_capacity()` returns `host_capacity(...)`; `create_output_on` past the real count calls `grow`; output destroy calls `shrink`; a size change of a grown display calls `resize_grown` (renegotiate the consumer's format; the Task 1 fallback replaces this with close-and-reopen of that display's session only).
- [ ] **Step 4:** Run tests, fmt, clippy; expect pass.
- [ ] **Step 5:** Commit `feat(wayland): Grow a display on a portal virtual source in host capture`.

### Task 5: pixelflux `styx7` wheel

**Files:**
- Modify: `pixelflux/Cargo.toml`, `pixelflux/Cargo.lock` (`2.2.2+styx7`)

- [ ] **Step 1:** Bump both to `2.2.2+styx7`; commit `chore: Version 2.2.2+styx7`.
- [ ] **Step 2:** Build the wheel (Commands) into `/home/user/code/pixelflux/wheelhouse`; expect `pixelflux-2.2.2+styx7-cp314-...whl`.
- [ ] **Step 3:** `git push origin styx/multi-display`.

### Task 6: Styx seat portal virtual sources + gateway sub-display

**Files:**
- Modify: `agent/seat_portal.py` (virtual sources from Task 1, per-node `_abs` routing, `AvailableSourceTypes` 5), `agent/gateway_html.py` (WebRTC shim), `agent/refit.py` (`RELOAD_JS`, WebSockets shim), `agent/gateway_webrtc.py` (`signaling`), `agent/gateway.py` (`ws_proxy`)
- Test: `agent/tests/test_seat_portal.py`, `agent/tests/test_gateway_webrtc.py`, `agent/tests/test_gateway.py`, `agent/tests/test_refit_js.py`

**Interfaces:**
- Produces: query flag `styx_sub=1` (stripped before Selkies, like `styx_vid`); `viewers.split_sub(raw_qs: str) -> tuple[str, bool]`; `seat_portal.source_types(options) -> int` (pure: 4 when `types & 4`, else 1).

- [ ] **Step 1:** Tests: `test_source_types` (seat_portal), `test_sub_joins_beside_owner` (owner `A` open, sub `B` with `styx_sub=1` stays open, Selkies sees neither `styx_vid` nor `styx_sub`, no BUSY close of either), `test_sub_refused_without_owner` (sub alone closes with `refit.BUSY_CODE`), `test_sub_closes_with_owner` (owner closes -> sub closed within 2 s), `test_sub_no_refit_no_idle` (sub never appears in `viewers.by_vid`; idle expiry of the owner only), the same three for the WebSockets path in `test_gateway.py`, and `test_shim_tags_display_pages` in `test_refit_js.py` (with `location.hash = '#display2-top'` the tagged URL contains `styx_sub=1` and `styx/refit` is not posted).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Sub sockets pass auth/origin like any socket; they are proxied only while the owner session for this seat has a live socket and are closed when it ends.
- [ ] **Step 4:** Run the full agent suite; expect all pass.
- [ ] **Step 5:** Commit `feat(agent): second screen on GNOME seats (portal virtual sources, sub-display windows)`.

### Task 7: Engine flag, wheelhouse, version, docs

**Files:**
- Modify: `agent/engine.py:417` (`--second-screen=true` in seat mode, `false` in mirror mode), `agent/styx_agent.py:19` (`AGENT_VERSION = "0.11.0"`), `scripts/build_agent_artifacts.sh` only if `EXTRA_WHEELS` needs no change (document the wheel), `docs/build/upstream.md` (carrier `2.2.2+styx7` with its upstream PRs), `docs/build/agent.md` (seat portal virtual sources, sub-display gateway), `docs/use/` (short "Two screens" section), `CHANGELOG.md`
- Test: `agent/tests/test_engine.py`

- [ ] **Step 1:** Tests `test_second_screen_on_for_seat`, `test_second_screen_off_for_mirror` (command line contains the right flag).
- [ ] **Step 2:** Run; expect failures. **Step 3:** implement. **Step 4:** run full agent suite; expect pass.
- [ ] **Step 5:** Commit `feat(agent): enable second screen on seats; bump to 0.11.0`, docs in `docs: describe two-screen seats`.

### Task 8: Live verification on GAME-01 and PR

- [ ] **Step 1:** Restore GAME-01 spike files from `*.bak-2screen` and `bak-2screen-pf/`, then install the branch build (agent files + `styx7` wheel); restart the agent.
- [ ] **Step 2:** With the user, check: (1) Add Screen appears; (2) screen 2 shows its own picture at the window size; (3) stacked layout: drag crosses the shared edge, clicks land on both screens; (4) resize the second window: no Selkies restart in `journalctl --user -u styx-agent`; (5) close the second window: `GetCurrentState` lists one monitor; (6) single-screen session unchanged; (7) with screen 2 open, resize the primary window: after the Selkies restart both reconnect and `GetCurrentState` lists exactly two monitors.
- [ ] **Step 3:** Push `feat/seat-multi-display`, open the PR (body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`); check CI.
- [ ] **Step 4:** Prepare the upstream pixelflux feature PR (Tasks 2-4 commits, ported to `selkies-project/selkies` `crates/pixelflux`) from `sgtslaughta/selkies`; user reviews before it is opened.
