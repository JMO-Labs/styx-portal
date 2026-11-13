import { expect, test } from "@playwright/test";
import { ADMIN, MEMBER, uiLogin } from "./helpers";

test("staff (portal admin) sees Sessions and Capacity", async ({ page }) => {
  await uiLogin(page, ADMIN);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("menuitem", { name: "Admin console" }).click();
  await expect(page).toHaveURL(/\/admin\/sessions$/);
  await expect(page.getByRole("heading", { name: "Live sessions" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Admin console" });
  for (const n of ["Sessions", "Capacity", "Users", "Policy", "Announcements"])
    await expect(nav.getByRole("link", { name: n })).toBeVisible();
  await nav.getByRole("link", { name: "Capacity" }).click();
  await expect(page.getByRole("heading", { name: "Capacity" })).toBeVisible();
  await expect(page.getByText("Running", { exact: true })).toBeVisible();
});

test("ordinary user has no menu link and gets No access", async ({ page }) => {
  await uiLogin(page, MEMBER);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.getByRole("button", { name: /account menu/i }).click();
  await expect(page.getByRole("menuitem", { name: "My account" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Admin console" })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "No access" })).toBeVisible();
});
