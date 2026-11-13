import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Tile } from "@/components/system/overview-tiles";
import { NoAccess } from "./no-access";
import { isForbidden } from "./forbidden";

export function CapacityPage() {
  const { data, error, isPending } = useQuery({
    queryKey: ["admin-console", "capacity"], queryFn: api.adminCapacity, refetchInterval: 15_000,
  });
  if (isForbidden(error)) return <NoAccess />;
  if (error) return <p role="alert" className="text-sm text-destructive">Couldn't load capacity.</p>;
  if (isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <section aria-label="Capacity" className="space-y-4">
      <h1 className="text-xl font-semibold">Capacity</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fit,minmax(170px,1fr))]">
        <Tile title="Running" value={String(data.running)} note={data.limit ? `of ${data.limit} total` : "No global limit"} />
        <Tile title="Live streams" value={String(data.live_streams)} note="Open stream sessions" />
        <Tile title="Per-user limit" value={data.max_per_user ? String(data.max_per_user) : "—"} note="Instances per user" />
        {Object.entries(data.per_node).map(([n, c]) => <Tile key={n} title={`Node ${n}`} value={String(c)} note="Running instances" />)}
      </div>
    </section>
  );
}
