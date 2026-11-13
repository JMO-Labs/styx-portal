import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";

const accessReview = vi.fn();
const decideAccessReview = vi.fn();
vi.mock("@/api/client", () => ({
  api: {
    accessReview: (...a: unknown[]) => accessReview(...a),
    decideAccessReview: (...a: unknown[]) => decideAccessReview(...a),
  },
  ApiError: class extends Error { constructor(m: string, public status = 0) { super(m); } },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { ApiError } from "@/api/client";
import { AccessReviewPanel, currentQuarter } from "../access-review-panel";

const row = (o: object) => ({
  quarter: "2026-Q4", group_id: "g1", group: "media", user_id: "u1", username: "alice",
  email: "alice@x.io", decision: null, actor: null, decided_at: null, ...o,
});

beforeEach(() => {
  vi.clearAllMocks();
  accessReview.mockResolvedValue([row({}), row({ user_id: "u2", username: "bob", email: "bob@x.io", decision: "certify" })]);
  decideAccessReview.mockResolvedValue({});
});

describe("AccessReviewPanel", () => {
  test("currentQuarter formats", () => {
    expect(currentQuarter(new Date("2026-11-13"))).toBe("2026-Q4");
    expect(currentQuarter(new Date("2026-02-01"))).toBe("2026-Q1");
  });

  test("loads and shows group, user, email, decision", async () => {
    render(<AccessReviewPanel />);
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(accessReview).toHaveBeenCalledWith(currentQuarter());
    expect(screen.getAllByText("media").length).toBeGreaterThan(0);
    expect(screen.getByText("alice@x.io")).toBeInTheDocument();
    expect(screen.getByText("Certified")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  test("certify posts decision and updates row", async () => {
    render(<AccessReviewPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /certify alice/i }));
    await waitFor(() => expect(decideAccessReview).toHaveBeenCalledWith({
      group_id: "g1", user_id: "u1", quarter: currentQuarter(), decision: "certify" }));
    await waitFor(() => expect(screen.queryByText("Pending")).toBeNull());
    expect(accessReview).toHaveBeenCalledTimes(1);
  });

  test("revoke asks for confirmation", async () => {
    render(<AccessReviewPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /revoke alice/i }));
    expect(decideAccessReview).not.toHaveBeenCalled();
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(within(dlg).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(decideAccessReview).toHaveBeenCalledWith(
      expect.objectContaining({ user_id: "u1", decision: "revoke" })));
    expect(await screen.findByText("Revoked")).toBeInTheDocument();
  });

  test("export link targets csv endpoint", async () => {
    render(<AccessReviewPanel />);
    await screen.findByText("alice");
    const a = screen.getByRole("link", { name: /export csv/i });
    expect(a.getAttribute("href")).toBe(`/api/access-review/export.csv?quarter=${currentQuarter()}`);
  });

  test("decision uses the row's quarter even if the input is edited", async () => {
    render(<AccessReviewPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /revoke alice/i }));
    const dlg = await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("Quarter"), { target: { value: "2025-Q1" } });
    fireEvent.click(within(dlg).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(decideAccessReview).toHaveBeenCalledWith(
      expect.objectContaining({ user_id: "u1", quarter: "2026-Q4" })));
  });

  test("409 refreshes rows", async () => {
    const err = new ApiError("Already decided this quarter", 409);
    decideAccessReview.mockRejectedValue(err);
    render(<AccessReviewPanel />);
    await screen.findByText("alice");
    fireEvent.click(screen.getByRole("button", { name: /certify alice/i }));
    await waitFor(() => expect(accessReview).toHaveBeenCalledTimes(2));
  });
});
