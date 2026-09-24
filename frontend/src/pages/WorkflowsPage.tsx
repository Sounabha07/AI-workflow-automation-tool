import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronRight, Plus, Search } from "lucide-react";
import { toast } from "sonner";
import { createPipeline, listPipelines, patchPipelineActive } from "@/api/pipelines";
import type { PipelineListItem } from "@/api/types";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { StatusPill } from "@/components/StatusPill";
import { RelativeTime } from "@/components/RelativeTime";
import { useRunEvents } from "@/hooks/useRunEvents";
import { cn } from "@/lib/utils";

type FilterTab = "all" | "active" | "inactive";

export function WorkflowsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");

  const { data: pipelines = [], isLoading, isError } = useQuery({
    queryKey: ["pipelines"],
    queryFn: listPipelines,
  });

  useRunEvents("all", (event) => {
    if (event.type === "run_status") {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    }
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      patchPipelineActive(id, is_active),
    onMutate: async ({ id, is_active }) => {
      await queryClient.cancelQueries({ queryKey: ["pipelines"] });
      const previous = queryClient.getQueryData<PipelineListItem[]>(["pipelines"]);
      queryClient.setQueryData<PipelineListItem[]>(["pipelines"], (old) =>
        old?.map((p) => (p.id === id ? { ...p, is_active } : p))
      );
      return { previous };
    },
    onError: (err, _vars, context) => {
      queryClient.setQueryData(["pipelines"], context?.previous);
      toast.error(err instanceof ApiError ? err.message : "Couldn't update this workflow");
    },
    onSuccess: (_data, { id, is_active }) => {
      const name = queryClient.getQueryData<PipelineListItem[]>(["pipelines"])?.find((p) => p.id === id)?.name;
      toast.success(`${name ?? "Workflow"} is now ${is_active ? "active" : "inactive"}`);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["pipelines"] }),
  });

  const createWorkflow = useMutation({
    mutationFn: async () => {
      const existing = new Set(pipelines.map((p) => p.name));
      let n = 1;
      while (existing.has(`untitled_${n}`)) n++;
      const name = `untitled_${n}`;
      return createPipeline(name, {
        blocks: {
          trigger: {
            type: "manual_trigger",
            config: {},
            depends_on: [],
            next: [],
            position: { x: 80, y: 200 },
            notes: "",
          },
        },
      });
    },
    onSuccess: (pipeline) => {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      navigate(`/workflows/${pipeline.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't create workflow"),
  });

  const counts = useMemo(
    () => ({
      all: pipelines.length,
      active: pipelines.filter((p) => p.is_active).length,
      inactive: pipelines.filter((p) => !p.is_active).length,
    }),
    [pipelines]
  );

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return pipelines.filter(
      (p) =>
        (tab === "all" || (tab === "active") === p.is_active) &&
        p.name.toLowerCase().includes(q)
    );
  }, [pipelines, tab, search]);

  return (
    <div className="mx-auto h-full max-w-[1080px] overflow-auto p-6 sm:p-8">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="m-0 text-[22px] font-semibold">Workflows</h1>
          <p className="mt-1 text-ink-3">
            Active workflows run automatically when their trigger fires. You can always run any
            workflow manually.
          </p>
        </div>
        <Button variant="primary" onClick={() => createWorkflow.mutate()} disabled={createWorkflow.isPending}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          New workflow
        </Button>
      </div>

      <div className="mb-3 flex items-center gap-2.5">
        <div className="flex overflow-hidden rounded-[7px] border border-line-2">
          {(["all", "active", "inactive"] as FilterTab[]).map((f) => (
            <button
              key={f}
              onClick={() => setTab(f)}
              className={cn(
                "border-0 bg-surface px-2.5 py-1 text-xs text-ink-2",
                tab === f && "bg-ink text-white"
              )}
            >
              {f[0].toUpperCase() + f.slice(1)} {counts[f]}
            </button>
          ))}
        </div>
        <div className="flex h-8 w-[260px] items-center gap-1.5 rounded-[7px] border border-line-2 bg-surface px-2.5">
          <Search className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search workflows"
            aria-label="Search workflows"
            className="flex-1 border-0 bg-transparent text-[13px] outline-none"
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-[10px] border border-line bg-surface">
        <div className="grid grid-cols-[minmax(0,2.2fr)_130px_1.4fr_1fr_24px] items-center gap-2 bg-panel px-4 py-2 text-xs text-ink-3">
          <span>Name</span>
          <span>Status</span>
          <span>Last run</span>
          <span>Updated</span>
          <span />
        </div>

        {isLoading && <div className="p-8 text-center text-ink-3">Loading…</div>}
        {isError && <div className="p-8 text-center text-err">Couldn't load workflows.</div>}
        {!isLoading && !isError && rows.length === 0 && (
          <div className="p-8 text-center text-ink-3">
            No workflows match. Clear the search or create a new workflow.
          </div>
        )}
        {rows.map((p) => (
          <div
            key={p.id}
            role="link"
            tabIndex={0}
            onClick={() => navigate(`/workflows/${p.id}`)}
            onKeyDown={(e) => e.key === "Enter" && navigate(`/workflows/${p.id}`)}
            className="grid cursor-pointer grid-cols-[minmax(0,2.2fr)_130px_1.4fr_1fr_24px] items-center gap-2 border-t border-line px-4 py-3 text-[13px] hover:bg-panel"
          >
            <div>
              <div className="font-semibold">{p.name}</div>
              <div className="mt-0.5 text-xs text-ink-3">{p.block_count} blocks</div>
            </div>
            <div className="flex items-center gap-2 text-xs text-ink-2" onClick={(e) => e.stopPropagation()}>
              <Switch
                checked={p.is_active}
                aria-label={`${p.name} active`}
                onCheckedChange={(checked) => toggleActive.mutate({ id: p.id, is_active: checked })}
              />
              {p.is_active ? "Active" : "Inactive"}
            </div>
            <span className="flex items-center gap-1">
              <StatusPill status={p.last_run_status} />
              {p.last_run_at && <RelativeTime iso={p.last_run_at} className="text-xs text-ink-3" />}
            </span>
            <span className="text-ink-3">
              <RelativeTime iso={p.updated_at} />
            </span>
            <ChevronRight className="h-4 w-4 text-ink-3" aria-hidden="true" />
          </div>
        ))}
      </div>
    </div>
  );
}
