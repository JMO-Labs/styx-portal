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
  const [tab] = await Promise.all([ctx.waitForEvent("page"), p.getByRole("button", { name: "Connect E2E Desk" }).click()]);
  await tab.waitForURL(new RegExp(`/desktop/${sub}$`)); // may pass through /connecting
  const bar = tab.getByRole("toolbar", { name: "Desktop controls" });
  await expect(bar).toBeVisible();
  expect((await bar.boundingBox())!.height).toBeLessThanOrEqual(40);
  for (const n of ["Fullscreen", "Disconnect", "Home"]) await expect(bar.getByRole(n === "Home" ? "link" : "button", { name: n })).toBeVisible();
  // Keyboard: Tab reaches each control in order, each with a visible focus ring.
  await bar.evaluate((el) => (el.ownerDocument.activeElement as HTMLElement | null)?.blur());
  for (const [role, name] of [["button", "Fullscreen"], ["button", "Disconnect"], ["link", "Home"]] as const) {
    await tab.keyboard.press("Tab");
    const ctl = bar.getByRole(role, { name });
    await expect(ctl).toBeFocused();
    expect(await ctl.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe("none");
  }
  await apiCall(ctx, "PUT", "/api/auth/me/preferences", { open_workspaces: null });
  await ctx.close();
});
