import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Generic API stub: list*/discover* and known array endpoints -> [],
// shaped endpoints -> minimal payload, everything else -> {}.
vi.mock("@/api/client", () => {
  const arrays = new Set(["getSystemSettings", "linkedProviders", "oauthProviders", "getMyProfiles", "accessReview"]);
  const shaped: Record<string, () => Promise<unknown>> = {
    listImages: async () => [{ id: "img1", image: "styx/desktop:latest", size_mb: 512, pulled_at: "2026-11-01T00:00:00Z" }],
    listOAuthProviders: async () => [{
      id: "p1", name: "authentik", display_label: "Authentik", kind: "oidc", issuer_url: "https://id.example",
      client_id: "styx", scopes: "openid email", role_map: {}, enabled: true, has_secret: true, icon_url: null,
      trust_email: false, allow_signup: false, auto_promote_admins: false, redirect_uri: "", test_redirect_uri: "",
    }],
    getDiagnosticsHistory: async () => ({ status: {} }),
    getRelayStats: async () => { throw new Error("unavailable"); },
  };
  return {
    api: new Proxy({}, {
      get: (_t, k: string) => shaped[k] ?? (async () => (/^(list|discover)/.test(k) || arrays.has(k) ? [] : {})),
    }),
    ApiError: class extends Error {},
  };
});
vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ user: { id: 1, username: "admin", role: "admin" }, logout: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { CATEGORIES } from "../nav-config";
import { expectNoSeriousA11y } from "@/test/axe";

const sections = CATEGORIES.flatMap((c) => c.sections);
const byId = (id: string) => sections.find((s) => s.id === id)!;

function renderSection(id: string) {
  const { Component } = byId(id);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Component /></MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, qc };
}

describe("settings sections a11y", () => {
  test.each(sections.map((s) => s.id))("%s has no serious a11y violations", async (id) => {
    const { container, qc } = renderSection(id);
    // Wait until every query has settled so loaded content (not spinners) is audited.
    await waitFor(() => expect(qc.isFetching()).toBe(0));
    await waitFor(() => expectNoSeriousA11y(container));
  });

  test("image rows have a named remove button", async () => {
    const { container } = renderSection("images");
    const btn = await screen.findByRole("button", { name: "Remove styx/desktop:latest" });
    expect(btn.className).toContain("focus-visible:opacity-100");
    await expectNoSeriousA11y(container);
  });

  test("provider rows and dialog fields are labelled", async () => {
    const { container } = renderSection("sso");
    expect(await screen.findByRole("checkbox", { name: "Enable authentik" })).toBeChecked();
    await expectNoSeriousA11y(container);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    expect(await screen.findByLabelText("Display name")).toHaveValue("Authentik");
    expect(screen.getByLabelText("Client ID")).toHaveValue("styx");
    expect(screen.getByLabelText("Display name")).toHaveAccessibleDescription("Shown to users on the login button.");
    await expectNoSeriousA11y(dialog);
  });
});
