import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Header } from "@/components/layout/header";
import { MyProfiles } from "@/components/settings/my-profiles";
import { Button } from "@/components/ui/button";
import { api } from "@/api/client";
import { useHomeStorage } from "@/hooks/use-home-storage";
import { useInstances, useStopInstance } from "@/hooks/use-instances";
import { useOpenInstance } from "@/hooks/use-open-actions";

const GB = 1024 ** 3;
const fmt = (b: number) => `${Number((b / GB).toFixed(1))} GB`;
const FILES_SLUGS = ["files", "filebrowser", "nextcloud"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Storage() {
  const { data } = useHomeStorage();
  if (!data || data.used_bytes == null || data.quota_bytes == null || data.percent == null)
    return <p className="text-sm text-muted-foreground">No storage quota set.</p>;
  const pct = Math.min(100, Math.round(data.percent));
  return (
    <div className="space-y-1.5">
      <div role="progressbar" aria-label="Home storage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="h-2.5 overflow-hidden rounded-full bg-secondary">
        <div className={`h-full ${data.warn ? "bg-amber-500" : "bg-primary"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-sm text-muted-foreground">{fmt(data.used_bytes)} / {fmt(data.quota_bytes)} used ({pct} %)</p>
    </div>
  );
}

function Files() {
  const { data } = useQuery({ queryKey: ["services"], queryFn: api.listServiceTiles });
  const app = data?.find((s) => s.enabled && FILES_SLUGS.includes(s.slug));
  if (!app) return null;
  return (
    <Section title="Files">
      <Button asChild variant="outline"><a href={`/_styx/app/${app.slug}/`} aria-label={`Open ${app.name}`}>Open {app.name}</a></Button>
    </Section>
  );
}

function Sessions() {
  const { data } = useInstances();
  const stop = useStopInstance();
  const open = useOpenInstance();
  const running = (data ?? []).filter((i) => i.status === "running");
  return (
    <Section title="Sessions">
      {running.length === 0 ? <p className="text-sm text-muted-foreground">No running desktops.</p> : (
        <ul className="grid gap-1">
          {running.map((i) => (
            <li key={i.id} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-card">
              <strong className="min-w-0 flex-1 truncate font-semibold">{i.name}</strong>
              <Button size="sm" onClick={() => open(i)} aria-label={`Open ${i.name}`}>Open</Button>
              <Button size="sm" variant="outline" aria-label={`Stop ${i.name}`}
                onClick={() => stop.mutate(i.id, { onError: (e: Error) => toast.error(`Stop failed: ${e.message}`) })}>Stop</Button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function AccountPage() {
  const navigate = useNavigate();
  return (
    <div className="flex h-dvh flex-col bg-background styx-app-bg">
      <Header activeTab="home" onTabChange={() => navigate("/")} />
      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl space-y-8">
          <h1 className="text-2xl font-bold">My account</h1>
          <Section title="Storage"><Storage /></Section>
          <Files />
          <Section title="Profiles"><MyProfiles /></Section>
          <Sessions />
        </div>
      </main>
    </div>
  );
}
