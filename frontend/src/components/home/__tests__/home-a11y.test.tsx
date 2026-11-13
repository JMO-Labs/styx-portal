import { render, screen } from "@testing-library/react";
import { describe, test, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const role = { current: "user" };
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user: { id: "u", role: role.current } }) }));
vi.mock("@/api/client", () => ({
  api: {
    getHomeStorage: () => Promise.resolve({ used_bytes: null, quota_bytes: null, percent: null, warn: false }),
    myWorkstations: () => Promise.resolve([{ id: "w1", name: "mini", status: "online", in_use: false, in_use_self: false, in_use_by: null, icon_etag: "e", os_info: {} }]),
    listServiceTiles: () => Promise.resolve([{ id: "s1", slug: "sonarr", name: "Sonarr", icon_kind: "image", icon_etag: "e", mount_mode: "path", frame_ok: true, enabled: true, up: true, needs_setup: true }]),
    serviceFocus: () => Promise.resolve({ slug: null }),
    workstationThumbUrl: (id: string) => `/t/${id}`,
    screenshotUrl: (id: string) => `/s/${id}`,
  },
  ApiError: class extends Error {},
}));
vi.mock("@/hooks/use-instances", () => ({
  useInstances: () => ({ data: [{ id: "i1", name: "Chrome", template_id: "t", subdomain: "chrome", status: "running" }] }),
  useStartInstance: () => ({ mutate: vi.fn() }),
  useStopInstance: () => ({ mutate: vi.fn() }),
  useUnpauseInstance: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/hooks/use-templates", () => ({ useTemplates: () => ({ data: [{ id: "t", icon: "🌐" }] }) }));
vi.mock("@/components/open-prompt", () => ({ useOpenChoice: () => vi.fn() }));
vi.mock("@/components/home/details-sheet", () => ({ DetailsSheet: () => null }));
vi.mock("@/lib/effects/water", () => ({ createWater: () => ({ destroy() {} }) }));

import { HomePage } from "../home-page";
import { expectNoSeriousA11y } from "@/test/axe";

describe("HomePage a11y", () => {
  test("no serious axe violations", async () => {
    const { container } = render(<QueryClientProvider client={new QueryClient()}><HomePage onNewContainer={vi.fn()} /></QueryClientProvider>);
    await screen.findByText("mini");
    await expectNoSeriousA11y(container);
  });
});
