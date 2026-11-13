import { expect, test } from "@playwright/test";
import { ADMIN, uiLogin } from "./helpers";

test("users list opens detail; policy editor is editable for platform-admin", async ({ page }) => {
  await uiLogin(page, ADMIN);
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(ADMIN.username) }).first().click();
  await expect(page).toHaveURL(/\/admin\/users\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Groups" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();

  await page.goto("/admin/policy");
  await expect(page.getByRole("heading", { name: "Policy" })).toBeVisible();
  await expect(page.getByText(/Read-only/)).toHaveCount(0);
  await expect(page.locator("fieldset.grp").first()).toBeVisible();
});
