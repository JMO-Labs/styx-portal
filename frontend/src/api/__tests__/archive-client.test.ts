import { afterEach, describe, expect, test, vi } from "vitest";
import { api } from "../client";

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const f = vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", f);
  return f;
}

describe("archive client", () => {
  test.each([
    ["restoreArchive", "/archive/restore"],
    ["sendToArchive", "/archive/send"],
  ] as const)("%s posts { relpath }", async (fn, url) => {
    const f = stubFetch();
    await api[fn]("docs/a.txt");
    const [called, init] = f.mock.calls[0]!;
    expect(String(called)).toContain(url);
    expect(JSON.parse(init.body)).toEqual({ relpath: "docs/a.txt" });
  });
});

test("dismissNotice url-encodes the id", async () => {
  const f = stubFetch();
  await api.dismissNotice("a/b c");
  expect(String(f.mock.calls[0]![0])).toContain("/notices/a%2Fb%20c/dismiss");
});
