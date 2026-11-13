import { SystemSettingsPanel } from "@/components/system/system-settings-panel";
import { useAuth } from "@/hooks/use-auth";

/** Policy settings; editable by platform-admin only (the PATCH is gated server-side too). */
export function PolicyEditor() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.staff_role === "platform-admin";
  return (
    <section aria-label="Policy" className="space-y-3">
      <h1 className="text-xl font-semibold">Policy</h1>
      {!canEdit && <p className="text-sm text-muted-foreground">Read-only: only platform admins can change policy.</p>}
      <SystemSettingsPanel readOnly={!canEdit} />
    </section>
  );
}
