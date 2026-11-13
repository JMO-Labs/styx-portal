import { ApiError } from "@/api/client";

export const isForbidden = (e: unknown) => e instanceof ApiError && e.status === 403;
