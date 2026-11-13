import { render } from "@testing-library/react";
import { expect, test, vi } from "vitest";
vi.mock("@/components/effects/wave-transition", () => ({
  WaveTransition: ({ label }: { label: string }) => <p>{label}</p>,
}));
import { ConnectingPage } from "../ConnectingPage";
import { expectNoSeriousA11y } from "@/test/axe";

test("ConnectingPage has no serious axe violations", async () => {
  Object.defineProperty(window, "location", { configurable: true,
    value: { origin: "http://localhost", hash: "#" + encodeURIComponent(JSON.stringify({ label: "Connecting to Box…" })), replace: vi.fn() } });
  const { container } = render(<ConnectingPage />);
  await expectNoSeriousA11y(container);
  expect(container).toBeTruthy();
});
