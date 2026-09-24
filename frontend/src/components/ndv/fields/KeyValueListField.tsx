import { Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { ScalarField } from "./ScalarField";
import { EXPRESSION_MIME } from "@/lib/dnd";
import { cn } from "@/lib/utils";

interface KVPair {
  key: string;
  value: unknown;
}

export function KeyValueListField({
  label,
  value,
  onChange,
  outputs,
}: {
  label: string;
  value: KVPair[];
  onChange: (value: KVPair[]) => void;
  outputs: Record<string, unknown>;
}) {
  const pairs = Array.isArray(value) ? value : [];

  const updatePair = (i: number, patch: Partial<KVPair>) => {
    onChange(pairs.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  };
  const removePair = (i: number) => onChange(pairs.filter((_, idx) => idx !== i));

  return (
    <div className="mb-4">
      <div className="mb-1.5 text-xs font-semibold text-ink-2">{label}</div>
      <div className="rounded-lg border border-line bg-panel p-2.5">
        {pairs.map((p, i) => (
          <div key={i} className="mb-2.5 grid grid-cols-[110px_1fr_24px] items-start gap-2 last:mb-0">
            <Input
              aria-label="Key"
              value={p.key}
              onChange={(e) => updatePair(i, { key: e.target.value })}
              className="mt-0"
            />
            <div className="[&>div]:mb-0">
              <ScalarField
                label=""
                value={p.value}
                fieldType="string"
                outputs={outputs}
                onChange={(v) => updatePair(i, { value: v })}
              />
            </div>
            <button
              onClick={() => removePair(i)}
              aria-label="Remove"
              className="mt-1.5 border-0 bg-transparent p-1 text-ink-3 hover:text-err"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <DropZone
          onAdd={(key) => onChange([...pairs, { key, value: "" }])}
          onAddExpr={(key, expr) => onChange([...pairs, { key, value: expr }])}
        />
      </div>
    </div>
  );
}

function DropZone({
  onAdd,
  onAddExpr,
}: {
  onAdd: (key: string) => void;
  onAddExpr: (key: string, expr: string) => void;
}) {
  return (
    <div
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(EXPRESSION_MIME)) e.preventDefault();
      }}
      onDrop={(e) => {
        const expr = e.dataTransfer.getData(EXPRESSION_MIME);
        if (!expr) return;
        e.preventDefault();
        const m = expr.match(/\.([\w]+)\s*\}\}$/);
        onAddExpr(m ? m[1] : "field", expr);
      }}
      className={cn(
        "rounded-lg border-[1.5px] border-dashed border-line-2 p-3 text-center text-xs text-ink-3"
      )}
    >
      Drag input fields here or{" "}
      <button type="button" onClick={() => onAdd("")} className="cursor-pointer border-0 bg-transparent p-0 text-accent underline">
        add a field
      </button>
    </div>
  );
}
