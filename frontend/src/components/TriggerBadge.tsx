import { Clock, Play, Webhook } from "lucide-react";
import type { TriggerType } from "@/api/types";

const TRIGGERS: Record<TriggerType, { label: string; Icon: typeof Play }> = {
  manual: { label: "Manual", Icon: Play },
  schedule: { label: "Schedule", Icon: Clock },
  webhook: { label: "Webhook", Icon: Webhook },
};

/** How a workflow starts, or what started a run. */
export function TriggerBadge({ type }: { type: TriggerType | null | undefined }) {
  const { label, Icon } = TRIGGERS[type ?? "manual"] ?? TRIGGERS.manual;
  return (
    <span className="inline-flex flex-none items-center gap-1 rounded-full border border-line bg-panel px-1.5 py-px text-[11px] text-ink-2">
      <Icon className="h-3 w-3 text-trigger" aria-hidden="true" />
      {label}
    </span>
  );
}
