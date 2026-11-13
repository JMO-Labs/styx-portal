import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

const takeover = vi.fn();
vi.mock("@/api/client", async (orig) => {
  const mod = await orig<typeof import("@/api/client")>();
  return { ...mod, api: { ...mod.api, takeover: (id: string) => takeover(id) } };
});
import { ApiError } from "@/api/client";
import { useTakeover } from "../use-instances";

const active = { actor_name: "Ada", mode: "control", started_at: "x" };
let qc: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={qc}>{children}</QueryClientProvider>
);

beforeEach(() => {
  takeover.mockReset();
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

test("keeps the active takeover when a poll fails transiently", async () => {
  takeover.mockResolvedValueOnce(active).mockRejectedValueOnce(new ApiError("boom", 503));
  const { result } = renderHook(() => useTakeover("i1", true), { wrapper });
  await waitFor(() => expect(result.current.data).toEqual(active));
  await qc.refetchQueries({ queryKey: ["takeover", "i1"] });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(result.current.data).toEqual(active);
});

test("maps 403/404 to no takeover", async () => {
  takeover.mockRejectedValueOnce(new ApiError("nope", 404));
  const { result } = renderHook(() => useTakeover("i1", true), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data).toBeNull();
});
