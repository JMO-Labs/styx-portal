import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "@/api/client";
import { NoAccess } from "./no-access";
import { isForbidden } from "./forbidden";

export function UsersPage() {
  const { data, error, isPending } = useQuery({ queryKey: ["admin-console", "users"], queryFn: api.adminUsers });
  if (isForbidden(error)) return <NoAccess />;
  const rows = data?.users ?? [];
  return (
    <section aria-label="Users" className="space-y-3">
      <h1 className="text-xl font-semibold">Users</h1>
      {error ? <p role="alert" className="text-sm text-destructive">Couldn't load users.</p>
        : isPending ? <p className="text-sm text-muted-foreground">Loading…</p>
        : (
          <ul className="divide-y divide-border rounded-xl border border-border text-sm">
            {rows.map((u) => (
              <li key={u.id}>
                <Link to={`/admin/users/${u.id}`} className="flex justify-between px-3 py-2 hover:bg-secondary max-md:min-h-11">
                  <span>{u.username}</span><span className="text-muted-foreground">{u.email ?? "—"}</span>
                </Link>
              </li>))}
          </ul>
        )}
    </section>
  );
}
