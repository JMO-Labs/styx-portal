import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { a, nav } = vi.hoisted(() => ({ a: { smartcardToken: vi.fn() }, nav: vi.fn() }));
vi.mock("@/api/client", () => ({ api: a }));
vi.mock("@/lib/navigate", () => ({ navigateTo: nav }));

import { SmartcardConnect, cardUrl } from "../smartcard-connect";

describe("SmartcardConnect", () => {
  beforeEach(() => { a.smartcardToken.mockReset(); nav.mockReset(); });

  it("builds the styx-card URL with encoded params", () => {
    expect(cardUrl("h.example", "a b")).toBe("styx-card://connect?host=h.example&token=a%20b");
  });

  it("mints a token and navigates to styx-card://", async () => {
    a.smartcardToken.mockResolvedValue({ token: "tok123", host: "desk.example" });
    render(<SmartcardConnect instanceId="i1" />);
    fireEvent.click(screen.getByRole("button", { name: /connect smart card/i }));
    await waitFor(() => expect(nav).toHaveBeenCalledWith("styx-card://connect?host=desk.example&token=tok123"));
    expect(a.smartcardToken).toHaveBeenCalledWith("i1");
    expect(document.body.innerHTML).not.toContain("tok123");
  });

  it("shows an inline error and does not navigate", async () => {
    a.smartcardToken.mockRejectedValue(new Error("nope"));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<SmartcardConnect instanceId="i1" />);
    fireEvent.click(screen.getByRole("button", { name: /connect smart card/i }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("nope"));
    expect(nav).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });

  it("links help to the install runbook", () => {
    render(<SmartcardConnect instanceId="i1" />);
    expect(screen.getByRole("link", { name: /install/i }).getAttribute("href")).toContain("smartcard");
  });
});
