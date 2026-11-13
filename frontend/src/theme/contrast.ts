const LIGHT_TEXT = "#ffffff";
const DARK_TEXT = "#0f1c22";
const MIN_RATIO = 4.5;

function parse(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  let h = m[1]!;
  if (h.length === 3) h = [...h].map((c) => c + c).join("");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

function luminance([r, g, b]: [number, number, number]): number {
  const [R, G, B] = [r, g, b].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

/** WCAG contrast ratio between two hex colours (NaN if either is invalid). */
export function contrastRatio(a: string, b: string): number {
  const pa = parse(a), pb = parse(b);
  if (!pa || !pb) return NaN;
  const [hi, lo] = [luminance(pa), luminance(pb)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Valid brand accent plus readable text colour, or null → keep the default accent. */
export function resolveAccent(accent: string | null | undefined): { accent: string; foreground: string } | null {
  if (!accent || !parse(accent)) return null;
  for (const fg of [LIGHT_TEXT, DARK_TEXT]) {
    if (contrastRatio(accent, fg) >= MIN_RATIO) return { accent: accent.trim(), foreground: fg };
  }
  return null;
}
