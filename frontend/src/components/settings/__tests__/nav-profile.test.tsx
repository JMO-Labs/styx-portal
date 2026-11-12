import { expect, test, vi } from "vitest";
vi.mock("../section-panels", () => ({ OverviewPane: () => null, PeoplePane: () => null, SecurityPane: () => null, TimeoutsPane: () => null, StreamingPane: () => null }));
vi.mock("@/components/system/relay-cost-page", () => ({ RelayCostPage: () => null }));
vi.mock("@/components/system/metrics-sessions", () => ({ MetricsSessions: () => null }));
vi.mock("@/components/system/metrics-logs", () => ({ MetricsLogs: () => null }));
vi.mock("@/components/system/health-panel", () => ({ HealthPanel: () => null }));
vi.mock("@/components/system/services-panel", () => ({ ServicesPanel: () => null }));
vi.mock("@/components/system/workstations-panel", () => ({ WorkstationsPanel: () => null }));
vi.mock("@/components/system/oauth-providers-panel", () => ({ OAuthProvidersPanel: () => null }));
vi.mock("@/components/system/image-manager", () => ({ ImageManager: () => null }));
vi.mock("@/components/system/connected-accounts", () => ({ ConnectedAccounts: () => null }));
vi.mock("../my-profiles", () => ({ MyProfiles: () => null }));
vi.mock("../matrix-card", () => ({ MatrixCard: () => null }));
import { visibleCategories } from "../nav-config";

const ids = (disabled: string[]) =>
  visibleCategories(true, { cfAnalytics: false, disabled }).flatMap((c) => c.sections.map((s) => s.id));

test("enterprise-disabled features drop their settings sections (ADR-0053)", () => {
  const gated = ["sso", "connected", "workstations", "images", "signin-card"];
  for (const id of gated) expect(ids([])).toContain(id);
  const off = ids(["password_login", "matrix_2fa", "generic_oidc", "workstation_enrollment", "docker_routers"]);
  for (const id of gated) expect(off).not.toContain(id);
  expect(off).toContain("users");
  expect(off).toContain("services");
});
