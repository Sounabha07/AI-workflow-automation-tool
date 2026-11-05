import { useMemo, useState } from "react";
import { CircleCheck, FlaskConical, Loader2, TriangleAlert, Wrench, X } from "lucide-react";
import { toast } from "sonner";
import type { FieldSchema } from "@/api/types";
import { ApiError } from "@/api/client";
import { testTool } from "@/api/tools";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FieldRenderer } from "./fields/FieldRenderer";
import { flowToDefinition, type FlowNode } from "@/lib/definition";
import { useEditorStore } from "@/store/editor";
import { cn } from "@/lib/utils";

const TOOL_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
// Gemini's documented Schema keywords; others may be ignored by the model.
const GEMINI_KEYWORDS = new Set([
  "type", "format", "title", "description", "nullable", "enum", "items", "maxItems", "minItems",
  "properties", "required", "minProperties", "maxProperties", "minimum", "maximum", "minLength",
  "maxLength", "pattern", "example", "anyOf", "propertyOrdering", "default", "$schema",
]);

function unsupportedKeywords(schema: unknown, path = ""): string[] {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) return [];
  const out: string[] = [];
  for (const [k, v] of Object.entries(schema as Record<string, unknown>)) {
    const here = path ? `${path}.${k}` : k;
    if (!GEMINI_KEYWORDS.has(k)) {
      out.push(here);
      continue;
    }
    if (k === "properties" && v && typeof v === "object") {
      for (const [p, sub] of Object.entries(v as Record<string, unknown>)) out.push(...unsupportedKeywords(sub, `${here}.${p}`));
    } else if (k === "items") out.push(...unsupportedKeywords(v, here));
    else if (k === "anyOf" && Array.isArray(v)) v.forEach((sub, i) => out.push(...unsupportedKeywords(sub, `${here}[${i}]`)));
  }
  return out;
}

function asText(value: unknown, fallback: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value ?? fallback, null, 2);
}

/** A JSON object editor that keeps the text while it's invalid and stores
 * the parsed object once it parses. */
function JsonObjectEditor({
  label,
  value,
  fallback,
  description,
  validate,
  onChange,
  rows = 6,
}: {
  label: string;
  value: unknown;
  fallback: unknown;
  description?: string;
  validate?: (parsed: unknown) => { error?: string; warning?: string };
  onChange: (value: unknown) => void;
  rows?: number;
}) {
  const [text, setText] = useState(() => asText(value, fallback));
  const parsed = useMemo(() => {
    try {
      return { value: JSON.parse(text.trim() || "{}") as unknown };
    } catch (e) {
      return { error: (e as Error).message };
    }
  }, [text]);
  const check =
    "error" in parsed
      ? { error: `Not valid JSON: ${parsed.error}` }
      : parsed.value === null || typeof parsed.value !== "object" || Array.isArray(parsed.value)
        ? { error: "Must be a JSON object" }
        : validate?.(parsed.value) ?? {};

  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-medium text-ink-2">{label}</label>
      <Textarea
        rows={rows}
        value={text}
        spellCheck={false}
        className={cn(check.error && "border-err")}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const v = JSON.parse(e.target.value.trim() || "{}");
            if (v && typeof v === "object" && !Array.isArray(v)) onChange(v);
          } catch {
            // Keep the draft; the error shows below.
          }
        }}
      />
      {check.error ? (
        <p className="mt-1 text-xs text-err">{check.error}</p>
      ) : check.warning ? (
        <p className="mt-1 text-xs text-[#9A6B00]">{check.warning}</p>
      ) : description ? (
        <p className="mt-1 text-xs text-ink-3">{description}</p>
      ) : null}
    </div>
  );
}

