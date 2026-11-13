import { expect, test } from "@playwright/test";
import { ADMIN, uiLogin } from "./helpers";

test("My account page renders its sections and is reachable from the user menu", async ({ page }) => {
  await uiLogin(page, ADMIN);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("menuitem", { name: "My account" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { name: "My account" })).toBeVisible();
  for (const name of ["Storage", "Profiles", "Sessions"]) {
    await expect(page.getByRole("heading", { name, level: 2 })).toBeVisible();
  }
});
