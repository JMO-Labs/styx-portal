import { useEffect, useState } from "react";
import { api } from "@/api/client";

/** Features the enterprise profile hard-disables (ADR-0053); mirrors backend app/services/profile.py. */
export type ProfileFeature =
  | "password_login" | "matrix_2fa" | "generic_oidc" | "workstation_enrollment" | "docker_routers";

/** Deployment profile from the public `/api/system/profile`; homelab (nothing disabled) until it loads or on error. */
export function useProfile() {
  const [disabled, setDisabled] = useState<string[]>([]);
  const [profile, setProfile] = useState("homelab");
  const [smartcard, setSmartcard] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.resolve(api.systemProfile?.())
      .then((p) => { if (live) { setDisabled(p?.disabled ?? []); setProfile(p?.profile ?? "homelab"); setSmartcard(!!p?.smartcard); } })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  return { disabled, profile, smartcard, isDisabled: (f: ProfileFeature) => disabled.includes(f) };
}
