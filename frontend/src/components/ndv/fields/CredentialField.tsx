import { useState } from "react";
import { Plus } from "lucide-react";
import { useCredentials } from "@/hooks/useCredentials";
import { CredentialDialog } from "@/components/credentials/CredentialDialog";
import { Button } from "@/components/ui/button";

/** Picks a saved credential by id. The secret itself never reaches the
 * editor or the workflow definition; "+ New" saves one and selects it. */
export function CredentialField({
  label,
  value,
  credentialTypes,
  placeholder,
  description,
  onChange,
}: {
  label: string;
  value: unknown;
  credentialTypes?: string[];
  placeholder?: string;
  description?: string;
  onChange: (value: string) => void;
}) {
  const { data: credentials = [], isLoading } = useCredentials();
  const [creating, setCreating] = useState(false);
  const selected = typeof value === "string" ? value : "";
  const usable = credentials.filter((c) => !credentialTypes?.length || credentialTypes.includes(c.type));
  const missing = selected && !isLoading && !credentials.some((c) => c.id === selected);

  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-medium text-ink-2" htmlFor="credential-select">
        {label}
      </label>
      <div className="flex gap-2">
        <select
          id="credential-select"
          value={selected}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-[34px] min-w-0 flex-1 rounded-[7px] border border-line-2 bg-surface px-2.5 py-1.5 text-[13px] text-ink"
        >
          <option value="">{placeholder ?? "None"}</option>
          {usable.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.hint})
            </option>
          ))}
          {missing && <option value={selected}>Deleted credential</option>}
        </select>
        <Button type="button" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          New
        </Button>
      </div>
      {missing && <div className="mt-1 text-xs text-err">This credential was deleted. Pick another one.</div>}
      {description && <div className="mt-1 text-[11px] text-ink-3">{description}</div>}
      <CredentialDialog
        open={creating}
        onClose={() => setCreating(false)}
        allowedTypes={credentialTypes}
        onSaved={(c) => onChange(c.id)}
      />
    </div>
  );
}
