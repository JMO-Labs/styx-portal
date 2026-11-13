import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBranding, _resetBranding } from "./branding";

function Probe() {
  const b = useBranding();
  return <span>{b.brand_name}</span>;
}

describe("useBranding", () => {
  beforeEach(() => {
    _resetBranding();
    document.documentElement.removeAttribute("style");
  });

  it("fetches once, exposes brand_name and sets --accent", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ brand_name: "Acme", brand_logo_url: null, brand_accent: "#1d4ed8" }) });
    vi.stubGlobal("fetch", f);
    render(<><Probe /><Probe /></>);
    await waitFor(() => expect(screen.getAllByText("Acme")).toHaveLength(2));
    expect(f).toHaveBeenCalledTimes(1);
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("#1d4ed8");
  });

  it("leaves default accent when contrast is too low", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ brand_name: "X", brand_logo_url: null, brand_accent: "#7f7f7f" }) }));
    render(<Probe />);
    await waitFor(() => screen.getByText("X"));
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe("");
  });

  it("falls back to defaults when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<Probe />);
    await waitFor(() => screen.getByText("STYX PORTAL"));
  });
});
