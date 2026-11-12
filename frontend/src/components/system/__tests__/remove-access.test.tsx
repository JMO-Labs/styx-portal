import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, test, vi } from "vitest";

const listUsers = vi.fn();
const removeAccess = vi.fn();
vi.mock("@/api/client", () => ({
  api: {
    listUsers: (...a: unknown[]) => listUsers(...a),
    listInvites: () => Promise.resolve([]),
    removeAccess: (...a: unknown[]) => removeAccess(...a),
  },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/components/system/user-groups-dialog", () => ({ UserGroupsDialog: () => null }));

import { UsersPanel } from "../users-panel";

const row = (o: object) => ({ last_login: null, locked_until: null, failed_count: 0, email: "pat@x.io",
  id: "u1", username: "pat", role: "user", is_active: true, ...o });

beforeEach(() => vi.clearAllMocks());

describe("Remove access", () => {
  test("confirm dialog then row shows Disabled", async () => {
    let active = true;
    listUsers.mockImplementation(() => Promise.resolve([row({ is_active: active })]));
    removeAccess.mockImplementation(async () => { active = false; return {}; });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><UsersPanel /></QueryClientProvider>);
    fireEvent.keyDown(await screen.findByRole("button", { name: "More actions for pat" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Remove access/ }));
    expect(removeAccess).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Remove access" }));
    await waitFor(() => expect(removeAccess).toHaveBeenCalledWith("u1"));
    expect(await screen.findByText("Disabled")).toBeTruthy();
  });
});
