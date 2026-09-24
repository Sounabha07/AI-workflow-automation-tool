import { Braces, Brackets, CircleOff, Hash, ToggleLeft, Type, ChevronDown } from "lucide-react";
import { EXPRESSION_MIME } from "@/lib/dnd";
import { buildExpression } from "@/lib/expressions";

export type ViewMode = "schema" | "table" | "json";

function typeIcon(v: unknown) {
  if (Array.isArray(v)) return Brackets;
  if (v === null) return CircleOff;
  if (typeof v === "object") return Braces;
  if (typeof v === "number") return Hash;
  if (typeof v === "boolean") return ToggleLeft;
  return Type;
}

function SchemaRows({ obj, prefix, baseId, depth }: { obj: Record<string, unknown>; prefix: string; baseId: string; depth: number }) {
  return (
    <>
      {Object.entries(obj).map(([k, v]) => {
        const path = prefix ? `${prefix}.${k}` : k;
        const pad = 6 + depth * 16;
        const isNested = v && typeof v === "object" && !Array.isArray(v);
        if (isNested) {
          return (
            <div key={path}>
              <div className="flex items-center gap-1.5 rounded py-0.5" style={{ paddingLeft: pad }}>
                <ChevronDown className="h-3.5 w-3.5 text-ink-3" />
                <span className="font-mono text-xs">{k}</span>
              </div>
              <SchemaRows obj={v as Record<string, unknown>} prefix={path} baseId={baseId} depth={depth + 1} />
            </div>
          );
        }
        const Icon = typeIcon(v);
        return (
          <div
            key={path}
            draggable
            title="Drag into a parameter"
            onDragStart={(e) => e.dataTransfer.setData(EXPRESSION_MIME, buildExpression(baseId, path))}
            style={{ paddingLeft: pad }}
            className="flex cursor-grab items-center gap-1.5 rounded py-0.5 pr-1.5 hover:bg-accent-bg [&:hover_.k]:text-accent"
          >
            <Icon className="h-3.5 w-3.5 flex-none text-ink-3" />
            <span className="k font-mono text-xs">{k}</span>
            <span className="ml-auto min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-xs text-ink-3">
              {JSON.stringify(v)}
            </span>
          </div>
        );
      })}
    </>
  );
}

function flatten(obj: Record<string, unknown>, prefix = "", out: [string, unknown][] = []): [string, unknown][] {
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      flatten(v as Record<string, unknown>, path, out);
    } else {
      out.push([path, v]);
    }
  }
  return out;
}

function JsonView({ data }: { data: unknown }) {
  const text = JSON.stringify(data, null, 2);
  const html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/("[^"]*")(\s*:)/g, '<span class="text-[#5A3FC0]">$1</span>$2')
    .replace(/: ("[^"]*")/g, ': <span class="text-[#157A4A]">$1</span>')
    .replace(/: (-?\d+\.?\d*)/g, ': <span class="text-[#B4580E]">$1</span>');
  return (
    <pre
      className="m-0 whitespace-pre-wrap break-all font-mono text-xs leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function DataView({ data, mode, baseId }: { data: unknown; mode: ViewMode; baseId: string }) {
  if (mode === "json") return <JsonView data={data} />;

  if (mode === "table") {
    const isObject = !!data && typeof data === "object" && !Array.isArray(data);
    const rows = isObject ? flatten(data as Record<string, unknown>) : [["value", data] as [string, unknown]];
    return (
      <table className="w-full border-collapse text-xs">
        <tbody>
          {rows.map(([k, v]) => (
            <tr
              key={k}
              draggable
              title="Drag into a parameter"
              onDragStart={(e) => e.dataTransfer.setData(EXPRESSION_MIME, buildExpression(baseId, isObject ? k : ""))}
              className="cursor-grab hover:bg-accent-bg [&:hover_td:first-child]:text-accent"
            >
              <td className="w-[45%] border-b border-line py-1.5 pr-1 align-top font-mono text-ink-2">{k}</td>
              <td className="break-all border-b border-line py-1.5 align-top font-mono">{JSON.stringify(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return (
      <div
        draggable
        onDragStart={(e) => e.dataTransfer.setData(EXPRESSION_MIME, buildExpression(baseId, ""))}
        className="flex cursor-grab items-center gap-1.5 rounded py-0.5 pl-1.5 hover:bg-accent-bg"
      >
        <Type className="h-3.5 w-3.5 text-ink-3" />
        <span className="font-mono text-xs text-ink-3">{JSON.stringify(data)}</span>
      </div>
    );
  }
  return <SchemaRows obj={data as Record<string, unknown>} prefix="" baseId={baseId} depth={0} />;
}
