import { Waves } from "lucide-react";
import type { Branding } from "@/theme/branding";

/** Org logo (or the default waves icon) for the header and login page. */
export function BrandMark({ b, className }: { b: Branding; className: string }) {
  return b.brand_logo_url
    ? <img src={b.brand_logo_url} alt="" className={className} />
    : <Waves className={className} aria-hidden style={{ color: "var(--brand-accent)" }} />;
}
