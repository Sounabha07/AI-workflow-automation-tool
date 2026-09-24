import type { BlockError } from "@/api/types";

/** Same copy used in History's expanded detail and the block editor's Output pane (B5/B7). */
export function retryHint(error: Pick<BlockError, "retryable" | "attempts">): string {
  return error.retryable
    ? `Retried ${error.attempts} times with backoff before giving up. The service may be down, try the run again later.`
    : "Not retried, because this kind of error won't succeed on retry. Fix the block's configuration, then run the workflow again.";
}

export function firstSentence(message: string): string {
  const idx = message.indexOf(".");
  return idx === -1 ? message : message.slice(0, idx + 1);
}
