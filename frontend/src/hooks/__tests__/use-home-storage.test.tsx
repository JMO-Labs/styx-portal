import { renderHook, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useHomeStorage } from "../use-home-storage";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);
afterEach(() => vi.unstubAllGlobals());

describe("useHomeStorage", () => {
  test("fetches /api/me/storage", async () => {
    const body = { used_bytes: 9, quota_bytes: 10, percent: 90, warn: true };
    const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", f);
    const { result } = renderHook(() => useHomeStorage(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(body));
    expect(String(f.mock.calls[0]?.[0])).toContain("/api/me/storage");
  });
});
