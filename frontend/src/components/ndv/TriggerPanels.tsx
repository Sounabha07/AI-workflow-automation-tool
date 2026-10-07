import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPipeline, previewSchedule } from "@/api/pipelines";
import { ApiError } from "@/api/client";
import { CopyField } from "@/components/CopyField";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useEditorStore } from "@/store/editor";

const FALLBACK_TIMEZONES = ["UTC", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Kolkata", "Asia/Tokyo", "Australia/Sydney"];

function allTimezones(): string[] {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    return FALLBACK_TIMEZONES;
  }
}

/** Timezone select for the schedule trigger, plus the next 5 fire times
 * computed by the backend (/schedule/preview), so cron semantics live in one place. */
export function SchedulePanel({
  cron,
  timezone,
  onTimezoneChange,
}: {
  cron: string;
  timezone: string;
  onTimezoneChange: (tz: string) => void;
}) {
  const zones = useMemo(() => allTimezones(), []);
  const debouncedCron = useDebouncedValue(cron.trim(), 400);
  const preview = useQuery({
    queryKey: ["schedulePreview", debouncedCron, timezone],
    queryFn: () => previewSchedule(debouncedCron, timezone),
    enabled: debouncedCron.length > 0,
    retry: false,
  });

  return (
    <>
      <div className="mb-4">
        <label className="mb-1.5 block text-xs font-medium text-ink-2" htmlFor="schedule-tz">
          Timezone
        </label>
        <select
          id="schedule-tz"
          value={timezone}
          onChange={(e) => onTimezoneChange(e.target.value)}
          className="min-h-[34px] w-full rounded-[7px] border border-line-2 bg-surface px-2.5 py-1.5 text-[13px] text-ink"
        >
          {!zones.includes(timezone) && <option value={timezone}>{timezone}</option>}
          {zones.map((z) => (
            <option key={z} value={z}>
              {z}
            </option>
          ))}
        </select>
      </div>
      <div className="mb-4 rounded-lg border border-line bg-panel p-3">
        <div className="mb-1.5 text-xs font-medium text-ink-2">Next 5 runs ({timezone})</div>
        {preview.isError ? (
          <p className="m-0 text-xs text-err">
            {preview.error instanceof ApiError ? preview.error.message : "Couldn't preview this schedule."}
          </p>
        ) : preview.data ? (
          <ol className="m-0 list-decimal pl-5 font-mono text-xs text-ink-2">
            {preview.data.times.map((t) => (
              <li key={t}>{new Date(t).toLocaleString(undefined, { timeZone: timezone, dateStyle: "medium", timeStyle: "short" })}</li>
            ))}
          </ol>
        ) : (
          <p className="m-0 text-xs text-ink-3">{debouncedCron ? "Loading…" : "Enter a cron expression."}</p>
        )}
        <p className="mb-0 mt-2 text-xs text-ink-3">Runs only while the workflow is active. Missed runs are not made up.</p>
      </div>
    </>
  );
}

/** The webhook trigger's URL. The backend mints it on the first save. */
export function WebhookPanel({ blockId }: { blockId: string }) {
  const pipelineId = useEditorStore((s) => s.pipelineId);
  const dirty = useEditorStore((s) => s.dirty);
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", pipelineId],
    queryFn: () => getPipeline(pipelineId!),
    enabled: !!pipelineId,
  });
  const url = pipeline?.triggers?.find((t) => t.block_id === blockId && t.type === "webhook")?.webhook_url;

  return (
    <div className="mb-4 rounded-lg border border-line bg-panel p-3">
      <div className="mb-1.5 text-xs font-medium text-ink-2">Webhook URL</div>
      {url ? (
        <CopyField value={url} label="webhook URL" />
      ) : (
        <p className="m-0 text-xs text-ink-3">The URL appears after you save the workflow{dirty ? "" : " with this block"}.</p>
      )}
      <p className="mb-0 mt-2 text-xs text-ink-3">
        POST JSON to it while the workflow is active. Downstream blocks read it as{" "}
        <code className="font-mono">{`{{ ${blockId}.body }}`}</code>, plus <code className="font-mono">query</code> and{" "}
        <code className="font-mono">headers</code>. Send <code className="font-mono">Idempotency-Key</code> to make retries safe.
      </p>
    </div>
  );
}

/** The wait block's fixed resume URL (minted on the first save, like a
 * webhook URL), plus the per-run link expression for sending it onward. */
export function WaitPanel({ blockId }: { blockId: string }) {
  const pipelineId = useEditorStore((s) => s.pipelineId);
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", pipelineId],
    queryFn: () => getPipeline(pipelineId!),
    enabled: !!pipelineId,
  });
  const url = pipeline?.resume_links?.find((l) => l.block_id === blockId)?.url;

  return (
    <>
      <div className="mb-4 rounded-lg border border-line bg-panel p-3 text-xs text-ink-2">
        <div className="mb-1.5 font-medium">Resume URL</div>
        {url ? (
          <CopyField value={url} label="resume URL" />
        ) : (
          <p className="m-0 text-ink-3">The URL appears after you save the workflow with this block.</p>
        )}
        <p className="mb-0 mt-2 text-ink-3">
          POST a JSON object to it to continue a run that is waiting here. If several runs are waiting, each call
          continues the one that has waited longest. Later blocks read what you sent as{" "}
          <code className="font-mono">{`{{ ${blockId}.data }}`}</code>. If nobody resumes a run before the timeout, that
          run fails.
        </p>
      </div>
      <div className="mb-4 rounded-lg border border-line bg-panel p-3 text-xs text-ink-2">
        <div className="mb-1.5 font-medium">Link for one specific run</div>
        <p className="m-0 mb-2 text-ink-3">
          Each run also gets its own link that continues only that run. Any block can include it, for example to send
          it in a message before this block starts waiting. It doesn't connect the blocks.
        </p>
        <CopyField value={`{{ resume.${blockId}.url }}`} label="per-run link expression" />
      </div>
    </>
  );
}
