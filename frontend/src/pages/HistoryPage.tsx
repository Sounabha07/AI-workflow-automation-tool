import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronUp, Search } from "lucide-react";
import { listRuns } from "@/api/runs";
import type { RunListItem, RunStatus } from "@/api/types";
import { StatusPill } from "@/components/StatusPill";
import { RelativeTime } from "@/components/RelativeTime";
import { RunDetail } from "@/components/history/RunDetail";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useRunEvents } from "@/hooks/useRunEvents";
import { firstSentence } from "@/lib/errorHints";
import { formatDuration } from "@/lib/time";
import { cn } from "@/lib/utils";

const STATUS_TABS: { label: string; value: RunStatus | "" }[] = [
  { label: "All", value: "" },
  { label: "Succeeded", value: "succeeded" },
  { label: "Failed", value: "failed" },
  { label: "Running", value: "running" },
];

export function HistoryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [nameFilter, setNameFilter] = useState("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<RunListItem[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const debouncedName = useDebouncedValue(nameFilter, 300);

  useEffect(() => setOffset(0), [debouncedName, status]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["runs", debouncedName, status, offset],
    queryFn: () => listRuns({ pipeline_name: debouncedName, status: status || undefined, limit: 50, offset }),
  });

  useEffect(() => {
    if (!data) return;
    setItems((prev) => (offset === 0 ? data.items : [...prev, ...data.items]));
  }, [data, offset]);

  useRunEvents("all", (event) => {
    if (event.type === "run_status") {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });

  const total = data?.total ?? 0;
  const hasMore = items.length < total;

  const pipelineNames = useMemo(() => [...new Set(items.map((r) => r.pipeline_name))], [items]);

  return (
    <div className="mx-auto h-full max-w-[1080px] overflow-auto p-6 sm:p-8">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="m-0 text-[22px] font-semibold">Run history</h1>
          <p className="mt-1 text-ink-3">Click a run to open it on the canvas. Use the arrow to preview it here.</p>
        </div>
      </div>

      <div className="mb-3 flex items-center gap-2.5">
        <div className="flex h-8 w-[260px] items-center gap-1.5 rounded-[7px] border border-line-2 bg-surface px-2.5">
          <Search className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
          <input
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            placeholder="Filter by workflow name"
            aria-label="Filter by workflow name"
            list="wfNames"
            className="flex-1 border-0 bg-transparent text-[13px] outline-none"
          />
          <datalist id="wfNames">
            {pipelineNames.map((n) => (
              <option key={n} value={n} />
            ))}
          </datalist>
        </div>
        <div className="flex overflow-hidden rounded-[7px] border border-line-2">
          {STATUS_TABS.map((t) => (
            <button
              key={t.label}
              onClick={() => setStatus(t.value)}
              className={cn(
                "border-0 bg-surface px-2.5 py-1 text-xs text-ink-2",
                status === t.value && "bg-ink text-white"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-[10px] border border-line bg-surface">
        <div className="grid grid-cols-[120px_minmax(0,1.6fr)_100px_1.2fr_80px_1fr_32px] items-center gap-2 bg-panel px-4 py-2 text-xs text-ink-3">
          <span>Status</span>
          <span>Workflow</span>
          <span>Run</span>
          <span>Started</span>
          <span>Duration</span>
          <span>Blocks run</span>
          <span />
        </div>

        {isLoading && offset === 0 && <div className="p-8 text-center text-ink-3">Loading…</div>}
        {isError && <div className="p-8 text-center text-err">Couldn't load run history.</div>}
        {!isLoading && !isError && items.length === 0 && (
          <div className="p-8 text-center text-ink-3">No runs match these filters.</div>
        )}

        {items.map((r) => (
          <div key={r.id} className={cn(openId === r.id && "bg-panel")}>
            <div
              role="link"
              tabIndex={0}
              onClick={() => navigate(`/workflows/${r.pipeline_id}/runs/${r.id}`)}
              onKeyDown={(e) => e.key === "Enter" && navigate(`/workflows/${r.pipeline_id}/runs/${r.id}`)}
              className="grid cursor-pointer grid-cols-[120px_minmax(0,1.6fr)_100px_1.2fr_80px_1fr_32px] items-center gap-2 border-t border-line px-4 py-3 text-[13px] hover:bg-panel"
            >
              <StatusPill status={r.status} />
              <div className="min-w-0">
                <div className="font-semibold">{r.pipeline_name}</div>
                {r.error_summary && (
                  <div className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[#B0342B]">
                    {r.error_summary.block_id}: {firstSentence(r.error_summary.message)}
                  </div>
                )}
              </div>
              <span className="font-mono text-xs text-ink-2">{r.id.slice(0, 8)}</span>
              <RelativeTime iso={r.started_at ?? r.created_at} />
              <span className="text-ink-3">{formatDuration(r.duration_ms) || (r.status === "running" ? "running" : "")}</span>
              <span className="text-ink-3">
                {r.blocks_ran} of {r.total_blocks}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setOpenId(openId === r.id ? null : r.id);
                }}
                aria-label="Preview run"
                aria-expanded={openId === r.id}
                className="rounded p-1 text-ink-3 hover:bg-line"
              >
                {openId === r.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
            </div>
            {openId === r.id && <RunDetail run={r} />}
          </div>
        ))}
      </div>

      {hasMore && (
        <div className="mt-4 flex justify-center">
          <button
            onClick={() => setOffset((o) => o + 50)}
            className="rounded-[7px] border border-line-2 bg-surface px-3 py-1.5 text-[13px] hover:bg-panel"
          >
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
