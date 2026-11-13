import { render, screen } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";

vi.mock("@/api/client", () => ({
  api: {
    listWorkstations: () => Promise.reject(new Error("load failed")),
    listUsers: () => Promise.resolve([]),
    workstationThumbUrl: (id: string) => `/t/${id}`,
  },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/components/system/workstation-icon", () => ({ WorkstationIcon: () => null }));

import { WorkstationsPanel } from "../workstations-panel";

describe("WorkstationsPanel error", () => {
  test("load failure is announced as an alert", async () => {
    render(<WorkstationsPanel />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/load failed/);
  });
});
