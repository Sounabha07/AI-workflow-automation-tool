import type { FieldOption } from "@/api/types";

export function OptionsField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: FieldOption[];
  onChange: (value: string) => void;
}) {
  // A saved value that's no longer listed must still show as what will run.
  const unlisted = value && !options.some((o) => o.value === value);

  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-medium text-ink-2">{label}</label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-[34px] w-full rounded-[7px] border border-line-2 bg-surface px-2.5 py-1.5 text-[13px] text-ink"
      >
        {unlisted && <option value={value}>{value} (not in list)</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
