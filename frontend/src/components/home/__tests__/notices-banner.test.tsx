import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "@/api/client";
import { NoticesBanner } from "../notices-banner";

vi.mock("@/api/client", async (orig) => ({
  ...(await orig<typeof import("@/api/client")>()),
  api: { listNotices: vi.fn(), dismissNotice: vi.fn() },
}));
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const view = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><NoticesBanner /></QueryClientProvider>);
beforeEach(() => vi.clearAllMocks());

test("shows notices and dismisses", async () => {
  m.listNotices!.mockResolvedValue([{ id: "n1", message: "3 files age off in 7 days", dismissed: false }]);
  m.dismissNotice!.mockResolvedValue(undefined);
  view();
  expect(await screen.findByText("3 files age off in 7 days")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
  await waitFor(() => expect(m.dismissNotice).toHaveBeenCalledWith("n1"));
});
test("hides dismissed notices; renders nothing when none", async () => {
  m.listNotices!.mockResolvedValue([{ id: "n1", message: "old", dismissed: true }]);
  const { container } = view();
  await waitFor(() => expect(m.listNotices).toHaveBeenCalled());
  expect(container.innerHTML).toBe("");
});
test("renders nothing on error", async () => {
  m.listNotices!.mockRejectedValue(new Error("x"));
  const { container } = view();
  await waitFor(() => expect(m.listNotices).toHaveBeenCalled());
  expect(container.innerHTML).toBe("");
});
