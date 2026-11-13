export type StaffRole = "platform-admin" | "help-desk" | "auditor";

/** Nav entries and the staff roles that see them (server remains the gate). */
export const NAV: { to: string; label: string; roles: StaffRole[] }[] = [
  { to: "sessions", label: "Sessions", roles: ["platform-admin", "help-desk", "auditor"] },
  { to: "capacity", label: "Capacity", roles: ["platform-admin", "help-desk", "auditor"] },
  { to: "users", label: "Users", roles: ["platform-admin", "help-desk"] },
  { to: "policy", label: "Policy", roles: ["platform-admin", "auditor"] },
  { to: "announcements", label: "Announcements", roles: ["platform-admin"] },
];

export const navFor = (role: string | undefined) => NAV.filter((n) => (n.roles as string[]).includes(role ?? ""));
