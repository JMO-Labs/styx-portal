import { useState } from "react";
import { api } from "@/api/client";
import { navigateTo } from "@/lib/navigate";

export const SMARTCARD_DOCS = "/docs/enterprise/runbooks/smartcard-helper/";

export function cardUrl(host: string, token: string): string {
  return `styx-card://connect?host=${encodeURIComponent(host)}&token=${encodeURIComponent(token)}`;
}

/** Mints a one-time token and hands it to the local helper; the token never enters state or logs. */
export function SmartcardConnect({ instanceId }: { instanceId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const { token, host } = await api.smartcardToken(instanceId);
      navigateTo(cardUrl(host, token));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start smart card session");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed bottom-3 right-3 z-10 flex max-w-xs flex-col gap-1 rounded bg-black/80 p-2 text-xs text-white">
      <button type="button" disabled={busy} onClick={connect} className="rounded bg-white/15 px-2 py-1 font-medium">
        Connect smart card
      </button>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      <p>
        Needs the Styx card helper. <a href={SMARTCARD_DOCS} className="underline" target="_blank" rel="noreferrer">Install guide</a>
      </p>
    </div>
  );
}
