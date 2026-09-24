import { Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

interface FieldDef {
  name: string;
  type?: "text" | "json";
  required?: boolean;
}

export function FieldDefinitionsField({
  value,
  onChange,
}: {
  value: FieldDef[];
  onChange: (value: FieldDef[]) => void;
}) {
  const fields = Array.isArray(value) ? value : [];
  const update = (i: number, patch: Partial<FieldDef>) =>
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const remove = (i: number) => onChange(fields.filter((_, idx) => idx !== i));

  return (
    <div className="mb-4">
      <div className="mb-1.5 text-xs font-semibold text-ink-2">
        Input fields the user fills in when starting a run
      </div>
      <div className="rounded-lg border border-line bg-panel p-2.5">
        {fields.map((f, i) => (
          <div key={i} className="mb-2.5 grid grid-cols-[1fr_90px_auto_24px] items-center gap-2 last:mb-0">
            <Input aria-label="Field name" value={f.name} onChange={(e) => update(i, { name: e.target.value })} />
            <select
              value={f.type ?? "text"}
              onChange={(e) => update(i, { type: e.target.value as "text" | "json" })}
              className="h-[34px] rounded-[7px] border border-line-2 bg-surface px-2 text-[13px]"
            >
              <option value="text">Text</option>
              <option value="json">JSON</option>
            </select>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <Switch checked={!!f.required} onCheckedChange={(v) => update(i, { required: v })} />
              Required
            </label>
            <button onClick={() => remove(i)} aria-label="Remove field" className="border-0 bg-transparent p-1 text-ink-3 hover:text-err">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => onChange([...fields, { name: `field_${fields.length + 1}`, type: "text", required: false }])}
          className="cursor-pointer rounded-lg border-[1.5px] border-dashed border-line-2 p-2 w-full text-center text-xs text-accent underline"
        >
          Add field
        </button>
      </div>
    </div>
  );
}
