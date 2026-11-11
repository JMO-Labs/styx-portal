import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bucketKey, createRttReporter } from "../rttReporter";

describe("bucketKey", () => {
  it("uses inclusive upper bounds", () => {
    expect(bucketKey(80)).toBe(".08");
    expect(bucketKey(81)).toBe(".1");
    expect(bucketKey(5)).toBe(".01");
    expect(bucketKey(1000)).toBe("1");
    expect(bucketKey(1001)).toBe("+Inf");
  });
});

describe("createRttReporter", () => {
  const send = vi.fn();
  const beacon = vi.fn();
  beforeEach(() => { vi.useFakeTimers(); send.mockReset(); beacon.mockReset(); });
  afterEach(() => vi.useRealTimers());

  it("posts bucketed counts every 60 s and resets", () => {
    const r = createRttReporter({ send, beacon });
    r.add(80, "webrtc"); r.add(81, "webrtc"); r.add(81, "webrtc");
    vi.advanceTimersByTime(60_000);
    expect(send).toHaveBeenCalledWith({ transport: "webrtc", buckets: { ".08": 1, ".1": 2 }, sum: 0.242 });
    vi.advanceTimersByTime(60_000);
    expect(send).toHaveBeenCalledTimes(1);
    r.stop();
  });

  it("never sends an empty report", () => {
    const r = createRttReporter({ send, beacon });
    vi.advanceTimersByTime(180_000);
    r.flush(true);
    expect(send).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
    r.stop();
  });

  it("flushes via beacon when asked", () => {
    const r = createRttReporter({ send, beacon });
    r.add(20, "websocket");
    r.flush(true);
    expect(beacon).toHaveBeenCalledWith({ transport: "websocket", buckets: { ".02": 1 }, sum: 0.02 });
    expect(send).not.toHaveBeenCalled();
    r.stop();
  });

  it("ignores non-finite or negative samples", () => {
    const r = createRttReporter({ send, beacon });
    r.add(NaN, "webrtc"); r.add(-1, "webrtc"); r.add(Infinity, "webrtc");
    r.flush(false);
    expect(send).not.toHaveBeenCalled();
    r.stop();
  });

  it("splits by transport and caps at 15 samples per report", () => {
    const r = createRttReporter({ send, beacon });
    for (let i = 0; i < 12; i++) r.add(10, "webrtc");
    r.add(10, "websocket");
    r.flush(false);
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls.map((c) => c[0].transport).sort()).toEqual(["webrtc", "websocket"]);
    r.stop();
  });
});
