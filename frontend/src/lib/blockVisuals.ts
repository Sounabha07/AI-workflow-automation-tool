import { FormInput, Globe, Play, Split, type LucideIcon } from "lucide-react";

export interface BlockVisual {
  label: string;
  icon: LucideIcon;
  /** Tailwind color token name, matching PROMPT.md B2's category colors. */
  color: "trigger" | "flow" | "data" | "action";
  isTrigger?: boolean;
}

export const BLOCK_VISUALS: Record<string, BlockVisual> = {
  manual_trigger: { label: "Trigger", icon: Play, color: "trigger", isTrigger: true },
  switch: { label: "Switch", icon: Split, color: "flow" },
  input_block: { label: "Input", icon: FormInput, color: "data" },
  http_request: { label: "HTTP", icon: Globe, color: "action" },
};

export function blockVisual(type: string): BlockVisual {
  return (
    BLOCK_VISUALS[type] ?? { label: type, icon: Globe, color: "action" }
  );
}

/** Category order for the block picker (B2). */
export const CATEGORY_ORDER = ["Triggers", "Flow", "Data", "Actions", "Communication"] as const;

export const CATEGORY_COLOR: Record<string, string> = {
  Triggers: "trigger",
  Flow: "flow",
  Data: "data",
  Actions: "action",
  Communication: "ink-3",
};

// Tailwind's content scanner needs full, static class names in source — these
// maps exist so a dynamic `visual.color` lookup still resolves to a class
// Tailwind actually generated, instead of building `text-${color}` at runtime.
export const COLOR_TEXT_CLASS: Record<BlockVisual["color"], string> = {
  trigger: "text-trigger",
  flow: "text-flow",
  data: "text-data",
  action: "text-action",
};

export const COLOR_BG_CLASS: Record<BlockVisual["color"], string> = {
  trigger: "bg-trigger",
  flow: "bg-flow",
  data: "bg-data",
  action: "bg-action",
};
