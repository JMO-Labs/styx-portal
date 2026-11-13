import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api } from "@/api/client";
import { NoAccess } from "./no-access";
import { isForbidden } from "./forbidden";

const when = (s: string | null) => (s ? new Date(s.endsWith("Z") || /[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "—");
const gb = (b: number | null) => (b == null ? "—" : `${(b / 1024 ** 3).toFixed(1)} GB`);

export function UserDetail() {
  const { id = "" } = useParams();
  const { data: u, error, isPending } = useQuery({ queryKey: ["admin-console", "user", id], queryFn: () => api.adminUser(id) });
  if (isForbidden(error)) return <NoAccess />;
  if (error) return <p role="alert" className="text-sm text-destructive">Couldn't load user.</p>;
  if (isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const rows: [string, string][] = [
    ["Email", u.email ?? "—"], ["Staff role", u.staff_role || "none"],
    ["Created", when(u.created_at)], ["Last login", when(u.last_login)],
  ];
  return (
    <section aria-label="User detail" className="space-y-5">
      <Link to="/admin/users" className="text-sm text-muted-foreground hover:underline">← Users</Link>
      <h1 className="text-xl font-semibold">{u.display_name}</h1>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>)}
      </dl>
      <div><h2 className="mb-1 font-medium">Groups</h2>
        {u.groups.length ? <ul className="flex flex-wrap gap-2 text-sm">{u.groups.map((g) => <li key={g} className="rounded-md bg-secondary px-2 py-1">{g}</li>)}</ul>
          : <p className="text-sm text-muted-foreground">No groups.</p>}</div>
      <div><h2 className="mb-1 font-medium">Quota</h2>
        <p className="text-sm">{u.storage.used_bytes == null ? "Unavailable" : `${gb(u.storage.used_bytes)} of ${gb(u.storage.quota_bytes)}${u.storage.percent != null ? ` (${Math.round(u.storage.percent)}%)` : ""}`}</p></div>
      <div><h2 className="mb-1 font-medium">Sessions</h2>
        {u.sessions.length ? <ul className="text-sm">{u.sessions.map((s) => <li key={s.id}>{s.template} · {when(s.started_at)} · {s.node ?? "unknown"}</li>)}</ul>
          : <p className="text-sm text-muted-foreground">No running sessions.</p>}</div>
    </section>
  );
}
