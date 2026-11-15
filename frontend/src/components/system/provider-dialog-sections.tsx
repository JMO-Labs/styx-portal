import type { Dispatch, SetStateAction } from "react";
import { Input } from "@/components/ui/input";
import {
  type OAuthProviderRow, type OAuthProviderCreate, type ProviderTestResult,
} from "@/api/client";
import { Check, AlertCircle, ChevronDown, Link2 } from "lucide-react";
import { Field, CopyRow } from "./provider-dialog-fields";

type FormState = OAuthProviderCreate;
type SetForm = Dispatch<SetStateAction<FormState>>;
type SetField = (
  k: keyof OAuthProviderCreate,
) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void;

export function EndpointsSection({ form, set, editing, advanced, setAdvanced }: {
  form: FormState;
  set: SetField;
  editing: OAuthProviderRow | null;
  advanced: boolean;
  setAdvanced: Dispatch<SetStateAction<boolean>>;
}) {
  return (
        <details
          className="rounded-md border border-border"
          open={form.kind === "oauth2"}
        >
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium hover:bg-muted/40 transition-colors">
            Endpoints
          </summary>
          <div className="space-y-3 px-3 pb-3">
            {form.kind === "oidc" && (
              <Field label="Issuer URL" hint="We auto-discover endpoints from here.">
                <Input
                  value={form.issuer_url || ""}
                  onChange={set("issuer_url")}
                  placeholder="https://auth.example.com/application/o/styx/"
                />
              </Field>
            )}

            <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
                Redirect URI — register this in your identity provider
              </div>
              <CopyRow
                label="Login callback"
                value={
                  editing
                    ? editing.redirect_uri
                    : `${window.location.origin}/api/auth/oauth/${form.name || "your-provider"}/callback`
                }
              />
              {editing ? (
                <CopyRow label="Test-login callback" value={editing.test_redirect_uri} />
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Save the provider to get its Test-login callback URL.
                </p>
              )}
              <p className="text-[11px] text-muted-foreground">
                Must match exactly — scheme, host, path, and case. Use Strict matching in your IdP.
              </p>
            </div>

            <Field label="Scopes">
              <Input value={form.scopes || ""} onChange={set("scopes")} />
            </Field>

            <button
              type="button"
              onClick={() => setAdvanced((v) => !v)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown
                className={`h-3 w-3 transition-transform ${advanced ? "rotate-180" : ""}`}
              />
              Advanced — manual endpoint overrides
            </button>

            {advanced && (
              <div className="space-y-2 rounded-md border border-border p-3">
                <Input
                  placeholder="authorize_url"
                  value={form.authorize_url || ""}
                  onChange={set("authorize_url")}
                />
                <Input
                  placeholder="token_url"
                  value={form.token_url || ""}
                  onChange={set("token_url")}
                />
                <Input
                  placeholder="userinfo_url"
                  value={form.userinfo_url || ""}
                  onChange={set("userinfo_url")}
                />
              </div>
            )}
          </div>
        </details>
  );
}

export function RoleMappingSection({
  form, setForm, groupsClaim, setGroupsClaim, userGroup, setUserGroup, adminGroup, setAdminGroup,
}: {
  form: FormState;
  setForm: SetForm;
  groupsClaim: string; setGroupsClaim: (v: string) => void;
  userGroup: string; setUserGroup: (v: string) => void;
  adminGroup: string; setAdminGroup: (v: string) => void;
}) {
  return (
        <details className="rounded-md border border-border">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium hover:bg-muted/40 transition-colors">
            Role mapping
          </summary>
          <div className="space-y-3 px-3 pb-3">
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5"
                checked={form.auto_promote_admins ?? true}
                onChange={(e) => setForm((f) => ({ ...f, auto_promote_admins: e.target.checked }))} />
              <span>
                Auto-promote admins from the identity provider
                <span className="block text-xs text-muted-foreground">
                  When on, a user whose groups claim contains the admin group below becomes an
                  admin automatically. Turn off to require manual promotion.
                </span>
              </span>
            </label>

            <div className="grid grid-cols-3 gap-2">
              <Field label="Groups claim" hint="Userinfo claim holding the user's groups.">
                <Input
                  value={groupsClaim}
                  onChange={(e) => setGroupsClaim(e.target.value)}
                  placeholder="groups"
                />
              </Field>
              <Field label="User group" hint="Required to sign up (blank = anyone).">
                <Input
                  value={userGroup}
                  onChange={(e) => setUserGroup(e.target.value)}
                  placeholder="styx-users"
                />
              </Field>
              <Field label="Admin group" hint="Members get the admin role.">
                <Input
                  value={adminGroup}
                  onChange={(e) => setAdminGroup(e.target.value)}
                  placeholder="styx-admins"
                />
              </Field>
            </div>

            <p className="text-xs text-muted-foreground">
              If a user's <code>{groupsClaim || "groups"}</code> claim contains
              "{adminGroup || "<admin group>"}", they'll be made an admin.
            </p>
            <p className="text-[11px] text-muted-foreground">
              With a user group set, only its members may sign up; leave it
              blank to allow anyone the provider authenticates. Group mapping also applies to
              invited users.
            </p>
          </div>
        </details>
  );
}

export function SelfServiceSection({ form, setForm }: { form: FormState; setForm: SetForm }) {
  return (
        <details className="rounded-md border border-border">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium hover:bg-muted/40 transition-colors">
            Self-service
          </summary>
          <div className="space-y-3 px-3 pb-3">
            <label className="flex items-start gap-3 rounded-md border border-border p-3 cursor-pointer hover:bg-muted/20 transition-colors">
              <input
                type="checkbox"
                checked={!!form.trust_email}
                className="mt-0.5 h-4 w-4"
                onChange={(e) =>
                  setForm((f) => ({ ...f, trust_email: e.target.checked }))
                }
              />
              <span className="text-sm">
                <span className="font-medium">Trust emails from this provider</span>
                <span className="block text-xs text-muted-foreground">
                  Enable if your IdP (e.g. Authentik) doesn't send a verified-email claim.
                  Email is still required.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={!!form.allow_signup}
                className="mt-0.5 h-4 w-4"
                onChange={(e) =>
                  setForm((f) => ({ ...f, allow_signup: e.target.checked }))
                }
              />
              <span className="text-sm">
                <span className="font-medium">Allow new users to sign up</span>
                <span className="block text-xs text-muted-foreground">
                  Auto-create accounts on first login without an invite. Otherwise sign-in
                  is invite-only.
                </span>
              </span>
            </label>
          </div>
        </details>
  );
}

export function TestResults(
  { test, probe }: { test: ProviderTestResult | null; probe: Record<string, unknown> | null },
) {
  return (
    <>
          {test && (
            <div className="space-y-1 rounded-md border border-border p-3 text-xs">
              {test.checks.map((c) => (
                <div key={c.label} className="flex items-center gap-2">
                  {c.ok ? (
                    <Check className="h-3 w-3 text-success" />
                  ) : (
                    <AlertCircle className="h-3 w-3 text-destructive" />
                  )}
                  <span className="font-medium">{c.label}</span>
                  <span className="text-muted-foreground truncate">{c.detail}</span>
                </div>
              ))}
            </div>
          )}

          {probe && (
            <div className="mt-2 space-y-1 rounded-md border border-border p-3 text-xs">
              <div className={probe.would_pass ? "font-medium text-success" : "font-medium text-destructive"}>
                {probe.would_pass ? "✓ A real login would succeed" : "✗ A real login would be rejected"}
              </div>
              {typeof probe.email === "string" && (
                <div className="text-muted-foreground">
                  Email: {probe.email}{probe.email_verified ? " (verified)" : " (unverified)"}
                </div>
              )}
              {!probe.would_pass && !probe.email && (
                <div className="text-muted-foreground">No email returned by the provider.</div>
              )}
              <details className="mt-1">
                <summary className="cursor-pointer select-none text-muted-foreground">Raw response</summary>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[10px] text-muted-foreground font-mono">
                  {JSON.stringify(probe, null, 2)}
                </pre>
              </details>
            </div>
          )}
    </>
  );
}
