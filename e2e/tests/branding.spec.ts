import { expect, test } from "@playwright/test";
import { ADMIN, uiLogin } from "./helpers";

const BRAND = { brand_name: "Acme Cloud", brand_logo_url: null, brand_accent: "#1d4ed8" };

test("branding: brand name on login + header, accent applied, dark mode via user menu", async ({ page }) => {
  await page.route("**/api/branding", (r) => r.fulfill({ json: BRAND }));
  await page.goto("/login");
  await expect(page.getByTestId("login-logo")).toContainText("Acme Cloud");
  await uiLogin(page, ADMIN);
  await expect(page.locator(".styx-logo")).toContainText("Acme Cloud");
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--accent"))).toBe("#1d4ed8");

  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
