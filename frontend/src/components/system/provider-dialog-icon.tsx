import { useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { OAuthProviderCreate } from "@/api/client";
import { KeyRound, Upload, X } from "lucide-react";
import { Field } from "./provider-dialog-fields";

const MAX_ICON_BYTES = 200 * 1024;

export function IconField({ form, setForm }: {
  form: OAuthProviderCreate;
  setForm: Dispatch<SetStateAction<OAuthProviderCreate>>;
}) {
  const [iconError, setIconError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function onPickIcon(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_ICON_BYTES) {
      setIconError("Icon must be under 200 KB.");
      e.target.value = "";
      return;
    }
    setIconError("");
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, icon_url: String(reader.result) }));
    reader.readAsDataURL(file);
  }

  return (
        <Field label="Icon" hint="URL or upload. Shown on the login button.">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border bg-muted/40 overflow-hidden">
                {form.icon_url ? (
                  <img src={form.icon_url} alt="" className="h-6 w-6 object-contain" />
                ) : (
                  <KeyRound className="h-4 w-4 text-muted-foreground" />
                )}
              </div>
              <Input
                value={form.icon_url ?? ""}
                placeholder="https://…/logo.svg"
                onChange={(e) =>
                  setForm((f) => ({ ...f, icon_url: e.target.value || null }))
                }
              />
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                hidden
                onChange={onPickIcon}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
                aria-label="Upload icon"
              >
                <Upload className="h-4 w-4" />
              </Button>
              {form.icon_url && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setForm((f) => ({ ...f, icon_url: null }))}
                  aria-label="Clear icon"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
            {iconError && <p className="text-xs text-destructive">{iconError}</p>}
          </div>
        </Field>
  );
}
