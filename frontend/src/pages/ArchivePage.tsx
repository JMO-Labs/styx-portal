import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/api/client";

const fmtSize = (b: number) =>
  b >= 1024 ** 3 ? `${Number((b / 1024 ** 3).toFixed(1))} GB` : b >= 1024 ** 2 ? `${Number((b / 1024 ** 2).toFixed(1))} MB` : `${Number((b / 1024).toFixed(1))} KB`;
const errMsg = (e: unknown) => (e instanceof Error ? e.message : "request failed");

export function ArchivePage() {
  const qc = useQueryClient();
  const [path, setPath] = useState("");
  const list = useQuery({ queryKey: ["archive"], queryFn: api.listArchive, retry: false });
  const refresh = () => qc.invalidateQueries({ queryKey: ["archive"] });
  const restore = useMutation({
    mutationFn: (p: string) => api.restoreArchive(p),
    onSuccess: () => { toast.success("Restored"); refresh(); },
    onError: (e) => toast.error(e instanceof ApiError && e.status === 409 ? `Conflict: ${e.message}` : `Restore failed: ${errMsg(e)}`),
  });
  const send = useMutation({
    mutationFn: (p: string) => api.sendToArchive(p),
    onSuccess: () => { toast.success("Sent to archive"); setPath(""); refresh(); },
    onError: (e) => toast.error(`Send failed: ${errMsg(e)}`),
  });

  if (list.error instanceof ApiError && /archive disabled/i.test(list.error.message))
    return <p className="mx-auto max-w-[900px] text-sm text-muted-foreground">The archive is disabled on this portal.</p>;

  const submit = (e: FormEvent) => { e.preventDefault(); if (path.trim()) send.mutate(path.trim()); };
  return (
    <div className="mx-auto max-w-[900px] space-y-6">
      <h1 className="text-lg font-semibold">Archive</h1>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-sm">Path (relative to home)
          <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="Documents/old.iso"
            className="rounded-md border border-border bg-background px-2.5 py-1.5" />
        </label>
        <button type="submit" disabled={send.isPending} className="rounded-md border border-border px-3 py-1.5 text-sm">Send to archive</button>
      </form>
      {list.error && <p className="text-sm text-destructive">{errMsg(list.error)}</p>}
      <table className="w-full text-left text-sm">
        <thead><tr><th>Name</th><th>Size</th><th>Archived</th><th /></tr></thead>
        <tbody>
          {(list.data ?? []).map((f) => (
            <tr key={f.relpath} className="border-t border-border">
              <td className="py-2">{f.relpath}</td>
              <td>{fmtSize(f.size)}</td>
              <td>{new Date(f.mtime * 1000).toISOString().slice(0, 10)}</td>
              <td className="text-right">
                <button type="button" disabled={restore.isPending} onClick={() => restore.mutate(f.relpath)}
                  className="rounded-md border border-border px-2.5 py-1 text-xs">Restore</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.data?.length === 0 && <p className="text-sm text-muted-foreground">No archived files.</p>}
    </div>
  );
}
