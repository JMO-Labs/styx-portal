import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import "@/styles/admin-table.css";
import { api, type ProvisionedUser } from "@/api/client";
import { SectionHead } from "@/components/common/section-head";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { Button } from "@/components/ui/button";

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** Review deadline: creation time plus one business day (weekends skipped). */
/** Backend timestamps may be naive (no offset); treat those as UTC. */
const parseTs = (iso: string) => new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);

export function dueBy(createdAt: string): Date {
  const d = parseTs(createdAt);
  do d.setUTCDate(d.getUTCDate() + 1);
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
  return d;
}

const fmt = (iso: string | Date) => (typeof iso === "string" ? parseTs(iso) : iso).toLocaleDateString(undefined, { dateStyle: "medium" });

export function RecentlyProvisionedPanel() {
  const [rows, setRows] = useState<ProvisionedUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<ProvisionedUser | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.listProvisioned());
      setError(null);
    } catch (e) {
      setError(errMsg(e, "Failed to load recently provisioned accounts"));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const act = async (fn: () => Promise<unknown>, ok: string, fail: string) => {
    try {
      await fn();
      toast.success(ok);
      await load();
    } catch (e) {
      toast.error(errMsg(e, fail));
    }
  };

  const now = Date.now();
  return (
    <section>
      <SectionHead title="Recently provisioned" note="Review new accounts within one business day, or suspend them." />
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {rows && rows.length === 0 && <p className="text-sm text-muted-foreground">No accounts provisioned recently.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="admin-table w-full text-sm">
            <thead>
              <tr><th>Username</th><th>Created</th><th>Status</th><th>Due by</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const due = dueBy(u.created_at);
                const overdue = !u.reviewed_at && u.status === "active" && due.getTime() < now;
                return (
                  <tr key={u.id} data-testid={`row-${u.id}`} data-overdue={String(overdue)}
                      className={overdue ? "bg-destructive/10" : undefined}>
                    <td>{u.username}</td>
                    <td>{fmt(u.created_at)}</td>
                    <td>{u.status === "disabled" ? "Suspended" : u.reviewed_at ? `Reviewed ${fmt(u.reviewed_at)}` : "Unreviewed"}</td>
                    <td>{u.reviewed_at ? "—" : <span className={overdue ? "font-semibold text-destructive" : undefined}>
                      Due {fmt(due)}{overdue ? " (overdue)" : ""}</span>}</td>
                    <td className="space-x-2 text-right">
                      {!u.reviewed_at && (
                        <Button size="sm" variant="outline" aria-label={`Mark ${u.username} reviewed`}
                                onClick={() => void act(() => api.reviewProvisioned(u.id), "Marked reviewed", "Failed to mark reviewed")}>
                          Mark reviewed
                        </Button>
                      )}
                      {u.status === "active" && (
                        <Button size="sm" variant="destructive" aria-label={`Suspend ${u.username}`} onClick={() => setTarget(u)}>
                          Suspend
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog
        open={!!target}
        onOpenChange={(o) => { if (!o) setTarget(null); }}
        title={`Suspend ${target?.username ?? ""}?`}
        description="The account is disabled immediately and its sessions are ended."
        confirmLabel="Suspend"
        variant="destructive"
        onConfirm={() => { const t = target; if (t) void act(() => api.suspendProvisioned(t.id), "Account suspended", "Failed to suspend"); }}
      />
    </section>
  );
}
