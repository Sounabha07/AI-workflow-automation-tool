import { useState } from "react";
import { Hourglass, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { resumeBlock } from "@/api/runs";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CopyField } from "@/components/CopyField";
import { RelativeTime } from "@/components/RelativeTime";

/** Run view of a waiting Wait for Input block: its resume URL, deadline,
 * and a small JSON editor to resume it by hand. */
export function ResumePanel({
  blockId,
  resumeUrl,
  waitDeadline,
}: {
  blockId: string;
  resumeUrl: string | null | undefined;
  waitDeadline: string | null | undefined;
}) {
  const [text, setText] = useState("{\n  \n}");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const submit = async () => {
    let data: unknown;
    try {
      data = text.trim() ? JSON.parse(text) : {};
    } catch (e) {
      setError(`Not valid JSON: ${(e as Error).message}`);
      return;
    }
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      setError("Send a JSON object, like {\"approved\": true}.");
      return;
    }
    setError(null);
    setSending(true);
    try {
      await resumeBlock(resumeUrl!, data as Record<string, unknown>);
      toast.success(`Resumed ${blockId}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't resume this block");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="rounded-lg border border-[#EED9A6] bg-run-bg p-3">
      <div className="mb-2 flex items-center gap-2 text-[13px] text-[#8C6108]">
        <Hourglass className="h-4 w-4" aria-hidden="true" />
        <b>Waiting for input</b>
        {waitDeadline && (
          <span className="ml-auto text-xs text-ink-3">
            times out <RelativeTime iso={waitDeadline} />
          </span>
        )}
      </div>
      {resumeUrl ? (
        <>
          <CopyField value={resumeUrl} label="resume URL" />
          <label className="mb-1 mt-3 block text-xs font-medium text-ink-2" htmlFor="resume-json">
            Resume with this JSON
          </label>
          <Textarea
            id="resume-json"
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="bg-surface font-mono text-xs"
          />
          {error && <p className="mb-0 mt-1 text-xs text-err">{error}</p>}
          <Button variant="primary" className="mt-2" onClick={submit} disabled={sending}>
            {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Resume manually
          </Button>
        </>
      ) : (
        <p className="m-0 text-xs text-ink-3">Loading the resume link…</p>
      )}
    </div>
  );
}
