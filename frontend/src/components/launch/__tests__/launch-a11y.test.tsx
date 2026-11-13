import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext, type AuthUser } from "@/auth/AuthContext";
import { NewContainerDrawer } from "../new-container-drawer";

const m = vi.hoisted(() => ({
  listRegistryImages: vi.fn(), listTemplates: vi.fn(), getSizePresets: vi.fn(),
  createTemplate: vi.fn(), createInstance: vi.fn(), updateTemplate: vi.fn(), listInstances: vi.fn(), getRuntime: vi.fn(),
}));
vi.mock("@/api/client", () => ({ api: m }));
vi.mock("@/components/effects/transition-provider", () => ({ useWaveTransition: () => ({ play: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const img = (name: string, category: string) => ({
  name, description: `${name} desc`, project_logo: "", category, stars: 1, monthly_pulls: 1, version: "1", stable: true,
  tags: [{ tag: "latest", desc: "" }], config: { env_vars: [], volumes: [{ path: "/config", host_path: "", desc: "", optional: false }], ports: [] },
  architectures: [], github_url: "", project_url: "",
});
const presets = [
  { id: "light", label: "Light", cpus: 2, memory_gb: 2, gpu: false },
  { id: "standard", label: "Standard", cpus: 4, memory_gb: 4, gpu: false },
  { id: "heavy", label: "Heavy", cpus: 6, memory_gb: 8, gpu: true },
];
const setup = { id: "s1", name: "chrome-gpu", display_name: "Chrome GPU", image: "lscr.io/linuxserver/chromium:latest", icon: "", session_config: {}, gpu_enabled: true, volumes: [{ name: "v", mount: "/config" }], profile_mount: "/config", cpu_limit: "4", memory_limit: "4g" };

function wrap(role: string, onClose = vi.fn(), gpu = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const auth = { user: { id: "u", username: "u", email: "u@x", role, can_use_gpu: gpu } as AuthUser, loading: false, setupRequired: false, refresh: vi.fn(), logout: vi.fn() };
  render(<QueryClientProvider client={qc}><AuthContext.Provider value={auth}><NewContainerDrawer open onClose={onClose} /></AuthContext.Provider></QueryClientProvider>);
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
  m.listRegistryImages.mockResolvedValue([img("firefox", "Browsers"), img("gimp", "Creative")]);
  m.listTemplates.mockResolvedValue([setup]);
  m.getSizePresets.mockResolvedValue(presets);
  m.createTemplate.mockImplementation(async (d) => ({ ...d, id: "t1" }));
  m.listInstances.mockResolvedValue([{ id: "x", name: "Chrome GPU", subdomain: "chrome-gpu" }]);
  m.getRuntime.mockResolvedValue({ runtime: "docker" });
  m.createInstance.mockResolvedValue({ id: "i1" });
});

import { expectNoSeriousA11y } from "@/test/axe";

describe("launch dialog a11y", () => {
  test("no serious axe violations", async () => {
    wrap("user");
    await screen.findByLabelText(/search linuxserver/i);
    await expectNoSeriousA11y(document.body);
  });

  test("launch step has no violations; empty name shows a linked alert", async () => {
    wrap("user");
    fireEvent.click(await screen.findByText("firefox"));
    const name = await screen.findByLabelText("Name");
    await expectNoSeriousA11y(document.body);
    fireEvent.change(name, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /^launch$/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/name and image required/i);
    expect(name).toHaveAttribute("aria-describedby", alert.id);
    expect(name).toHaveAttribute("aria-invalid", "true");
    await expectNoSeriousA11y(document.body);
  });
});
