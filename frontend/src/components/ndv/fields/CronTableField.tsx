import { useState } from "react";

const CRON_FIELDS = [
  { label: "Minute", allowed: "0–59", example: "0, */15, 30" },
  { label: "Hour", allowed: "0–23", example: "9, 9-17, */2" },
  { label: "Day of month", allowed: "1–31", example: "1, 15, 1-7" },
  { label: "Month", allowed: "1–12 or JAN–DEC", example: "1, JAN, 6-8" },
  { label: "Day of week", allowed: "0–6 (Sun=0) or SUN–SAT", example: "1-5, MON, 0,6" },
] as const;

/** Splits a cron string into its 5 fields, padding with "*" (a saved
 * expression with the wrong field count shows what it can). */
function splitCron(cron: string): string[] {
  const parts = cron.trim().split(/\s+/).filter(Boolean).slice(0, 5);
  while (parts.length < 5) parts.push("*");
  return parts;
}

/** The schedule trigger's cron expression as a table: one row per field.
 * Writes back the usual 5-field string; the backend validates it and the
 * preview below shows what it means. */
export function CronTableField({ value, onChange }: { value: string; onChange: (cron: string) => void }) {
  // Cells keep what was typed (an empty cell is shown empty, saved as "*").
  const [cells, setCells] = useState(() => splitCron(value));

  const setCell = (i: number, raw: string) => {
    const next = [...cells];
    next[i] = raw.replace(/\s+/g, ""); // a space would split the field in two
    setCells(next);
    onChange(next.map((c) => c || "*").join(" "));
  };

  return (
    <div className="mb-4">
      <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-ink-2">
        Schedule <span className="text-err">*</span>
        <code className="ml-auto rounded bg-panel px-1.5 py-0.5 font-mono text-[11px] text-ink-2">
          {cells.map((c) => c || "*").join(" ")}
        </code>
      </div>
      <table className="w-full border-collapse overflow-hidden rounded-[7px] border border-line-2 text-[13px]">
        <thead>
          <tr className="bg-panel text-left text-[11px] text-ink-3">
            <th className="px-2.5 py-1.5 font-medium">Field</th>
            <th className="w-[38%] px-2.5 py-1.5 font-medium">Value</th>
            <th className="px-2.5 py-1.5 font-medium">Allowed</th>
          </tr>
        </thead>
        <tbody>
          {CRON_FIELDS.map((f, i) => (
            <tr key={f.label} className="border-t border-line">
              <td className="px-2.5 py-1 text-ink-2">
                <label htmlFor={`cron-${i}`}>{f.label}</label>
              </td>
              <td className="px-1.5 py-1">
                <input
                  id={`cron-${i}`}
                  value={cells[i]}
                  placeholder="*"
                  onChange={(e) => setCell(i, e.target.value)}
                  className="w-full rounded-md border border-line-2 bg-surface px-2 py-1 font-mono text-[13px] text-ink outline-none focus:border-accent"
                />
              </td>
              <td className="px-2.5 py-1 text-[11px] text-ink-3" title={`e.g. ${f.example}`}>
                {f.allowed}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mb-0 mt-1.5 text-[11px] text-ink-3">
        <code className="font-mono">*</code> any · <code className="font-mono">*/15</code> every 15 ·{" "}
        <code className="font-mono">1-5</code> range · <code className="font-mono">1,15</code> list. Hover a row's
        allowed values for examples.
      </p>
    </div>
  );
}
