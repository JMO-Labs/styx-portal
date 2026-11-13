import { expect, test } from "@playwright/test";
import { ADMIN, apiCall, uiLogin } from "./helpers";

// Opening a desktop (pref "new_tab") lands on /desktop/:sub in a new tab with the slim toolbar.
test("desktop opens in a new tab with a slim toolbar", async ({ browser }) => {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await uiLogin(p, ADMIN);
  await expect(p.getByRole("button", { name: "Log out" })).toBeVisible();
  await apiCall(ctx, "PUT", "/api/auth/me/preferences", { open_workspaces: "new_tab" });
  const sub = "e2e-tab";
  await ctx.route("**/api/instances", (r) => r.fulfill({ json: [{ id: "e2e1", name: "E2E Desk", subdomain: sub, status: "running", template_id: "x" }] }));
  await p.goto("/");
  const [tab] = await Promise.all([ctx.waitForEvent("page"), p.evaluate((s) => window.open(`/desktop/${s}`, "_blank"), sub)]);
  await expect(tab).toHaveURL(new RegExp(`/desktop/${sub}$`));
  const bar = tab.getByRole("toolbar", { name: "Desktop controls" });
  await expect(bar).toBeVisible();
  expect((await bar.boundingBox())!.height).toBeLessThanOrEqual(40);
  for (const n of ["Fullscreen", "Disconnect", "Home"]) await expect(bar.getByRole(n === "Home" ? "link" : "button", { name: n })).toBeVisible();
  await tab.keyboard.press("Tab");
  await apiCall(ctx, "PUT", "/api/auth/me/preferences", { open_workspaces: null });
  await ctx.close();
});
