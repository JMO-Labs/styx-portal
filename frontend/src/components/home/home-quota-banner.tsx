import { AlertTriangle } from "lucide-react";
import type { HomeStorage } from "@/api/client";

const GB = 1024 ** 3;
const fmt = (b: number) => `${Number((b / GB).toFixed(1))} GB`;

export function HomeQuotaBanner({ data }: { data: HomeStorage | undefined }) {
  if (!data || !data.warn || data.used_bytes == null || data.quota_bytes == null || data.percent == null) return null;
  return (
    <div role="status" className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 text-sm text-foreground">
      <AlertTriangle aria-hidden="true" className="size-4 shrink-0 text-amber-500" />
      <span>Home storage {Math.round(data.percent)} % full ({fmt(data.used_bytes)} / {fmt(data.quota_bytes)})</span>
    </div>
  );
}
