import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import "@/styles/admin-table.css";
import { Download } from "lucide-react";
import { api, type AccessReviewRow } from "@/api/client";
import { SectionHead } from "@/components/common/section-head";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/common/confirm-dialog";

export const currentQuarter = (d = new Date()) => `${d.getUTCFullYear()}-Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
const QUARTER_RE = /^\d{4}-Q[1-4]$/;
const LABEL: Record<string, string> = { certify: "Certified", revoke: "Revoked" };

export function AccessReviewPanel() {
  const [quarter, setQuarter] = useState(currentQuarter());
  const [rows, setRows] = useState<AccessReviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<AccessReviewRow | null>(null);
  const valid = QUARTER_RE.test(quarter);

  const load = useCallback(async () => {
    if (!valid) return;
    try {
      setRows(await api.accessReview(quarter));
      setError(null);
    } catch (e) {
      setRows(null);
      setError(e instanceof Error && e.message ? e.message : "Failed to load access review");
    }
  }, [quarter, valid]);
  useEffect(() => { void load(); }, [load]);

  const decide = async (r: AccessReviewRow, decision: "certify" | "revoke") => {
    try {
      await api.decideAccessReview({ group_id: r.group_id, user_id: r.user_id, quarter, decision });
      setRows((cur) => cur && cur.map((x) => x === r ? { ...x, decision } : x));
      toast.success(decision === "certify" ? "Certified" : "Revoked");
    } catch (e) {
      toast.error(e instanceof Error && e.message ? e.message : "Decision failed");
    }
  };

  return (
    <div>
      <SectionHead title="Access review" action={
        <div className="flex items-center gap-2">
          <Input aria-label="Quarter" value={quarter} onChange={(e) => setQuarter(e.target.value.toUpperCase())}
                 className="h-9 w-28" placeholder="2026-Q4" />
          {valid ? (
            <Button asChild variant="outline" size="sm">
              <a href={`/api/access-review/export.csv?quarter=${quarter}`} download>
                <Download className="mr-1 h-4 w-4" />Export CSV
              </a>
            </Button>
          ) : null}
        </div>} />
      {!valid ? <p className="text-sm text-muted-foreground">Enter a quarter like 2026-Q4.</p>
        : error ? <p role="alert" className="text-sm text-destructive">{error}</p>
        : rows === null ? <p className="text-sm text-muted-foreground">Loading…</p>
        : rows.length === 0 ? <p className="text-sm text-muted-foreground">No members to review.</p>
        : (
          <table className="admin-table w-full text-sm">
            <thead><tr><th>Group</th><th>User</th><th>Email</th><th>Decision</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.group_id}:${r.user_id}`}>
                  <td>{r.group}</td><td>{r.username}</td><td>{r.email ?? "—"}</td>
                  <td>{r.decision ? LABEL[r.decision] : "Pending"}</td>
                  <td className="text-right">
                    {r.decision ? null : (
                      <span className="inline-flex gap-2">
                        <Button size="sm" variant="outline" aria-label={`Certify ${r.username}`} onClick={() => void decide(r, "certify")}>Certify</Button>
                        <Button size="sm" variant="destructive" aria-label={`Revoke ${r.username}`} onClick={() => setTarget(r)}>Revoke</Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      <ConfirmDialog
        open={target !== null}
        onOpenChange={(o) => { if (!o) setTarget(null); }}
        title={`Revoke ${target?.username ?? ""} from ${target?.group ?? ""}?`}
        description="They are removed from the group immediately."
        variant="destructive" confirmLabel="Revoke"
        onConfirm={() => { const t = target; setTarget(null); if (t) void decide(t, "revoke"); }}
      />
    </div>
  );
}
