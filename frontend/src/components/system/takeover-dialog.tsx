import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { openPending } from "@/lib/connect-wipe";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export type TakeoverMode = "view" | "control";
type Target = { id: string; name: string; subdomain: string };

const MODES: { id: TakeoverMode; label: string; hint: string }[] = [
  { id: "view", label: "View", hint: "Watch only. Your input is ignored." },
  { id: "control", label: "Control", hint: "Your keyboard and mouse drive the desktop. The user still sees the screen." },
];

/** View = Selkies `#shared` (view-only) client; Control = the normal client. */
export const desktopUrl = (sub: string, mode: TakeoverMode) => `/desktop/${sub}${mode === "view" ? "#shared" : ""}`;

export const endTakeoverFor = (id: string) => api.endTakeover(id);

export function TakeoverDialog({ open, instance, onOpenChange, onStarted }: {
  open: boolean; instance: Target; onOpenChange: (o: boolean) => void; onStarted: () => void;
}) {
  const [mode, setMode] = useState<TakeoverMode>("view");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmed = reason.trim();

  async function submit() {
    setBusy(true);
    try {
      await openPending("new_tab", `Taking over ${instance.name}…`, async () => {
        await api.startTakeover(instance.id, { mode, reason: trimmed });
        return desktopUrl(instance.subdomain, mode);
      });
      onStarted();
      onOpenChange(false);
    } catch (e) {
      toast.error(`Takeover failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{`Take over ${instance.name}`}</DialogTitle>
          <DialogDescription>The session is audited with your reason.</DialogDescription>
        </DialogHeader>
        <div role="radiogroup" aria-label="Mode" className="space-y-2">
          {MODES.map((m) => (
            <label key={m.id} className="flex items-start gap-2 rounded-md border border-border p-2 text-sm">
              <input type="radio" name="takeover-mode" checked={mode === m.id} onChange={() => setMode(m.id)}
                aria-label={m.label} className="mt-1" />
              <span><span className="font-medium">{m.label}</span>
                <span className="block text-xs text-muted-foreground">{m.hint}</span></span>
            </label>
          ))}
        </div>
        <div className="space-y-1">
          <label htmlFor="takeover-reason" className="text-sm font-medium">Ticket number or reason</label>
          <Textarea id="takeover-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!trimmed || busy} onClick={submit}>Start takeover</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
