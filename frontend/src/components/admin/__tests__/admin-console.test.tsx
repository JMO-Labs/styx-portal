import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";

const sessions = vi.fn();
const capacity = vi.fn();
let user: { role: string; staff_role?: string } = { role: "user", staff_role: "help-desk" };
vi.mock("@/api/client", () => ({
  api: { adminSessions: () => sessions(), adminCapacity: () => capacity() },
  ApiError: class extends Error { constructor(m: string, public status = 0) { super(m); } },
}));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user }) }));
vi.mock("@/components/layout/header", () => ({ Header: () => <header /> }));

import { ApiError } from "@/api/client";
import { AdminConsole } from "../admin-console";

const view = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><AdminConsole /></MemoryRouter>
  </QueryClientProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  user = { role: "user", staff_role: "help-desk" };
  sessions.mockResolvedValue({ sessions: [{ id: "i1", owner: "alice", template: "Firefox", image: "img:1", started_at: "2026-11-13T10:00:00", node: "local" }] });
  capacity.mockResolvedValue({ running: 3, max_per_user: 2, limit: null, live_streams: 1, per_node: { local: 3 } });
});

test("sessions page lists running sessions", async () => {
  view("/admin/sessions");
  expect(await screen.findByText("alice")).toBeInTheDocument();
  expect(screen.getByText("Firefox")).toBeInTheDocument();
});

test("capacity page shows tiles", async () => {
  view("/admin/capacity");
  expect(await screen.findByText("Running")).toBeInTheDocument();
  expect(screen.getByText("3")).toBeInTheDocument();
});

test("nav hides items the role may not use", async () => {
  view("/admin/sessions");
  await screen.findByText("alice");
  expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Policy" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Announcements" })).toBeNull();
});

test("platform admin sees every nav item", async () => {
  user = { role: "admin", staff_role: "platform-admin" };
  view("/admin/sessions");
  for (const n of ["Sessions", "Capacity", "Users", "Policy", "Announcements"])
    expect(await screen.findByRole("link", { name: n })).toBeInTheDocument();
});

test("403 shows No access", async () => {
  sessions.mockRejectedValue(new ApiError("Forbidden", 403));
  view("/admin/sessions");
  expect(await screen.findByRole("heading", { name: "No access" })).toBeInTheDocument();
});

test("no staff role shows No access without calling the API", async () => {
  user = { role: "user", staff_role: "" };
  view("/admin/sessions");
  expect(await screen.findByRole("heading", { name: "No access" })).toBeInTheDocument();
  await waitFor(() => expect(sessions).not.toHaveBeenCalled());
});

test("sessions refetch every 15 s", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  view("/admin/sessions");
  await screen.findByText("alice");
  await vi.advanceTimersByTimeAsync(15_100);
  expect(sessions.mock.calls.length).toBeGreaterThanOrEqual(2);
  vi.useRealTimers();
});
