import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useInstances = vi.fn();
const mutate = vi.fn();
vi.mock("@/hooks/use-instances", () => ({ useInstances: () => useInstances(), useKeepalive: () => ({ mutate }) }));
vi.mock("@/lib/activity", () => ({ startActivityHeartbeat: () => () => {} }));
const useTemplates = vi.fn(() => ({ data: [{ id: "t1", icon: "🌐" }] }));
vi.mock("@/hooks/use-templates", () => ({ useTemplates: () => useTemplates() }));
vi.mock("@/lib/stream-thumb", () => ({ startThumbUploader: () => () => {} }));

import { DesktopPage, faviconHref } from "../DesktopPage";

const inst = (status: string, extra = {}) =>
  ({ id: "i1", name: "My Desk", subdomain: "desk", status, ...extra });

function renderAt(list: unknown[] | undefined, pending = false) {
  useInstances.mockReturnValue({ data: list, isPending: pending });
  return render(
    <MemoryRouter initialEntries={["/desktop/desk"]}>
      <Routes><Route path="/desktop/:sub" element={<DesktopPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe("DesktopPage", () => {
  beforeEach(() => { useInstances.mockReset(); mutate.mockReset(); });

  it("mounts the iframe when running", () => {
    renderAt([inst("running")]);
    const f = screen.getByTitle("My Desk") as HTMLIFrameElement;
    expect(f.getAttribute("src")).toBe("/i/desk/");
    expect(f.hasAttribute("sandbox")).toBe(false);
  });

  it("sets the tab icon from the template and restores it on unmount", () => {
    const link = document.createElement("link");
    link.rel = "icon"; link.href = "http://localhost/favicon.svg";
    document.head.appendChild(link);
    const { unmount } = renderAt([inst("running", { template_id: "t1" })]);
    expect(link.href).toBe(faviconHref("🌐"));
    unmount();
    expect(link.href).toBe("http://localhost/favicon.svg");
    link.remove();
  });

  it("faviconHref passes URLs through", () => {
    expect(faviconHref("/api/x.png")).toBe("/api/x.png");
    expect(faviconHref(null)).toBeNull();
  });

  it("does not mount the iframe while starting, shows detail", () => {
    renderAt([inst("pulling", { status_detail: "Pulling 40%" })]);
    expect(screen.queryByTitle("My Desk")).toBeNull();
    expect(screen.getByText("Pulling 40%")).toBeTruthy();
  });

  it("shows not found for an unknown subdomain", () => {
    renderAt([]);
    expect(screen.getByText("Desktop not found")).toBeTruthy();
  });

  it("shows the idle banner and keeps alive on click", () => {
    renderAt([inst("idle")]);
    expect(screen.getByText(/Pausing soon/)).toBeTruthy();
    fireEvent.click(screen.getByText("I'm here"));
    expect(mutate).toHaveBeenCalledWith("i1", expect.anything());
  });

  it("no banner when running", () => {
    renderAt([inst("running")]);
    expect(screen.queryByText(/Pausing soon/)).toBeNull();
  });

  describe("toolbar", () => {
    it("shows name, fullscreen, disconnect and a back-to-home link", () => {
      renderAt([inst("running")]);
      const bar = screen.getByRole("toolbar", { name: "Desktop controls" });
      expect(bar.textContent).toContain("My Desk");
      expect(screen.getByRole("link", { name: /Home/ }).getAttribute("href")).toBe("/");
      expect(screen.getByRole("button", { name: /Fullscreen/ })).toBeTruthy();
      expect(screen.getByRole("button", { name: /Disconnect/ })).toBeTruthy();
    });

    it("fullscreen button requests fullscreen on the document", () => {
      renderAt([inst("running")]);
      const req = vi.fn();
      document.documentElement.requestFullscreen = req;
      fireEvent.click(screen.getByRole("button", { name: /Fullscreen/ }));
      expect(req).toHaveBeenCalled();
    });

    it("disconnect closes the tab", () => {
      renderAt([inst("running")]);
      const close = vi.spyOn(window, "close").mockImplementation(() => {});
      fireEvent.click(screen.getByRole("button", { name: /Disconnect/ }));
      expect(close).toHaveBeenCalled();
    });

    it("is at most 40px high and the iframe fills the rest", () => {
      renderAt([inst("running")]);
      expect(screen.getByRole("toolbar").className).toContain("h-10");
      expect(screen.getByTitle("My Desk").className).toContain("flex-1");
    });

    it("home link navigates to /", () => {
      useInstances.mockReturnValue({ data: [inst("running")], isPending: false });
      render(
        <MemoryRouter initialEntries={["/desktop/desk"]}>
          <Routes>
            <Route path="/desktop/:sub" element={<DesktopPage />} />
            <Route path="/" element={<p>home page</p>} />
          </Routes>
        </MemoryRouter>,
      );
      fireEvent.click(screen.getByRole("link", { name: /Home/ }));
      expect(screen.getByText("home page")).toBeTruthy();
    });
  });
});
