import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ServiceTile } from "@/api/client";
import { expectNoSeriousA11y } from "@/test/axe";

vi.mock("@/api/client", () => ({ api: {
  myWorkstations: () => Promise.resolve([]), listInstances: () => Promise.resolve([]),
  workstationConnectUrl: () => Promise.resolve({ url: "/" }),
} }));
vi.mock("@/components/open-prompt", () => ({ useOpenChoice: () => vi.fn() }));
vi.mock("@/lib/connect-wipe", () => ({ openPending: vi.fn(() => Promise.resolve()) }));
import { Dock } from "../dock";
import { EdgeTab } from "../edge-tab";
import { Card, Frame } from "../frame";

const tile: ServiceTile = { id: "1", slug: "sonarr", name: "Sonarr", icon_kind: "auto", icon_etag: "e", mount_mode: "path", enabled: true, up: true, frame_ok: true, needs_setup: false };

test("frame has no serious a11y violations", async () => {
  const { container } = render(<Frame tile={tile} inner="/" onTitle={() => {}} />);
  await expectNoSeriousA11y(container);
});

test("frame fallback card has no serious a11y violations", async () => {
  const { container } = render(<Card title="Sonarr can't run inside Styx" text="Blocked." href="/sonarr/" action="Open Sonarr on its own" />);
  await expectNoSeriousA11y(container);
});

test("edge tab has an accessible name and no violations", async () => {
  const { container } = render(<EdgeTab onOpen={() => {}} />);
  expect(screen.getByRole("button", { name: /Styx menu/ })).toBeInTheDocument();
  await expectNoSeriousA11y(container);
});

test("dock has no serious a11y violations and named controls", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Dock open onOpenChange={() => {}} tiles={[tile]} current="sonarr" focusSlug="sonarr" side="right" />
    </QueryClientProvider>,
  );
  const dialog = await screen.findByRole("dialog", { name: "Styx" });
  for (const el of dialog.querySelectorAll("a,button")) {
    expect((el.textContent ?? "").trim() || el.getAttribute("aria-label")).toBeTruthy();
  }
  await expectNoSeriousA11y(document.body);
});

test("edge tab keeps its opaque outline while the fill fades", () => {
  render(<EdgeTab onOpen={() => {}} />);
  const outline = screen.getByTestId("edge-tab-outline");
  expect(outline.style.boxShadow).toContain("1px");
  expect(screen.getByRole("button").style.opacity).toBe("");
});
