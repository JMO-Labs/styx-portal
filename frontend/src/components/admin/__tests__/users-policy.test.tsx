import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";

const users = vi.fn();
const adminUser = vi.fn();
const settings = vi.fn();
let user: { role: string; staff_role?: string } = { role: "user", staff_role: "platform-admin" };
vi.mock("@/api/client", () => ({
  api: { adminUsers: () => users(), adminUser: (id: string) => adminUser(id), getSystemSettings: () => settings() },
  ApiError: class extends Error { constructor(m: string, public status = 0) { super(m); } },
}));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ user }) }));
vi.mock("@/components/layout/header", () => ({ Header: () => <header /> }));

import { AdminConsole } from "../admin-console";

const view = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/admin/*" element={<AdminConsole />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  user = { role: "user", staff_role: "platform-admin" };
  users.mockResolvedValue({ users: [{ id: "u1", username: "alice", email: "a@x.test", staff_role: "" }] });
  adminUser.mockResolvedValue({
    id: "u1", username: "alice", display_name: "alice", email: "a@x.test", staff_role: "",
    groups: ["devs"], created_at: "2026-11-01T10:00:00", last_login: null,
    storage: { used_bytes: 1073741824, quota_bytes: 2147483648, percent: 50, warn: false },
    sessions: [{ id: "i1", template: "Firefox", started_at: null, node: "local" }],
  });
  settings.mockResolvedValue([{ group: "sessions", label: "Sessions", settings: [
    { key: "IDLE_TIMEOUT", label: "Idle timeout", help: "", type: "bool", value: true, default: true, min: null, max: null }] }]);
});

test("users list links to detail", async () => {
  view("/admin/users");
  expect(await screen.findByRole("link", { name: /alice/ })).toHaveAttribute("href", "/admin/users/u1");
});

test("user detail shows profile, groups, quota, sessions", async () => {
  view("/admin/users/u1");
  expect(await screen.findByText("a@x.test")).toBeInTheDocument();
  expect(screen.getByText("devs")).toBeInTheDocument();
  expect(screen.getByText(/1\.0 GB of 2\.0 GB \(50%\)/)).toBeInTheDocument();
  expect(screen.getByText(/Firefox/)).toBeInTheDocument();
});

test("policy is editable for platform-admin", async () => {
  view("/admin/policy");
  expect(await screen.findByRole("switch", { name: /idle timeout/i })).toBeEnabled();
});

test("policy is read-only for auditor", async () => {
  user = { role: "user", staff_role: "auditor" };
  view("/admin/policy");
  expect(await screen.findByRole("switch", { name: /idle timeout/i })).toBeDisabled();
  expect(screen.getByText(/Read-only/)).toBeInTheDocument();
});
