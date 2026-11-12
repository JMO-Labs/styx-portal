import { UserX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type Props = { username: string | null; pending: boolean; onCancel: () => void; onConfirm: () => void };

export function RemoveAccessDialog({ username, pending, onCancel, onConfirm }: Props) {
  return (
    <Dialog open={username !== null} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-destructive">
            <UserX className="h-5 w-5" />Remove access?
          </DialogTitle>
          <DialogDescription>
            This disables <strong>{username}</strong> in Styx and Keycloak and ends their live sessions immediately.
          </DialogDescription>
        </DialogHeader>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel} disabled={pending}>Cancel</Button>
          <Button variant="destructive" onClick={onConfirm} disabled={pending}>
            {pending ? "Removing…" : "Remove access"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
