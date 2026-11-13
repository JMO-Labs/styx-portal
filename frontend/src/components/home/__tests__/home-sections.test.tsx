import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const ann = { current: [] as unknown[] };
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user: { id: "u", role: "user" } }) }));
vi.mock("@/api/client", () => ({
  api: {
    getHomeStorage: () => Promise.resolve({ used_bytes: null, quota_bytes: null, percent: null, warn: false }),
    listNotices: () => Promise.resolve([]),
    listAnnouncements: () => Promise.resolve(ann.current),
    myWorkstations: () => Promise.resolve([{ id: "w1", name: "mini", status: "online", in_use: false, in_use_self: false, in_use_by: null, icon_etag: "e", os_info: {} }]),
    listServiceTiles: () => Promise.resolve([{ id: "s1", slug: "sonarr", name: "Sonarr", icon_kind: "image", icon_etag: "e", mount_mode: "path", frame_ok: true, enabled: true, up: true, needs_setup: false }]),
    serviceFocus: () => Promise.resolve({ slug: null }),
    workstationThumbUrl: (id: string) => `/t/${id}`,
    screenshotUrl: (id: string) => `/s/${id}`,
  },
  ApiError: class extends Error {},
}));
vi.mock("@/hooks/use-instances", () => ({
  useInstances: () => ({ data: [] }),
  useStartInstance: () => ({ mutate: vi.fn() }),
  useStopInstance: () => ({ mutate: vi.fn() }),
  useUnpauseInstance: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/hooks/use-templates", () => ({ useTemplates: () => ({ data: [] }) }));
vi.mock("@/components/open-prompt", () => ({ useOpenChoice: () => vi.fn() }));
vi.mock("@/components/home/details-sheet", () => ({ DetailsSheet: () => null }));
vi.mock("@/lib/effects/water", () => ({ createWater: () => ({ destroy() {} }) }));

import { HomePage } from "../home-page";
import { expectNoSeriousA11y } from "@/test/axe";

const renderHome = () =>
  render(<QueryClientProvider client={new QueryClient()}><HomePage onNewContainer={vi.fn()} /></QueryClientProvider>);

beforeEach(() => { ann.current = []; localStorage.clear(); });

describe("home sections", () => {
  test("My desktops and My services are landmarks with headings", async () => {
    renderHome();
    await screen.findByText("mini");
    const d = screen.getByRole("region", { name: "My desktops" });
    expect(within(d).getByRole("heading", { level: 2, name: "My desktops" })).toBeInTheDocument();
    expect(within(d).getByText("mini")).toBeInTheDocument();
    const s = screen.getByRole("region", { name: "My services" });
    expect(within(s).getByRole("heading", { level: 2, name: "My services" })).toBeInTheDocument();
    expect(await within(s).findByRole("link", { name: /sonarr/i })).toBeInTheDocument();
  });

  test("Announcements section lists active announcements", async () => {
    ann.current = [
      { id: "a1", title: "Patch night", body: "Friday 22:00", kind: "maintenance" },
      { id: "a2", title: "New apps", body: "Jellyfin added", kind: "info" },
    ];
    renderHome();
    const a = await screen.findByRole("region", { name: "Announcements" });
    expect(within(a).getByRole("heading", { level: 2, name: "Announcements" })).toBeInTheDocument();
    expect(within(a).getAllByRole("listitem")).toHaveLength(2);
    expect(within(a).getByText("Patch night")).toBeInTheDocument();
    expect(within(a).getByText("Jellyfin added")).toBeInTheDocument();
  });

  test("empty state: Announcements hidden", async () => {
    renderHome();
    await screen.findByText("mini");
    expect(screen.queryByRole("region", { name: "Announcements" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Announcements" })).toBeNull();
  });

  test("axe clean with announcements", async () => {
    ann.current = [{ id: "a1", title: "Patch night", body: "Friday", kind: "info" }];
    const { container } = renderHome();
    await screen.findByRole("region", { name: "Announcements" });
    await expectNoSeriousA11y(container);
  });
});
