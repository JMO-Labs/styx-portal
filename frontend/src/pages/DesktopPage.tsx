import { useCallback, useEffect, useRef } from "react";
import { useCanvasEffect } from "@/hooks/use-canvas-effect";
import { createWaves } from "@/lib/effects/waves";
import { Link, useParams } from "react-router";
import { Home, Loader2, Maximize, Unplug } from "lucide-react";
import { useInstances, useKeepalive } from "@/hooks/use-instances";
import { useTemplates } from "@/hooks/use-templates";
import { startActivityHeartbeat } from "@/lib/activity";
import { startThumbUploader } from "@/lib/stream-thumb";
import { api } from "@/api/client";
import { createRttReporter, type RttTransport } from "@/lib/rttReporter";

const ALLOW = "fullscreen; clipboard-read; clipboard-write; autoplay; gamepad; microphone; camera; display-capture; pointer-lock";
const WAITING = ["created", "creating", "pulling", "starting"];

/** Tab icon for a template icon: image URL as-is, emoji drawn into an SVG. */
export function faviconHref(icon: string | null | undefined): string | null {
  if (!icon) return null;
  if (icon.startsWith("http") || icon.startsWith("/")) return icon;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">${icon}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** Loading/status splash over a frozen frame of the login wave field. */
function Notice({ children }: { children: React.ReactNode }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const body = useRef<HTMLDivElement>(null);
  useCanvasEffect(cv, (c) => createWaves(c, { still: true, top: 0.58, calmRect: () => body.current?.getBoundingClientRect() ?? null }), []);
  return (
    <main className="relative flex h-dvh w-screen items-center justify-center bg-background p-4 text-center text-sm text-foreground/80">
      <canvas ref={cv} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
      <div ref={body} className="relative flex flex-col items-center gap-3">{children}</div>
    </main>
  );
}

const BTN = "inline-flex h-8 items-center gap-1.5 rounded px-2 text-xs text-foreground/90 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary";

/** Slim (40px) bar: name, fullscreen, disconnect (closes this tab; the desktop keeps running), back home. */
function Toolbar({ name }: { name: string }) {
  const goHome = () => { window.close(); if (!window.closed) window.location.assign("/"); };
  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  };
  return (
    <div role="toolbar" aria-label="Desktop controls" className="flex h-10 shrink-0 items-center gap-1 border-b border-white/10 bg-background px-2">
      <span className="mr-auto truncate text-sm font-medium">{name}</span>
      <button type="button" className={BTN} aria-label="Fullscreen" onClick={fullscreen}>
        <Maximize className="size-4" aria-hidden /><span className="hidden sm:inline">Fullscreen</span>
      </button>
      <button type="button" className={BTN} aria-label="Disconnect" onClick={goHome}>
        <Unplug className="size-4" aria-hidden /><span className="hidden sm:inline">Disconnect</span>
      </button>
      <Link to="/" className={BTN} aria-label="Home">
        <Home className="size-4" aria-hidden /><span className="hidden sm:inline">Home</span>
      </Link>
    </div>
  );
}

/** Full-viewport same-origin wrapper around /i/<sub>/ so the portal can snapshot the stream for card thumbnails. */
export function DesktopPage() {
  const { sub = "" } = useParams();
  const { data, isPending } = useInstances();
  const instance = data?.find((i) => i.subdomain === sub);
  const keepalive = useKeepalive();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const live = instance?.status === "running" || instance?.status === "idle";
  const id = instance?.id;

  const { data: templates } = useTemplates();
  const icon = faviconHref(templates?.find((t) => t.id === instance?.template_id)?.icon);

  useEffect(() => {
    if (instance?.name) document.title = instance.name;
  }, [instance?.name]);

  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link || !icon) return;
    const prev = { href: link.href, type: link.type };
    link.href = icon;
    link.removeAttribute("type");
    return () => { link.href = prev.href; link.type = prev.type; };
  }, [icon]);

  useEffect(() => {
    if (!live || !id) return;
    const stop = startThumbUploader(id, () => frameRef.current);
    const stopBeat = startActivityHeartbeat(id, () => frameRef.current);
    const focus = () => frameRef.current?.focus();
    window.addEventListener("focus", focus);
    return () => { stop(); stopBeat(); window.removeEventListener("focus", focus); };
  }, [live, id]);

  useEffect(() => {
    if (!live) return;
    const rep = createRttReporter({
      send: (r) => { api.reportRtt(r).catch(() => {}); },
      beacon: (r) => { navigator.sendBeacon?.("/api/stream/rtt", new Blob([JSON.stringify(r)], { type: "application/json" })); },
    });
    const onMessage = (e: MessageEvent) => {
      const win = frameRef.current?.contentWindow;
      if (e.origin !== window.location.origin || !win || e.source !== win) return;
      if (document.visibilityState === "hidden") return;
      const d = e.data as { type?: unknown; rtt_ms?: unknown; transport?: unknown } | null;
      if (!d || d.type !== "styx-rtt" || typeof d.rtt_ms !== "number") return;
      if (d.transport !== "webrtc" && d.transport !== "websocket") return;
      rep.add(d.rtt_ms, d.transport as RttTransport);
    };
    const onHide = () => rep.flush(true);
    window.addEventListener("message", onMessage);
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("pagehide", onHide);
      rep.stop();
    };
  }, [live]);

  const onLoad = useCallback(() => frameRef.current?.focus(), []);

  if (isPending) return <Notice><Loader2 className="size-5 animate-spin" aria-hidden /></Notice>;
  if (!instance) {
    return <Notice><p>Desktop not found</p><Link to="/" className="underline">Go home</Link></Notice>;
  }
  if (WAITING.includes(instance.status)) {
    return (
      <Notice>
        <Loader2 className="size-5 animate-spin" aria-hidden />
        <p>{instance.status_detail || `${instance.name} is starting…`}</p>
      </Notice>
    );
  }
  if (!live) {
    return <Notice><p>{instance.name} is {instance.status}</p><Link to="/" className="underline">Go home</Link></Notice>;
  }
  return (
    <div className="flex h-dvh w-screen flex-col bg-black">
      <Toolbar name={instance.name} />
      {instance.status === "idle" && (
        <div role="alert" className="fixed inset-x-0 top-10 z-10 flex items-center justify-center gap-3 bg-amber-500 px-3 py-2 text-sm font-medium text-black">
          Pausing soon due to inactivity
          <button
            type="button"
            className="rounded bg-black/80 px-2 py-0.5 text-white"
            onClick={() => keepalive.mutate(instance.id, { onSettled: () => frameRef.current?.focus() })}
          >
            I'm here
          </button>
        </div>
      )}
    <iframe
      ref={frameRef}
      src={`/i/${sub}/`}
      title={instance.name}
      allow={ALLOW}
      onLoad={onLoad}
      className="block min-h-0 w-full flex-1 border-0 bg-black"
    />
    </div>
  );
}
