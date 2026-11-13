import { describe, it, expect } from "vitest";
import { contrastRatio, resolveAccent } from "./contrast";

describe("contrastRatio", () => {
  it("black on white is 21", () => expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 0));
  it("accepts 3-digit hex", () => expect(contrastRatio("#fff", "#000")).toBeCloseTo(21, 0));
});

describe("resolveAccent", () => {
  it("keeps a dark accent with white text", () =>
    expect(resolveAccent("#1d4ed8")).toEqual({ accent: "#1d4ed8", foreground: "#ffffff" }));
  it("uses dark text on a light accent", () =>
    expect(resolveAccent("#facc15")).toEqual({ accent: "#facc15", foreground: "#0f1c22" }));
  it("falls back when neither text colour reaches 4.5:1", () =>
    expect(resolveAccent("#7f7f7f")).toBeNull());
  it("falls back on empty or invalid values", () => {
    expect(resolveAccent(null)).toBeNull();
    expect(resolveAccent("red")).toBeNull();
    expect(resolveAccent("url(x)")).toBeNull();
  });
});
