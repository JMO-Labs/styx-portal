import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

const listProvisioned = vi.fn();
const reviewProvisioned = vi.fn();
const suspendProvisioned = vi.fn();
vi.mock("@/api/client", () => ({
  api: {
    listProvisioned: (...a: unknown[]) => listProvisioned(...a),
    reviewProvisioned: (...a: unknown[]) => reviewProvisioned(...a),
    suspendProvisioned: (...a: unknown[]) => suspendProvisioned(...a),
  },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { RecentlyProvisionedPanel, dueBy } from "../recently-provisioned-panel";

// Wed 2026-11-11 12:00Z
const NOW = new Date("2026-11-11T12:00:00Z");
const row = (o: object) => ({
  id: "u1", username: "alice", email: "a@x", created_at: "2026-11-10T12:00:00Z",
  reviewed_at: null, status: "active", disabled_reason: null, ...o,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  listProvisioned.mockResolvedValue([
    row({}),
    row({ id: "u2", username: "bob", created_at: "2026-11-09T12:00:00Z" }),
    row({ id: "u3", username: "carol", created_at: "2026-11-01T12:00:00Z", reviewed_at: "2026-11-02T00:00:00Z" }),
  ]);
  reviewProvisioned.mockResolvedValue({});
  suspendProvisioned.mockResolvedValue({});
});
afterEach(() => vi.useRealTimers());

describe("dueBy", () => {
  test("treats naive timestamps as UTC", () => {
    expect(dueBy("2026-11-10T12:00:00").toISOString()).toBe("2026-11-11T12:00:00.000Z");
  });
  test("adds one business day, skipping weekends", () => {
    expect(dueBy("2026-11-10T12:00:00Z").toISOString()).toBe("2026-11-11T12:00:00.000Z");
    expect(dueBy("2026-11-13T12:00:00Z").toISOString()).toBe("2026-11-16T12:00:00.000Z"); // Fri -> Mon
    expect(dueBy("2026-11-14T12:00:00Z").toISOString()).toBe("2026-11-16T12:00:00.000Z"); // Sat -> Mon
  });
});

describe("RecentlyProvisionedPanel", () => {
  test("lists users with reviewed state and due-by", async () => {
    render(<RecentlyProvisionedPanel />);
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(within(screen.getByTestId("row-u3")).getByText(/reviewed/i)).toBeInTheDocument();
    expect(within(screen.getByTestId("row-u1")).getByText(/due/i)).toBeInTheDocument();
  });

  test("flags unreviewed rows past due only", async () => {
    render(<RecentlyProvisionedPanel />);
    await screen.findByText("alice");
    expect(screen.getByTestId("row-u2")).toHaveAttribute("data-overdue", "true");
    expect(screen.getByTestId("row-u1")).toHaveAttribute("data-overdue", "false");
    expect(screen.getByTestId("row-u3")).toHaveAttribute("data-overdue", "false");
  });

  test("mark reviewed calls api and refreshes", async () => {
    render(<RecentlyProvisionedPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /mark alice reviewed/i }));
    await waitFor(() => expect(reviewProvisioned).toHaveBeenCalledWith("u1"));
    await waitFor(() => expect(listProvisioned).toHaveBeenCalledTimes(2));
  });

  test("suspend requires confirmation then refreshes", async () => {
    render(<RecentlyProvisionedPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /suspend alice/i }));
    expect(suspendProvisioned).not.toHaveBeenCalled();
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: /^suspend$/i }));
    await waitFor(() => expect(suspendProvisioned).toHaveBeenCalledWith("u1"));
    await waitFor(() => expect(listProvisioned).toHaveBeenCalledTimes(2));
  });
});
