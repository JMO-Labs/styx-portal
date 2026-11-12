export interface ProvisionedUser {
  id: string; username: string; email: string | null; created_at: string;
  reviewed_at: string | null; status: "active" | "disabled"; disabled_reason: string | null;
}
