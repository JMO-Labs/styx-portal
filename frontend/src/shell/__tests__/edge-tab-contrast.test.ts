import { expect, test } from "vitest";
import { EDGE_IDLE_OPACITY, EDGE_OUTLINE } from "../edge-tab-style";

const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
};
const ratio = (a: string, b: string) => {
  const [lo, hi] = [lum(a), lum(b)].sort((x, y) => x - y);
  return (hi! + 0.05) / (lo! + 0.05);
};

// WCAG 1.4.11: the edge tab is the only visible sign of the control, so its opaque
// outline must reach 3:1 against any app page, white or black, in either theme.
test.each(["#FFFFFF", "#000000"])("edge tab outline keeps 3:1 against %s", (bg) => {
  expect(ratio(EDGE_OUTLINE, bg)).toBeGreaterThanOrEqual(3);
});

test("idle fade is a named, partial opacity (outline is not faded)", () => {
  expect(EDGE_IDLE_OPACITY).toBeGreaterThan(0);
  expect(EDGE_IDLE_OPACITY).toBeLessThan(1);
});
