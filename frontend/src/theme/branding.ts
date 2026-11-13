import { useEffect, useState } from "react";
import { resolveAccent } from "./contrast";

export type Branding = { brand_name: string; brand_logo_url: string | null; brand_accent: string | null };

export const DEFAULT_BRANDING: Branding = { brand_name: "STYX PORTAL", brand_logo_url: null, brand_accent: null };

let pending: Promise<Branding> | null = null;

/** Test hook: forget the cached fetch. */
export function _resetBranding() { pending = null; }

function applyAccent(accent: string | null) {
  const s = document.documentElement.style;
  const r = resolveAccent(accent);
  if (!r) { s.removeProperty("--accent"); s.removeProperty("--accent-foreground"); return; }
  s.setProperty("--accent", r.accent);
  s.setProperty("--accent-foreground", r.foreground);
}

/** GET /api/branding exactly once per page load; failures fall back to defaults. */
function load(): Promise<Branding> {
  pending ??= fetch("/api/branding")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((d: Partial<Branding>) => {
      const b = { ...DEFAULT_BRANDING, brand_name: d.brand_name || DEFAULT_BRANDING.brand_name, brand_logo_url: d.brand_logo_url ?? null, brand_accent: d.brand_accent ?? null };
      applyAccent(b.brand_accent);
      return b;
    })
    .catch(() => DEFAULT_BRANDING);
  return pending;
}

export function useBranding(): Branding {
  const [b, setB] = useState<Branding>(DEFAULT_BRANDING);
  useEffect(() => {
    let live = true;
    load().then((v) => { if (live) setB(v); });
    return () => { live = false; };
  }, []);
  return b;
}
