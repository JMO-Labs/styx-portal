import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

const { a, auth } = vi.hoisted(() => ({
  a: { setupRequired: vi.fn(), oauthProviders: vi.fn(), refreshSession: vi.fn() },
  auth: { user: null as null | { id: string }, loading: false, setupRequired: false,
    refresh: vi.fn(), logout: vi.fn() },
}));
vi.mock("@/api/client", () => ({ api: a, withRetry: (fn: () => unknown) => fn() }));
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => auth }));
vi.mock("@/components/auth/LoginBrandPanel", () => ({ LoginBrandPanel: () => null }));
vi.mock("sonner", () => ({ toast: vi.fn() }));

import { LoginPage } from "../LoginPage";

const replace = vi.fn();
const realLocation = window.location;

function at(search: string, banner_url: string) {
  a.setupRequired.mockResolvedValue({ setup_required: false, banner_url });
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...realLocation, origin: "http://localhost", search, replace, href: "" },
  });
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  a.oauthProviders.mockResolvedValue([]);
});
afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

describe("LoginPage banner redirect", () => {
  test("banner_url set redirects to it", async () => {
    at("", "https://banner.example.com/");
    await waitFor(() => expect(replace).toHaveBeenCalledWith("https://banner.example.com/"));
  });

  test("empty banner_url does not redirect", async () => {
    at("", "");
    await waitFor(() => expect(a.setupRequired).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(replace).not.toHaveBeenCalled();
  });

  test("?error present does not redirect (loop guard)", async () => {
    at("?error=oauth_failed", "https://banner.example.com/");
    await waitFor(() => expect(a.setupRequired).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(replace).not.toHaveBeenCalled();
  });
});
