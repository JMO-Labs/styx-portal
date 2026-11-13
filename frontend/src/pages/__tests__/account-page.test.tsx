import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

const stop = vi.fn();
const tiles = { current: [] as unknown[] };
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user: { id: "u", username: "alice", role: "user" }, logout: vi.fn() }) }));
vi.mock("@/api/client", () => ({
  api: {
    getHomeStorage: () => Promise.resolve({ used_bytes: 2 * 1024 ** 3, quota_bytes: 10 * 1024 ** 3, percent: 20, warn: false }),
    listServiceTiles: () => Promise.resolve(tiles.current),
  },
}));
vi.mock("@/hooks/use-instances", () => ({
  useInstances: () => ({ data: [
    { id: "i1", name: "Chrome", subdomain: "chrome", status: "running" },
    { id: "i2", name: "Old", subdomain: "old", status: "stopped" },
  ] }),
  useStopInstance: () => ({ mutate: stop }),
}));
const open = vi.fn();
vi.mock("@/hooks/use-open-actions", () => ({ useOpenInstance: () => open }));
vi.mock("@/components/settings/my-profiles", () => ({ MyProfiles: () => <div>profiles-stub</div> }));
vi.mock("@/components/layout/header", () => ({ Header: () => null }));

import { AccountPage } from "../AccountPage";

const renderPage = () =>
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><AccountPage /></MemoryRouter></QueryClientProvider>);

beforeEach(() => { stop.mockClear(); open.mockClear(); tiles.current = []; });

describe("AccountPage", () => {
  test("renders storage quota bar", async () => {
    renderPage();
    const bar = await screen.findByRole("progressbar", { name: /home storage/i });
    expect(bar).toHaveAttribute("aria-valuenow", "20");
    expect(screen.getByText(/2 GB \/ 10 GB/)).toBeInTheDocument();
  });

  test("files section hidden without a files app, shown with one", async () => {
    const { unmount } = renderPage();
    await screen.findByRole("progressbar");
    expect(screen.queryByRole("heading", { name: "Files" })).toBeNull();
    unmount();
    tiles.current = [{ id: "s", slug: "files", name: "Files", enabled: true }];
    renderPage();
    expect(await screen.findByRole("link", { name: /open files/i })).toHaveAttribute("href", "/_styx/app/files/");
  });

  test("profiles section reuses MyProfiles", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Profiles" })).toBeInTheDocument();
    expect(screen.getByText("profiles-stub")).toBeInTheDocument();
  });

  test("sessions list running desktops; Open and Stop work", async () => {
    renderPage();
    const sec = screen.getByRole("region", { name: "Sessions" });
    expect(within(sec).queryByText("Old")).toBeNull();
    await userEvent.click(within(sec).getByRole("button", { name: "Open Chrome" }));
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ id: "i1" }));
    await userEvent.click(within(sec).getByRole("button", { name: "Stop Chrome" }));
    expect(stop).toHaveBeenCalledWith("i1", expect.anything());
  });
});
