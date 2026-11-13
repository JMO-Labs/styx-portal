import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { ApiError, api } from "@/api/client";
import { ArchivePage } from "../ArchivePage";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/api/client", async (orig) => ({
  ...(await orig<typeof import("@/api/client")>()),
  api: { listArchive: vi.fn(), restoreArchive: vi.fn(), sendToArchive: vi.fn() },
}));
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ArchivePage /></QueryClientProvider>);
}
const files = [{ path: "docs/a.txt", name: "a.txt", size: 2048, archived_at: "2026-10-01T12:00:00Z" }];
beforeEach(() => { vi.clearAllMocks(); m.listArchive!.mockResolvedValue(files); });

describe("ArchivePage", () => {
  test("lists files with name, size, date", async () => {
    view();
    expect(await screen.findByText("a.txt")).toBeInTheDocument();
    expect(screen.getByText("2 KB")).toBeInTheDocument();
    expect(screen.getByText(/2026-10-01/)).toBeInTheDocument();
  });
  test("restore success toasts", async () => {
    m.restoreArchive!.mockResolvedValue({});
    view();
    await userEvent.click(await screen.findByRole("button", { name: /restore/i }));
    expect(m.restoreArchive).toHaveBeenCalledWith("docs/a.txt");
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });
  test("restore 409 toasts error", async () => {
    m.restoreArchive!.mockRejectedValue(new ApiError("exists", 409));
    view();
    await userEvent.click(await screen.findByRole("button", { name: /restore/i }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("exists")));
  });
  test("send form calls API with path", async () => {
    m.sendToArchive!.mockResolvedValue({});
    view();
    await userEvent.type(await screen.findByLabelText(/path/i), "old/big.iso");
    await userEvent.click(screen.getByRole("button", { name: /send to archive/i }));
    expect(m.sendToArchive).toHaveBeenCalledWith("old/big.iso");
  });
  test("disabled state when archive disabled", async () => {
    m.listArchive!.mockRejectedValue(new ApiError("archive disabled", 404));
    view();
    expect(await screen.findByText(/archive is disabled/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send to archive/i })).toBeNull();
  });
});
