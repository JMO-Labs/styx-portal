import { cloneElement, isValidElement, useId } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, { id, ...(hint ? { "aria-describedby": hintId } : {}) })
    : children;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-muted-foreground">{label}</label>
      {control}
      {hint && <p id={hintId} className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="flex items-start gap-2">
        <code className="flex-1 break-all rounded border border-border bg-background px-2 py-1 font-mono text-[11px]">
          {value}
        </code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            navigator.clipboard?.writeText(value);
            toast.success("Copied");
          }}
          aria-label="Copy to clipboard"
        >
          <Copy className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
