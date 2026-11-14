import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reportRtt = vi.fn((_body: unknown) => Promise.resolve());
vi.mock("@/api/client", () => ({ api: { reportRtt: (b: unknown) => reportRtt(b) } }));
vi.mock("@/hooks/use-instances", () => ({
  useInstances: () => ({ data: [{ id: "i1", name: "My Desk", subdomain: "desk", status: "running" }], isPending: false }),
  useKeepalive: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/lib/activity", () => ({ startActivityHeartbeat: () => () => {} }));
vi.mock("@/hooks/use-templates", () => ({ useTemplates: () => ({ data: [] }) }));
vi.mock("@/lib/stream-thumb", () => ({ startThumbUploader: () => () => {} }));

import { DesktopPage } from "../DesktopPage";

function mount() {
  render(
    <MemoryRouter initialEntries={["/desktop/desk"]}>
      <Routes><Route path="/desktop/:sub" element={<DesktopPage />} /></Routes>
    </MemoryRouter>,
  );
  return screen.getByTitle("My Desk") as HTMLIFrameElement;
}

function post(data: unknown, o: { origin?: string; source?: unknown } = {}, frame?: HTMLIFrameElement) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", {
      data, origin: o.origin ?? window.location.origin,
      source: (o.source ?? frame?.contentWindow) as MessageEventSource,
    }));
  });
}

const good = { type: "styx-rtt", rtt_ms: 80, transport: "webrtc" };
const tick = () => act(() => { vi.advanceTimersByTime(60_000); });

describe("DesktopPage RTT reporting", () => {
  let vis = "visible";
  beforeEach(() => {
    vi.useFakeTimers(); reportRtt.mockClear(); vis = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => vis as DocumentVisibilityState);
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("reports a valid same-origin message from the iframe", () => {
    const f = mount();
    post(good, {}, f);
    tick();
    expect(reportRtt).toHaveBeenCalledWith({ transport: "webrtc", buckets: { ".08": 1 }, sum: 0.08 });
  });

  it("ignores other origins", () => {
    const f = mount();
    post(good, { origin: "https://evil.example" }, f);
    tick();
    expect(reportRtt).not.toHaveBeenCalled();
  });

  it("ignores source other than the iframe", () => {
    mount();
    post(good, { source: window });
    tick();
    expect(reportRtt).not.toHaveBeenCalled();
  });

  it.each([
    ["string rtt", { type: "styx-rtt", rtt_ms: "80", transport: "webrtc" }],
    ["missing type", { rtt_ms: 80, transport: "webrtc" }],
    ["bad transport", { type: "styx-rtt", rtt_ms: 80, transport: "x" }],
    ["null", null],
  ])("ignores malformed payload: %s", (_n, data) => {
    const f = mount();
    post(data, {}, f);
    tick();
    expect(reportRtt).not.toHaveBeenCalled();
  });

  it("does not sample while hidden", () => {
    const f = mount();
    vis = "hidden";
    post(good, {}, f);
    tick();
    expect(reportRtt).not.toHaveBeenCalled();
  });

  it("flushes via sendBeacon on pagehide", () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    const f = mount();
    post(good, {}, f);
    act(() => { window.dispatchEvent(new Event("pagehide")); });
    expect(beacon).toHaveBeenCalledTimes(1);
    expect((beacon.mock.calls[0] as unknown[])[0]).toBe("/api/stream/rtt");
  });
});
