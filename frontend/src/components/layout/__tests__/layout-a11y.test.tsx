import { render } from "@testing-library/react";
import { describe, it, vi } from "vitest";
import { Header } from "../header";
import { TooltipProvider } from "@/components/ui/tooltip";
import { expectNoSeriousA11y } from "@/test/axe";

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ user: { username: "alice", role: "admin" }, logout: vi.fn() }),
}));
vi.mock("@/components/layout/opening-menu", () => ({ OpeningMenu: () => null }));
vi.mock("@/theme/ThemeProvider", () => ({ useTheme: () => ({ theme: "dark", setTheme: vi.fn() }) }));

describe("layout a11y", () => {
  it("header/nav has no serious axe violations", async () => {
    const { container } = render(<TooltipProvider><Header activeTab="home" onTabChange={vi.fn()} /></TooltipProvider>);
    await expectNoSeriousA11y(container);
  });
});
