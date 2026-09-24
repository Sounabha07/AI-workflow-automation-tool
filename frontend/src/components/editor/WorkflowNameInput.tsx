import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { updatePipeline } from "@/api/pipelines";
import { ApiError } from "@/api/client";
import { applyPipelineUpdate } from "@/lib/pipelineCache";
import { useEditorStore } from "@/store/editor";

/** The workflow name in the editor bar: plain text until focused, then an
 * input. Blur/Enter saves (PUT name only), Escape reverts, empty reverts. */
export function WorkflowNameInput({ pipelineId, name }: { pipelineId: string; name: string }) {
  const queryClient = useQueryClient();
  const setPipelineMeta = useEditorStore((s) => s.setPipelineMeta);
  const [draft, setDraft] = useState(name);
  const [focused, setFocused] = useState(false);
  const cancelled = useRef(false);

  // Follow external name changes (load, save-as-new) while not editing.
  useEffect(() => {
    if (!focused) setDraft(name);
  }, [name, focused]);

  const rename = useMutation({
    mutationFn: (next: string) => updatePipeline(pipelineId, { name: next }),
    onSuccess: (pipeline) => {
      setPipelineMeta(pipeline.id, pipeline.name);
      applyPipelineUpdate(queryClient, pipeline);
      toast.success(`Renamed to ${pipeline.name}`);
    },
    onError: (err) => {
      setDraft(name);
      toast.error(err instanceof ApiError ? `Couldn't rename: ${err.message}` : "Couldn't rename this workflow");
    },
  });

  const commit = () => {
    setFocused(false);
    if (cancelled.current) {
      cancelled.current = false;
      setDraft(name);
      return;
    }
    const next = draft.trim();
    if (!next) {
      setDraft(name);
      toast.error("A workflow name can't be empty");
      return;
    }
    if (next === name) {
      setDraft(name);
      return;
    }
    setDraft(next);
    rename.mutate(next);
  };

  return (
    // Grid autosize: the invisible span sizes the cell, the input fills it.
    <span className="relative inline-grid min-w-[4ch] max-w-[40vw]">
      <span aria-hidden="true" className="invisible col-start-1 row-start-1 whitespace-pre px-1.5 font-semibold">
        {draft || " "}
      </span>
      <input
        aria-label="Workflow name"
        value={draft}
        disabled={rename.isPending}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={(e) => {
          setFocused(true);
          e.currentTarget.select();
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            cancelled.current = true;
            e.currentTarget.blur();
          }
        }}
        className="col-start-1 row-start-1 w-full min-w-0 cursor-text rounded-md border border-transparent bg-transparent px-1.5 py-0.5 font-semibold text-ink outline-none hover:border-line focus:border-accent focus:bg-surface disabled:opacity-60"
      />
    </span>
  );
}
