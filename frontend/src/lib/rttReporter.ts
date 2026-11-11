/** Buckets stream RTT samples locally and reports them once a minute (POST /api/stream/rtt). */
export type RttTransport = "webrtc" | "websocket";
export interface RttReport { transport: RttTransport; buckets: Record<string, number>; sum: number }
interface Sinks { send: (r: RttReport) => void; beacon: (r: RttReport) => void }

export const REPORT_MS = 60_000;
/** Upper bounds in seconds; keys must match the backend whitelist exactly. */
const BOUNDS: [number, string][] = [
  [0.01, ".01"], [0.02, ".02"], [0.04, ".04"], [0.06, ".06"], [0.08, ".08"],
  [0.1, ".1"], [0.15, ".15"], [0.25, ".25"], [0.5, ".5"], [1, "1"],
];

export function bucketKey(ms: number): string {
  const s = ms / 1000;
  return BOUNDS.find(([le]) => s <= le)?.[1] ?? "+Inf";
}

export function createRttReporter({ send, beacon }: Sinks) {
  const acc = new Map<RttTransport, RttReport>();
  const full = (r: RttReport) => Object.values(r.buckets).reduce((a, b) => a + b, 0) >= 15;

  function flush(unloading: boolean) {
    const reports = [...acc.values()];
    acc.clear();
    for (const r of reports) {
      r.sum = Math.round(r.sum * 1e6) / 1e6;
      (unloading ? beacon : send)(r);
    }
  }

  const timer = setInterval(() => flush(false), REPORT_MS);
  return {
    add(ms: number, transport: RttTransport) {
      if (!Number.isFinite(ms) || ms < 0) return;
      let r = acc.get(transport);
      if (r && full(r)) { flush(false); r = undefined; }   // backend accepts <= 15 samples/report
      if (!r) acc.set(transport, (r = { transport, buckets: {}, sum: 0 }));
      const k = bucketKey(ms);
      r.buckets[k] = (r.buckets[k] ?? 0) + 1;
      r.sum += ms / 1000;
    },
    flush,
    stop() { clearInterval(timer); },
  };
}
