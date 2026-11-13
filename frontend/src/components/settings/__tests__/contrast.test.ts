import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TOKENS, contrast } from "@/styles/tokens";

// Contrast audit for settings/system/charts (WCAG 1.4.3 text 4.5:1, 1.4.11 UI 3:1).
const css = readFileSync("src/styles/globals.css", "utf8").toLowerCase();
const block = (re: RegExp) => re.exec(css)![0];
const tok = (blk: string, name: string) => new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`).exec(blk)![1]!;
const MODES = [
  ["light", block(/:root\s*\{[^}]*\}/), TOKENS.light],
  ["dark", block(/\.dark\s*\{[^}]*\}/), TOKENS.dark],
] as const;

const walk = (d: string): string[] => readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? (e.name === "__tests__" ? [] : walk(`${d}/${e.name}`)) : [`${d}/${e.name}`]);
const files = ["settings", "system", "charts"].flatMap((d) => walk(`src/components/${d}`));

describe("settings token contrast", () => {
  for (const [mode, blk, t] of MODES) {
    for (const [surface, bg] of [["background", t.background], ["card", t.card]] as const) {
      it(`${mode}: text tokens on ${surface} ≥ 4.5:1`, () => {
        for (const fg of [t.foreground, t.mutedForeground, t.destructive, t.primary]) {
          expect(contrast(fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
        }
      });
      it(`${mode}: input border and focus ring on ${surface} ≥ 3:1`, () => {
        for (const ui of [tok(blk, "input"), tok(blk, "ring")]) {
          expect(contrast(ui, bg), `${ui} on ${bg}`).toBeGreaterThanOrEqual(3);
        }
      });
    }
  }
});

describe("settings/system/charts classes", () => {
  // Tailwind rose-400 (~2.5:1) and red-500 (~3.3:1) fail on the light surfaces;
  // muted-foreground at 60% opacity drops below 4.5:1. Use the theme tokens.
  const BAD = /text-rose-400|text-red-500|text-muted-foreground\/60/;
  it.each(files)("%s avoids low-contrast text classes", (f) => {
    expect(readFileSync(f, "utf8")).not.toMatch(BAD);
  });
});

describe("form control borders", () => {
  // `border` is below 3:1 (WCAG 1.4.11); <select>/<input> must use `border-input`.
  const BAD_CONTROL = /<(?:select|input)\b(?:=>|[^>])*?\bborder-border\b/;
  it.each(files)("%s form controls use border-input", (f) => {
    expect(readFileSync(f, "utf8")).not.toMatch(BAD_CONTROL);
  });
});