/** The HTTP block's Tool definition section, shown when it's connected to an agent. */
export function ToolDefinitionPanel({
  node,
  agentId,
  fields,
  config,
  outputs,
  onChange,
}: {
  node: FlowNode;
  agentId: string;
  fields: FieldSchema[];
  config: Record<string, unknown>;
  outputs: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
}) {
  const byName = Object.fromEntries(fields.map((f) => [f.name, f]));
  const name = String(config.tool_name ?? "");
  const description = String(config.tool_description ?? "");
  const nameError = !name
    ? "Required."
    : !TOOL_NAME.test(name)
      ? "Letters, digits and underscores, starting with a letter or _ (max 64)."
      : name === "finish"
        ? "'finish' is reserved for the agent's final answer."
        : null;

  return (
    <div className="mb-5 rounded-lg border border-[#D9CCF2] bg-[#FAF7FF] p-3">
      <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ink">
        <Wrench className="h-4 w-4 text-llm" />
        Tool definition
        <span className="ml-auto text-xs font-normal text-ink-3">used by {agentId}</span>
      </div>
      <p className="mb-3 text-xs text-ink-2">
        The model's arguments are sent as they are: query params for GET, DELETE and HEAD, the JSON body for POST, PUT and
        PATCH. A {"{name}"} in the URL is filled from the argument of that name. The method, host, headers and auth always
        come from this block.
      </p>
      {byName.tool_name && (
        <>
          <FieldRenderer field={byName.tool_name} config={config} outputs={outputs} onChange={onChange} />
          {nameError && <p className="-mt-3 mb-3 text-xs text-err">{nameError}</p>}
        </>
      )}
      {byName.tool_description && (
        <>
          <FieldRenderer field={byName.tool_description} config={config} outputs={outputs} onChange={onChange} />
          {description.trim().length < 20 && (
            <p className="-mt-3 mb-3 text-xs text-err">At least 20 characters: this is what tells the model when to use it.</p>
          )}
        </>
      )}
      <JsonObjectEditor
        key={`${node.id}-params`}
        label="Parameters (JSON Schema)"
        value={config.tool_parameters}
        fallback={{ type: "object", properties: {} }}
        rows={8}
        validate={(v) => {
          const schema = v as Record<string, unknown>;
          if (schema.type !== "object") return { error: 'The top level needs "type": "object".' };
          const unsupported = unsupportedKeywords(schema);
          return unsupported.length
            ? { warning: `Gemini may ignore: ${unsupported.join(", ")}. Arguments are still checked against the full schema.` }
            : {};
        }}
        onChange={(v) => onChange("tool_parameters", v)}
      />
      <JsonObjectEditor
        key={`${node.id}-static`}
        label="Static fields"
        value={config.tool_static_fields}
        fallback={{}}
        rows={3}
        description="Always sent, and they win over the model's values."
        onChange={(v) => onChange("tool_static_fields", v)}
      />
      {byName.tool_side_effects && (
        <FieldRenderer field={byName.tool_side_effects} config={config} outputs={outputs} onChange={onChange} />
      )}
      {byName.output_mapping && (
        <FieldRenderer field={byName.output_mapping} config={config} outputs={outputs} onChange={onChange} />
      )}
      <TestToolBox blockId={node.id} />
    </div>
  );
}

function TestToolBox({ blockId }: { blockId: string }) {
  const [args, setArgs] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Awaited<ReturnType<typeof testTool>> | null>(null);
  const [problems, setProblems] = useState<string[] | null>(null);

  const run = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(args.trim() || "{}");
    } catch (e) {
      setProblems([`Sample args aren't valid JSON: ${(e as Error).message}`]);
      return;
    }
    const { nodes, edges, pipelineId } = useEditorStore.getState();
    setBusy(true);
    setProblems(null);
    try {
      setResult(
        await testTool({ definition: flowToDefinition(nodes, edges), block_id: blockId, args: parsed, pipeline_id: pipelineId })
      );
    } catch (err) {
      setResult(null);
      if (err instanceof ApiError) setProblems(err.problems?.length ? err.problems : [err.message]);
      else toast.error("Couldn't test this tool");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 border-t border-[#E6DCF7] pt-3">
      <label className="mb-1.5 block text-xs font-medium text-ink-2">Sample args</label>
      <Textarea rows={3} value={args} spellCheck={false} onChange={(e) => setArgs(e.target.value)} />
      <Button variant="test" className="mt-2" onClick={run} disabled={busy}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />}
        {busy ? "Calling" : "Test tool"}
      </Button>
      {problems && (
        <div className="mt-2 rounded-md border border-[#F2C4BF] bg-err-bg p-2 text-xs text-[#B0342B]">
          {problems.map((p) => (
            <div key={p}>{p}</div>
          ))}
        </div>
      )}
      {result && (
        <div className="mt-2 space-y-2 text-xs">
          <div className={cn("flex items-center gap-1.5", result.ok ? "text-ok" : "text-err")}>
            {result.ok ? <CircleCheck className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
            {result.ok ? `OK${result.status ? ` (${result.status})` : ""}` : result.error ?? "Failed"}
            <span className="ml-auto text-ink-3">{result.duration_ms} ms</span>
          </div>
          <Pre label="Request" value={result.request} />
          <Pre label="The model would see" value={result.response} />
        </div>
      )}
    </div>
  );
}

export function Pre({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-3">{label}</div>
      <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-surface p-2 font-mono text-[11px] leading-relaxed">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/** The agent's Tools field: read-only, set by wiring on the canvas. */
export function ConnectedTools({ toolIds, nodes }: { toolIds: string[]; nodes: FlowNode[] }) {
  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-medium text-ink-2">Tools</label>
      {toolIds.length === 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-ink-3">
          <TriangleAlert className="h-3.5 w-3.5" />
          None yet. Drag an HTTP Request block's connector onto this agent's Tools handle.
        </p>
      ) : (
        <ul className="m-0 list-none space-y-1 p-0">
          {toolIds.map((id) => {
            const cfg = nodes.find((n) => n.id === id)?.data.config ?? {};
            return (
              <li key={id} className="flex items-center gap-2 rounded-md border border-line bg-surface px-2 py-1.5 text-xs">
                <Wrench className="h-3.5 w-3.5 text-llm" />
                <span className="font-mono">{String(cfg.tool_name || "(no name)")}</span>
                <span className="text-ink-3">
                  {String(cfg.method ?? "GET")} · {id}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
