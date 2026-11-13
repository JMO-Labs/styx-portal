import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, test, expect, vi } from "vitest";
import { expectNoSeriousA11y } from "@/test/axe";

const login = vi.fn().mockRejectedValue(new Error("bad"));
vi.mock("@/api/client", () => ({
  api: {
    oauthProviders: vi.fn().mockResolvedValue([]),
    setupRequired: vi.fn().mockResolvedValue({ setup_required: false }),
    setupPreflight: vi.fn().mockResolvedValue({
      docker: { ok: true, detail: "ok" }, data_writable: true, domain_set: true,
      runtime: "docker", deploy_mode: "local",
    }),
    login: (...a: unknown[]) => login(...a),
    acceptInvite: vi.fn().mockRejectedValue(new Error("Invite expired")),
    changePassword: vi.fn(),
  },
  withRetry: (fn: () => unknown) => fn(),
  ApiError: class extends Error {},
}));
vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ user: null, loading: false, setupRequired: true, refresh: vi.fn(), logout: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

import { LoginPage } from "../LoginPage";
import { SetupWizard } from "../SetupWizard";
import { ChangePasswordPage } from "../ChangePasswordPage";
import { AcceptInvitePage } from "../AcceptInvitePage";

function mount(ui: React.ReactNode) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/invite/tok"]}>
        <Routes><Route path="/invite/:token" element={ui} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("auth pages a11y", () => {
  test("LoginPage", async () => {
    const { container } = mount(<LoginPage />);
    await expectNoSeriousA11y(container);
  });
  test("SetupWizard", async () => {
    const { container } = mount(<SetupWizard />);
    await screen.findByText("Environment check");
    await expectNoSeriousA11y(container);
  });
  test("ChangePasswordPage", async () => {
    const { container } = mount(<ChangePasswordPage />);
    await expectNoSeriousA11y(container);
  });
  test("AcceptInvitePage", async () => {
    const { container } = mount(<AcceptInvitePage />);
    await expectNoSeriousA11y(container);
  });

  test("password show/hide toggle is keyboard reachable", () => {
    mount(<AcceptInvitePage />);
    expect(screen.getByRole("button", { name: "Show password" })).not.toHaveAttribute("tabindex", "-1");
  });

  test("Login error is alert linked to username and password", async () => {
    mount(<LoginPage />);
    fireEvent.change(screen.getByLabelText("Email or username"), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "b" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Email or username")).toHaveAttribute("aria-describedby", "login-error");
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-describedby", "login-error");
  });

  test("AcceptInvite error is alert linked to inputs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({}));
    mount(<AcceptInvitePage />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Xk9#vQ2!mZ7@pL4$wR8" } });
    fireEvent.click(screen.getByRole("button", { name: "Join" }));
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert).toHaveAttribute("id"));
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-describedby", expect.stringContaining(alert.id));
  });

  test("Setup error is alert linked to password", async () => {
    mount(<SetupWizard />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByLabelText("Setup code"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "abc" } });
    fireEvent.submit(screen.getByRole("button", { name: "Create admin" }).closest("form")!);
    const alert = await screen.findByRole("alert");
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-describedby", expect.stringContaining(alert.id));
  });

  test("ChangePassword field errors are announced", async () => {
    mount(<ChangePasswordPage />);
    fireEvent.change(screen.getByLabelText("Current Password"), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText("New Password", { selector: "input" }), { target: { value: "b" } });
    fireEvent.change(screen.getByLabelText("Confirm Password"), { target: { value: "c" } });
    fireEvent.submit(screen.getByLabelText("Confirm Password").closest("form")!);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Passwords do not match");
  });
});
