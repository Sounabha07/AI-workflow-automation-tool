/** "2 min ago" (or "in 2 min" for a future time) style relative time, for
 * B9's relative-time + tooltip requirement. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const future = diffMs < 0;
  const diffSec = Math.round(Math.abs(diffMs) / 1000);
  const fmt = (n: number, unit: string) => (future ? `in ${n} ${unit}` : `${n} ${unit} ago`);

  if (diffSec < 5) return future ? "in a moment" : "just now";
  if (diffSec < 60) return fmt(diffSec, "s");
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return fmt(diffMin, "min");
  const diffHour = Math.round(diffMin / 60);
  if (diffHour < 24) return fmt(diffHour, "h");
  const diffDay = Math.round(diffHour / 24);
  if (diffDay < 30) return fmt(diffDay, "d");
  const diffMonth = Math.round(diffDay / 30);
  if (diffMonth < 12) return fmt(diffMonth, "mo");
  return fmt(Math.round(diffMonth / 12), "y");
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
