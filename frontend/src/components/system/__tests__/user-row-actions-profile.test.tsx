import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

const { a } = vi.hoisted(() => ({ a: { systemProfile: vi.fn() } }));
vi.mock("@/api/client", () => ({ api: a }));

import { UserRowActions, type UserActions } from "../user-row-actions";
import type { UserRow } from "../users-filters";

const u = { id: "1", username: "pat", has_matrix_card: true } as unknown as UserRow;
const acts = new Proxy({}, { get: () => vi.fn() }) as UserActions;

async function menu() {
  render(<UserRowActions u={u} locked={false} a={acts} />);
  await waitFor(() => expect(a.systemProfile).toHaveBeenCalled());
  fireEvent.keyDown(await screen.findByRole("button", { name: "More actions for pat" }), { key: "Enter" });
  await screen.findByRole("menuitem", { name: /Groups/ });
}

test("enterprise hides password and sign-in card actions (ADR-0053)", async () => {
  a.systemProfile.mockResolvedValue({ profile: "enterprise", disabled: ["password_login", "matrix_2fa"] });
  await menu();
  await waitFor(() => expect(screen.queryByText(/Reset password/)).toBeNull());
  expect(screen.queryByText(/Force password change/)).toBeNull();
  expect(screen.queryByText(/Reset sign-in card/)).toBeNull();
});

test("homelab keeps them", async () => {
  a.systemProfile.mockResolvedValue({ profile: "homelab", disabled: [] });
  await menu();
  expect(screen.getAllByText(/Reset password/).length).toBeGreaterThan(0);
  expect(screen.getByText(/Reset sign-in card/)).toBeTruthy();
});
