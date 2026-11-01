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

  if (blockType === "schedule_trigger") {
    const cron = typeof config.cron === "string" ? config.cron.trim() : "";
    if (!cron) return "Not configured";
    return `${cron} (${typeof config.timezone === "string" && config.timezone ? config.timezone : "UTC"})`;
  }

  if (blockType === "webhook_trigger") {
    return config.secret ? "POST, signed" : "POST";
  }

  if (blockType === "wait_for_input") {
    const seconds = Number(config.timeout_seconds);
    if (!Number.isFinite(seconds) || seconds <= 0) return "Not configured";
    return `Up to ${formatSeconds(seconds)}`;
  }

  if (blockType === "input_block") {
    const fields = Array.isArray(config.fields) ? (config.fields as FieldDef[]) : [];
    if (fields.length === 0) return "Not configured";
    return fields.map((f) => f.name).filter(Boolean).join(", ");
  }

  if (blockType === "llm") {
    const model = typeof config.model === "string" ? config.model.trim() : "";
    const prompt = typeof config.prompt === "string" ? config.prompt.trim() : "";
    if (!prompt) return "Not configured";
    return model || "Default model";
  }

  return "";
}

function formatSeconds(s: number): string {
  if (s % 86400 === 0) return `${s / 86400} d`;
  if (s % 3600 === 0) return `${s / 3600} h`;
  if (s % 60 === 0) return `${s / 60} min`;
  return `${s} s`;
}

export function switchOutputs(config: Record<string, unknown>): string[] {
  const rules = Array.isArray(config.rules) ? (config.rules as SwitchRule[]) : [];
  const outputs = rules.map((r) => String(r.output ?? "")).filter(Boolean);
  if (config.fallback !== false) outputs.push("fallback");
  return outputs;
}
