import { expect, test } from "@playwright/test";
import { MEMBER, uiLogin } from "./helpers";
import { mockApi } from "./shots-mocks";

test("home renders My desktops, My services and Announcements", async ({ page }) => {
  await mockApi(page, "GET", "/api/announcements/active", [
    { id: "a1", title: "Patch night", body: "Friday 22:00", kind: "maintenance", starts_at: "2026-11-01T00:00:00Z", ends_at: null },
  ]);
  await uiLogin(page, MEMBER);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("region", { name: "My desktops" })).toBeVisible();
  await expect(page.getByRole("region", { name: "My services" })).toBeVisible();
  const ann = page.getByRole("region", { name: "Announcements" });
  await expect(ann).toBeVisible();
  await expect(ann.getByText("Patch night")).toBeVisible();
});
