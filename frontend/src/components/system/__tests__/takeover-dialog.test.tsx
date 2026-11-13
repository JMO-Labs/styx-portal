import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const startTakeover = vi.fn(() => Promise.resolve({}));
const endTakeover = vi.fn(() => Promise.resolve());
vi.mock("@/api/client", () => ({ api: { startTakeover: (...a: unknown[]) => startTakeover(...(a as [])),
  endTakeover: (...a: unknown[]) => endTakeover(...(a as [])) } }));
const openPending = vi.fn((_m: string, _l: string, get: () => Promise<string>) => get().then(() => undefined));
vi.mock("@/lib/connect-wipe", () => ({ openPending: (...a: unknown[]) => openPending(...(a as [string, string, () => Promise<string>])) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
import { TakeoverDialog, endTakeoverFor } from "../takeover-dialog";

const inst = { id: "7", name: "Desk", subdomain: "desk" };
const show = (onStarted = vi.fn()) =>
  render(<TakeoverDialog open instance={inst} onOpenChange={() => {}} onStarted={onStarted} />);
beforeEach(() => vi.clearAllMocks());

test("reason is required", () => {
  show();
  const go = screen.getByRole("button", { name: "Start takeover" });
  expect(go).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/ticket/i), { target: { value: "   " } });
  expect(go).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/ticket/i), { target: { value: "INC-42" } });
  expect(go).toBeEnabled();
});

test("defaults to View and opens the #shared client", async () => {
  const onStarted = vi.fn();
  show(onStarted);
  fireEvent.change(screen.getByLabelText(/ticket/i), { target: { value: " INC-42 " } });
  fireEvent.click(screen.getByRole("button", { name: "Start takeover" }));
  await waitFor(() => expect(onStarted).toHaveBeenCalled());
  expect(startTakeover).toHaveBeenCalledWith("7", { mode: "view", reason: "INC-42" });
  expect(await openPending.mock.calls[0]![2]()).toBe("/desktop/desk#shared");
});

test("Control opens the normal client", async () => {
  show();
  fireEvent.click(screen.getByRole("radio", { name: /control/i }));
  fireEvent.change(screen.getByLabelText(/ticket/i), { target: { value: "r" } });
  fireEvent.click(screen.getByRole("button", { name: "Start takeover" }));
  await waitFor(() => expect(startTakeover).toHaveBeenCalledWith("7", { mode: "control", reason: "r" }));
  expect(await openPending.mock.calls[0]![2]()).toBe("/desktop/desk");
});

test("end takeover calls DELETE", async () => {
  await endTakeoverFor("7");
  expect(endTakeover).toHaveBeenCalledWith("7");
});
