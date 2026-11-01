import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createCredential, updateCredential } from "@/api/credentials";
import { ApiError } from "@/api/client";
import type { Credential } from "@/api/types";
import { useCredentialTypes } from "@/hooks/useCredentials";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Create a credential, or (with `credential`) rename it / replace its
 * secret. Secrets are write-only: an existing one is never shown, and
 * leaving the field blank on edit keeps it. */
export function CredentialDialog({
  open,
  onClose,
  credential,
  allowedTypes,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  credential?: Credential;
  /** Limit the types offered when creating (e.g. from a block's picker). */
  allowedTypes?: string[];
  onSaved?: (credential: Credential) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        {/* Remounted per open, so the form always starts empty. */}
        {open && (
          <CredentialForm credential={credential} allowedTypes={allowedTypes} onClose={onClose} onSaved={onSaved} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function CredentialForm({
  credential,
  allowedTypes,
  onClose,
  onSaved,
}: {
  credential?: Credential;
  allowedTypes?: string[];
  onClose: () => void;
  onSaved?: (credential: Credential) => void;
}) {
  const queryClient = useQueryClient();
  const { data: allTypes = [] } = useCredentialTypes();
  const types = allowedTypes ? allTypes.filter((t) => allowedTypes.includes(t.type)) : allTypes;
  const editing = !!credential;

  const [name, setName] = useState(credential?.name ?? "");
  const [pickedType, setPickedType] = useState<string>("");
  const typeId = credential?.type ?? (pickedType || types[0]?.type || "");
  const typeSpec = allTypes.find((t) => t.type === typeId);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const anySecret = Object.values(secrets).some((v) => v.trim());
  const allSecrets = !!typeSpec && typeSpec.fields.every((f) => secrets[f.name]?.trim());
  const canSave = name.trim() && (editing ? name.trim() !== credential.name || allSecrets : allSecrets && typeId);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? updateCredential(credential.id, {
            ...(name.trim() !== credential.name ? { name: name.trim() } : {}),
            ...(anySecret ? { data: secrets } : {}),
          })
        : createCredential({ name: name.trim(), type: typeId, data: secrets }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      toast.success(editing ? `${saved.name} updated` : `${saved.name} saved`);
      onSaved?.(saved);
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Couldn't save the credential"),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave && !save.isPending) save.mutate();
      }}
    >
      <DialogTitle>{editing ? `Edit ${credential.name}` : "New credential"}</DialogTitle>
      <DialogDescription>
        {editing
          ? "Rename it, or paste a new key to replace the saved one. The saved key is never shown."
          : "The key is encrypted on the server and never shown again. Workflows refer to it by name."}
      </DialogDescription>

      {!editing && types.length > 1 && (
        <div className="mb-3">
          <Label htmlFor="cred-type">Type</Label>
          <select
            id="cred-type"
            value={typeId}
            onChange={(e) => setPickedType(e.target.value)}
            className="mt-1.5 min-h-[34px] w-full rounded-[7px] border border-line-2 bg-surface px-2.5 py-1.5 text-[13px] text-ink"
          >
            {types.map((t) => (
              <option key={t.type} value={t.type}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="mb-3">
        <Label htmlFor="cred-name">Name</Label>
        <Input
          id="cred-name"
          className="mt-1.5"
          value={name}
          placeholder={typeSpec ? `e.g. Acme ${typeSpec.label}` : ""}
          autoFocus
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {typeSpec?.fields.map((f) => (
        <div key={f.name} className="mb-3">
          <Label htmlFor={`cred-${f.name}`}>
            {editing ? `New ${f.label.toLowerCase()}` : f.label}
            {editing && <span className="ml-1 font-normal text-ink-3">(saved: {credential.hint})</span>}
          </Label>
          <Input
            id={`cred-${f.name}`}
            className="mt-1.5"
            type="password"
            autoComplete="off"
            value={secrets[f.name] ?? ""}
            placeholder={editing ? "Leave blank to keep the saved key" : ""}
            onChange={(e) => setSecrets((s) => ({ ...s, [f.name]: e.target.value }))}
          />
        </div>
      ))}

      {error && <p className="mb-2 text-xs text-err">{error}</p>}

      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" onClick={onClose} disabled={save.isPending}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
