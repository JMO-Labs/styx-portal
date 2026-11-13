import { Info } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export function NoticesBanner() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["notices"], queryFn: api.listNotices, staleTime: 60000 });
  const dismiss = useMutation({
    mutationFn: api.dismissNotice,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notices"] }),
  });
  const items = (data ?? []).filter((n) => !n.dismissed);
  if (items.length === 0) return null;
  return (
    <>
      {items.map((n) => (
        <div key={n.id} role="status" className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 text-sm text-foreground">
          <Info aria-hidden="true" className="size-4 shrink-0 text-amber-500" />
          <span className="flex-1">{n.message}</span>
          <button type="button" className="text-xs underline" onClick={() => dismiss.mutate(n.id)}>Dismiss</button>
        </div>
      ))}
    </>
  );
}
