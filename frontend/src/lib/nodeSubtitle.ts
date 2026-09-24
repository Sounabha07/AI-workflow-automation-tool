import type { BlockNodeData } from "./definition";

interface SwitchRule {
  operator?: string;
  compare_value?: string;
  output?: string;
}

interface FieldDef {
  name?: string;
}

/** The one-line subtitle shown below a BlockNode (B6). */
export function nodeSubtitle(data: BlockNodeData): string {
  const { blockType, config } = data;

  if (blockType === "http_request") {
    const url = typeof config.url === "string" ? config.url.trim() : "";
    if (!url) return "Not configured";
    const method = typeof config.method === "string" ? config.method : "GET";
    let host = url;
    try {
      host = new URL(url).host || url;
    } catch {
      // Not a full URL yet (may still contain {{ }} expressions) — show as-is.
    }
    return `${method} ${host}`;
  }

  if (blockType === "switch") {
    const rules = Array.isArray(config.rules) ? (config.rules as SwitchRule[]) : [];
    const fallback = config.fallback !== false;
    const count = rules.length + (fallback ? 1 : 0);
    if (count === 0) return "Not configured";
    return `${count} output${count === 1 ? "" : "s"}`;
  }

  if (blockType === "input_block") {
    const fields = Array.isArray(config.fields) ? (config.fields as FieldDef[]) : [];
    if (fields.length === 0) return "Not configured";
    return fields.map((f) => f.name).filter(Boolean).join(", ");
  }

  return "";
}

export function switchOutputs(config: Record<string, unknown>): string[] {
  const rules = Array.isArray(config.rules) ? (config.rules as SwitchRule[]) : [];
  const outputs = rules.map((r) => String(r.output ?? "")).filter(Boolean);
  if (config.fallback !== false) outputs.push("fallback");
  return outputs;
}
