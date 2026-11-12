import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";

const { a, auth } = vi.hoisted(() => ({
  a: { oauthProviders: vi.fn(), refreshSession: vi.fn(), systemProfile: vi.fn() },
  auth: { user: null, loading: false, setupRequired: false, refresh: vi.fn(), logout: vi.fn() },
}));
vi.mock("@/api/client", () => ({ api: a, withRetry: (fn: () => unknown) => fn() }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => auth }));
vi.mock("@/components/auth/LoginBrandPanel", () => ({ LoginBrandPanel: () => null }));
vi.mock("sonner", () => ({ toast: vi.fn() }));

import { LoginPage } from "../LoginPage";

beforeEach(() => {
  vi.clearAllMocks();
  a.oauthProviders.mockResolvedValue([]);
});

const form = () => screen.getByTestId("password-form") as HTMLFormElement;

test("enterprise profile hides the password form (ADR-0053)", async () => {
  a.systemProfile.mockResolvedValue({ profile: "enterprise", disabled: ["password_login", "matrix_2fa"] });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  await waitFor(() => expect(form().hidden).toBe(true));
});

test("homelab profile keeps the password form", async () => {
  a.systemProfile.mockResolvedValue({ profile: "homelab", disabled: [] });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  await waitFor(() => expect(a.systemProfile).toHaveBeenCalled());
  expect(form().hidden).toBe(false);
});
