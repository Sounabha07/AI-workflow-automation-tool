import { Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";

const OPERATORS = [
  { value: "equals", label: "is equal to" },
  { value: "not_equals", label: "is not equal to" },
  { value: "contains", label: "contains" },
  { value: "greater_than", label: "is greater than" },
  { value: "less_than", label: "is less than" },
  { value: "is_empty", label: "is empty" },
];

export interface SwitchRule {
  operator: string;
  compare_value: string;
  output: string;
}

export function SwitchRulesField({
  value,
  onChange,
}: {
  value: SwitchRule[];
  onChange: (value: SwitchRule[]) => void;
}) {
  const rules = Array.isArray(value) ? value : [];
  const update = (i: number, patch: Partial<SwitchRule>) =>
    onChange(rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const remove = (i: number) => onChange(rules.filter((_, idx) => idx !== i));

  return (
    <div className="mb-4">
      <div className="mb-1.5 text-xs font-semibold text-ink-2">Routing rules</div>
      <div className="rounded-lg border border-line bg-panel p-2.5">
        {rules.map((r, i) => (
          <div key={i} className="mb-2 grid grid-cols-2 gap-2 border-b border-line pb-2 last:mb-0 last:border-0">
            <select
              value={r.operator}
              onChange={(e) => update(i, { operator: e.target.value })}
              className="h-[34px] rounded-[7px] border border-line-2 bg-surface px-2 text-[13px]"
            >
              {OPERATORS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            {r.operator !== "is_empty" ? (
              <Input
                aria-label="Compare to"
                value={r.compare_value}
                onChange={(e) => update(i, { compare_value: e.target.value })}
              />
            ) : (
              <span />
            )}
            <div className="col-span-2 flex items-center gap-2 text-xs text-ink-3">
              Send to output
              <Input
                aria-label="Output name"
                value={r.output}
                onChange={(e) => update(i, { output: e.target.value })}
                className="flex-1"
              />
              <button onClick={() => remove(i)} aria-label="Remove rule" className="border-0 bg-transparent p-1 text-ink-3 hover:text-err">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            onChange([...rules, { operator: "equals", compare_value: "", output: `output_${rules.length + 1}` }])
          }
          className="w-full cursor-pointer rounded-lg border-[1.5px] border-dashed border-line-2 p-2 text-center text-xs text-accent underline"
        >
          Add rule
        </button>
      </div>
    </div>
  );
}
