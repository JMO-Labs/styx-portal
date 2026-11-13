import { Eye, MousePointer2 } from "lucide-react";

export interface Takeover {
  actor_name: string;
  mode: "view" | "control" | string;
  started_at: string;
}

/** Persistent, non-dismissible notice that staff is viewing/controlling this session. */
export function TakeoverBanner({ takeover }: { takeover: Takeover | null | undefined }) {
  if (!takeover) return null;
  const control = takeover.mode === "control";
  const Icon = control ? MousePointer2 : Eye;
  return (
    <div role="alert" className="flex shrink-0 items-center justify-center gap-2 bg-red-600 px-3 py-1.5 text-sm font-medium text-white">
      <Icon className="size-4" aria-hidden />
      {takeover.actor_name} is {control ? "controlling" : "viewing"} your session
    </div>
  );
}
