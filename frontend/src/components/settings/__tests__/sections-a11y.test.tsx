import { render, waitFor } from "@testing-library/react";
import { describe, test, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Generic API stub: list*/discover* and known array endpoints -> [],
// shaped endpoints -> minimal payload, everything else -> {}.
vi.mock("@/api/client", () => {
  const arrays = new Set(["getSystemSettings", "linkedProviders", "oauthProviders", "getMyProfiles"]);
  const shaped: Record<string, () => Promise<unknown>> = {
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

describe("settings sections a11y", () => {
  test.each(sections.map((s) => [s.id, s] as const))("%s has no serious a11y violations", async (_id, s) => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><s.Component /></MemoryRouter>
      </QueryClientProvider>,
    );
    await new Promise((r) => setTimeout(r, 50));
    await waitFor(() => expectNoSeriousA11y(container));
  });
});
