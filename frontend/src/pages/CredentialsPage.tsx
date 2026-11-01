import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteCredential } from "@/api/credentials";
import { ApiError } from "@/api/client";
import type { Credential } from "@/api/types";
import { useCredentials } from "@/hooks/useCredentials";
import { CredentialDialog } from "@/components/credentials/CredentialDialog";
import { RelativeTime } from "@/components/RelativeTime";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

const GRID = "grid grid-cols-[minmax(0,2fr)_1.2fr_90px_1fr_76px] items-center gap-2";

export function CredentialsPage() {
  const { data: credentials = [], isLoading, isError } = useCredentials();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Credential | null>(null);
  const [deleting, setDeleting] = useState<Credential | null>(null);

  return (
    <div className="mx-auto h-full max-w-[1080px] overflow-auto p-6 sm:p-8">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="m-0 text-[22px] font-semibold">Credentials</h1>
          <p className="mt-1 text-ink-3">
            Your own API keys, encrypted on the server. Blocks use them by name; a saved key is never shown again.
          </p>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          New credential
        </Button>
      </div>

      <div className="overflow-hidden rounded-[10px] border border-line bg-surface">
        <div className={`${GRID} bg-panel px-4 py-2 text-xs text-ink-3`}>
          <span>Name</span>
          <span>Type</span>
          <span>Key</span>
          <span>Updated</span>
          <span />
        </div>
        {isLoading && <div className="p-8 text-center text-ink-3">Loading…</div>}
        {isError && <div className="p-8 text-center text-err">Couldn't load credentials.</div>}
        {!isLoading && !isError && credentials.length === 0 && (
          <div className="p-8 text-center text-ink-3">
            <KeyRound className="mx-auto mb-2 h-6 w-6" aria-hidden="true" />
            No credentials yet. Add your Gemini API key to use it in LLM blocks.
          </div>
        )}
        {credentials.map((c) => (
          <div key={c.id} className={`${GRID} border-t border-line px-4 py-3 text-[13px]`}>
            <span className="truncate font-semibold">{c.name}</span>
            <span className="text-ink-2">{c.type_label}</span>
            <span className="font-mono text-xs text-ink-3">{c.hint}</span>
            <RelativeTime iso={c.updated_at} className="text-xs text-ink-3" />
            <span className="flex justify-end gap-1">
              <Button size="icon" variant="ghost" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button size="icon" variant="ghost" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)}>
                <Trash2 className="h-3.5 w-3.5 text-err" />
              </Button>
            </span>
          </div>
        ))}
      </div>

      <CredentialDialog open={creating} onClose={() => setCreating(false)} />
      <CredentialDialog open={!!editing} credential={editing ?? undefined} onClose={() => setEditing(null)} />
      <DeleteCredentialDialog credential={deleting} onClose={() => setDeleting(null)} />
    </div>
  );
}

function DeleteCredentialDialog({ credential, onClose }: { credential: Credential | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (c: Credential) => deleteCredential(c.id),
    onSuccess: (_d, c) => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      toast.success(`${c.name} deleted`);
      close();
    },
    // 409 when a workflow still uses it: keep the dialog open with the reason.
    onError: (err) => setError(err instanceof ApiError ? err.message : "Couldn't delete the credential"),
  });
  const close = () => {
    setError(null);
    onClose();
  };

  return (
    <Dialog open={!!credential} onOpenChange={(o) => !o && !remove.isPending && close()}>
      <DialogContent hideClose>
        <DialogTitle>Delete {credential?.name}?</DialogTitle>
        <DialogDescription>
          The key is removed from the server for good. Workflows that use it must pick another one first.
        </DialogDescription>
        {error && <p className="text-xs text-err">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={close} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending || !!error}
            onClick={() => credential && remove.mutate(credential)}
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
