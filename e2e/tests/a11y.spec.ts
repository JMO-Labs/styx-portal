import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFileSync, mkdirSync } from "node:fs";
import { ADMIN, setupCode, uiLogin } from "./helpers";
import { INSTANCES, WORKSTATIONS, mockApi } from "./shots-mocks";

const OUT = "screenshots/a11y";
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
// Keep in sync with mobile-audit.spec.ts SECTIONS.
const SECTIONS = ["overview", "health", "sessions", "logs", "users", "sso", "workstations", "services", "images", "streaming",
  "security", "timeouts", "signin-card", "connected", "profiles"];

type Violation = { page: string; id: string; impact: string | null | undefined; help: string; targets: string[] };
const all: Violation[] = [];

const isBlocking = (v: { impact?: string | null }) => v.impact === "serious" || v.impact === "critical";

function formatFailure(blocking: Violation[]): string {
  return blocking.map((v) => `[${v.page}] ${v.id} (${v.impact}): ${v.targets.join(" | ")}`).join("\n");
}

async function scan(page: Page, name: string) {
  await page.waitForTimeout(400);
  const res = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  for (const v of res.violations)
    all.push({ page: name, id: v.id, impact: v.impact, help: v.help, targets: v.nodes.map((n) => n.target.join(" ")) });
}

test("a11y: axe scan of every routed page", async ({ page }) => {
  mkdirSync(OUT, { recursive: true });
  await page.goto("/");
  await page.waitForURL(/\/(setup|login)$/);
  if (page.url().endsWith("/setup")) {
    await scan(page, "/setup");
    await page.locator("#username").fill(ADMIN.username);
    await page.locator("#setup-code").fill(setupCode());
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Create admin" }).click();
    await page.waitForURL((u) => !u.pathname.endsWith("/setup"));
    await page.context().clearCookies();
  } else {
    await page.goto("/setup");
    await scan(page, "/setup");
  }
  await page.goto("/login");
  await scan(page, "/login");
  await page.goto("/accept-invite/a11y-token");
  await scan(page, "/accept-invite/<token>");

  await uiLogin(page, ADMIN);
  await page.waitForURL((u) => !u.pathname.endsWith("/login"));
  await mockApi(page, "GET", "/api/instances", INSTANCES);
  await mockApi(page, "GET", "/api/workstations/mine", WORKSTATIONS);
  for (const path of ["/change-password", "/connecting"]) {
    await page.goto(path);
    await scan(page, path);
  }
  await page.goto("/");
  await page.waitForTimeout(800);
  await scan(page, "/");
  await page.getByRole("button", { name: "Admin", exact: true }).click();
  await page.waitForTimeout(600);
  for (const id of SECTIONS) {
    await page.evaluate((i) => window.dispatchEvent(new CustomEvent("styx:settings-section", { detail: i })), id);
    await scan(page, `settings:${id}`);
  }
  await page.goto("/shell.html");
  await scan(page, "/shell.html");

  writeFileSync(`${OUT}/report.json`, JSON.stringify(all, null, 1));
  const blocking = all.filter(isBlocking);
  expect(blocking, `serious/critical a11y violations:\n${formatFailure(blocking)}`).toEqual([]);
});
