import { Copy } from "lucide-react";
import { toast } from "sonner";

/** A read-only monospace value with a copy button (webhook and resume URLs). */
export function CopyField({ value, label }: { value: string; label: string }) {
  const copy = () =>
    navigator.clipboard
      ?.writeText(value)
      .then(() => toast.success("Copied"))
      .catch(() => toast.error("Couldn't copy"));
  return (
    <div className="flex items-center gap-1.5">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-[7px] border border-line-2 bg-panel px-2.5 py-1.5 font-mono text-xs">
        {value}
      </code>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copy ${label}`}
        title={`Copy ${label}`}
        className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[7px] border border-line-2 bg-surface text-ink-2 hover:bg-panel"
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
