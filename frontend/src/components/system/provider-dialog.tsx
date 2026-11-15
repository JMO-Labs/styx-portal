import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import {
  api, type OAuthProviderRow, type OAuthProviderCreate, type ProviderTestResult,
} from "@/api/client";
import { Field } from "./provider-dialog-fields";
import { IconField } from "./provider-dialog-icon";
import {
  EndpointsSection, RoleMappingSection, SelfServiceSection, TestResults,
} from "./provider-dialog-sections";

const EMPTY: OAuthProviderCreate = {
  name: "", display_label: "", kind: "oidc", issuer_url: "",
  client_id: "", client_secret: "", scopes: "openid email profile",
  icon_url: null, trust_email: false, allow_signup: false, auto_promote_admins: true,
};

type RoleMap = { claim?: string; user_group?: string; admin_group?: string };

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: OAuthProviderRow | null;
};

export function ProviderDialog({ open, onOpenChange, editing }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState<OAuthProviderCreate>(EMPTY);
  const [advanced, setAdvanced] = useState(false);
  const [test, setTest] = useState<ProviderTestResult | null>(null);
  const [probe, setProbe] = useState<Record<string, unknown> | null>(null);
  const [groupsClaim, setGroupsClaim] = useState("groups");
  const [userGroup, setUserGroup] = useState("");
  const [adminGroup, setAdminGroup] = useState("");

  useEffect(() => {
    if (!open) return;
    setTest(null);
    setProbe(null);
    if (editing) {
      setForm({
        name: editing.name,
        display_label: editing.display_label,
        kind: editing.kind,
        issuer_url: editing.issuer_url ?? "",
        client_id: editing.client_id,
        client_secret: "",
        scopes: editing.scopes,
        icon_url: editing.icon_url,
        trust_email: editing.trust_email,
        allow_signup: editing.allow_signup,
        auto_promote_admins: editing.auto_promote_admins,
      });
      const rm = (editing.role_map ?? {}) as RoleMap;
      setGroupsClaim(rm.claim || "groups");
      setUserGroup(rm.user_group || "");
      setAdminGroup(rm.admin_group || "");
    } else {
      setForm(EMPTY);
      setGroupsClaim("groups");
      setUserGroup("");
      setAdminGroup("");
    }
  }, [open, editing]);

  function buildRoleMap(): RoleMap {
    const rm: RoleMap = { claim: groupsClaim.trim() || "groups" };
    if (userGroup.trim()) rm.user_group = userGroup.trim();
    if (adminGroup.trim()) rm.admin_group = adminGroup.trim();
    return rm;
  }

  const set = (k: keyof OAuthProviderCreate) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function autoName(label: string) {
    if (editing) return;
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    setForm((f) => ({ ...f, display_label: label, name: slug }));
  }

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        const patch: Partial<OAuthProviderCreate> & { enabled?: boolean } = {
          display_label: form.display_label,
          issuer_url: form.issuer_url,
          client_id: form.client_id,
          scopes: form.scopes,
          icon_url: form.icon_url,
          trust_email: form.trust_email,
          allow_signup: form.allow_signup,
          auto_promote_admins: form.auto_promote_admins,
          role_map: buildRoleMap(),
          authorize_url: form.authorize_url,
          token_url: form.token_url,
          userinfo_url: form.userinfo_url,
        };
        if (form.client_secret) patch.client_secret = form.client_secret;
        return api.updateOAuthProvider(editing.id, patch);
      }
      return api.createOAuthProvider({ ...form, role_map: buildRoleMap() });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["oauth-providers"] });
      toast.success(editing ? "Provider updated" : "Provider added");
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const checkConfig = useMutation({
    mutationFn: () => api.testOAuthConfig(editing!.id),
    onSuccess: (r) => setTest(r),
    onError: (e: Error) => toast.error(e.message),
  });

  function testLogin() {
    if (!editing) return;
    const w = window.open(api.oauthTestStartUrl(editing.id), "sso-test",
      "width=520,height=640");
    const onMsg = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin || ev.source !== w) return;
      if (ev.data?.type === "sso-test") {
        setProbe(ev.data.result);
        window.removeEventListener("message", onMsg);
        w?.close();
      }
    };
    window.addEventListener("message", onMsg);
  }

  const canSave = form.display_label && form.name && form.client_id &&
    (editing || form.client_secret) &&
    (form.kind !== "oidc" || form.issuer_url);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] sm:max-w-2xl flex-col">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit provider" : "Add SSO provider"}</DialogTitle>
          <DialogDescription>
            Connect an identity provider so users can sign in with single sign-on.
          </DialogDescription>
        </DialogHeader>

        <div className="-mr-2 flex-1 space-y-3 overflow-y-auto pr-2">
          {/* BASIC SECTION — always visible */}
          <Field label="Display name" hint="Shown to users on the login button.">
            <Input
              autoFocus
              value={form.display_label}
              onChange={(e) => autoName(e.target.value)}
              placeholder="My Authentik"
            />
          </Field>

          <Field label="Internal name" hint="Lowercase id used in URLs. Locked after creation.">
            <Input
              value={form.name}
              onChange={set("name")}
              disabled={!!editing}
              placeholder="authentik"
            />
          </Field>

          <Field label="Type">
            <select
              className="w-full rounded-md border border-border bg-background p-2 text-sm"
              value={form.kind}
              onChange={set("kind")}
              disabled={!!editing}
            >
              <option value="oidc">OIDC — Authentik, Google, Keycloak, generic</option>
              <option value="oauth2">OAuth2 — GitHub</option>
            </select>
          </Field>

          <Field label="Client ID">
            <Input value={form.client_id} onChange={set("client_id")} />
          </Field>

          <Field
            label="Client secret"
            hint={editing ? "Leave blank to keep the current secret." : undefined}
          >
            <PasswordInput
              value={form.client_secret}
              onChange={set("client_secret")}
              placeholder={editing ? "•••• unchanged" : ""}
            />
          </Field>

          <IconField form={form} setForm={setForm} />

          <EndpointsSection
            form={form} set={set} editing={editing}
            advanced={advanced} setAdvanced={setAdvanced}
          />

          <RoleMappingSection
            form={form} setForm={setForm}
            groupsClaim={groupsClaim} setGroupsClaim={setGroupsClaim}
            userGroup={userGroup} setUserGroup={setUserGroup}
            adminGroup={adminGroup} setAdminGroup={setAdminGroup}
          />

          <SelfServiceSection form={form} setForm={setForm} />

          {editing && (
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => checkConfig.mutate()}
                disabled={checkConfig.isPending}
              >
                {checkConfig.isPending ? "Checking…" : "Check config"}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={testLogin}
              >
                Test login
              </Button>
            </div>
          )}

          {!editing && (
            <p className="text-xs text-muted-foreground">
              Save the provider to enable Check config / Test login.
            </p>
          )}

          <TestResults test={test} probe={probe} />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={!canSave || save.isPending}
          >
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Add provider"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}