import { render, waitFor } from "@testing-library/react";
import { describe, test, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Generic API stub: list*/discover* -> [], everything else -> {}.
vi.mock("@/api/client", () => ({
  api: new Proxy({}, {
    get: (_t, k: string) => async () => (/^(list|discover)/.test(k) ? [] : {}),
  }),
  ApiError: class extends Error {},
}));
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
