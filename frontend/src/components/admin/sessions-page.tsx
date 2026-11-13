import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { NoAccess } from "./no-access";
import { isForbidden } from "./forbidden";

const when = (s: string | null) => (s ? new Date(s.endsWith("Z") || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "—");

export function SessionsPage() {
  const { data, error, isPending } = useQuery({
    queryKey: ["admin-console", "sessions"], queryFn: api.adminSessions, refetchInterval: 15_000,
  });
  if (isForbidden(error)) return <NoAccess />;
  const rows = data?.sessions ?? [];
  return (
    <section aria-label="Sessions" className="space-y-3">
      <h1 className="text-xl font-semibold">Live sessions</h1>
      {error ? <p role="alert" className="text-sm text-destructive">Couldn't load sessions.</p>
        : isPending ? <p className="text-sm text-muted-foreground">Loading…</p>
        : !rows.length ? <p className="text-sm text-muted-foreground">No running sessions.</p>
        : (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-left text-sm">
              <thead className="text-muted-foreground"><tr>
                {["Owner", "Template", "Image", "Started", "Node"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="px-3 py-2">{r.owner ?? "—"}</td><td className="px-3 py-2">{r.template}</td>
                  <td className="px-3 py-2 font-mono text-xs">{r.image}</td><td className="px-3 py-2">{when(r.started_at)}</td>
                  <td className="px-3 py-2">{r.node ?? "unknown"}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
    </section>
  );
}
