import { useQuery } from "@tanstack/react-query";
import { Info, Wrench } from "lucide-react";
import { api } from "@/api/client";
import { SectionHead } from "@/components/common/section-head";

export function AnnouncementsList() {
  const { data } = useQuery({ queryKey: ["announcements-active"], queryFn: api.listAnnouncements, staleTime: 60000 });
  if (!data || data.length === 0) return null;
  return (
    <section aria-label="Announcements">
      <SectionHead title="Announcements" />
      <ul className="space-y-2">
        {data.map((a) => {
          const Icon = a.kind === "maintenance" ? Wrench : Info;
          return (
            <li key={a.id} className="flex items-start gap-2.5 rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm">
              <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-amber-500" />
              <div><p className="font-semibold">{a.title}</p><p className="text-muted-foreground">{a.body}</p></div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
