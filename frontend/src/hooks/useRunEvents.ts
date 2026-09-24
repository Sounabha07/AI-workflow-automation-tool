import { useEffect, useRef } from "react";
import { WS_URL } from "@/api/client";
import type { RunEvent } from "@/api/types";

const BACKOFF_STEPS_MS = [1000, 2000, 5000, 10000];

/** Subscribes to /ws/runs/{runId} (or /ws/runs for "all"), reconnecting with
 * backoff while mounted. Per B8: open the socket first (onOpen fires), THEN
 * fetch current state over REST, then apply live events — that ordering
 * avoids missing an event that lands between the fetch and the subscribe. */
export function useRunEvents(
  runId: string | "all" | null,
  onEvent: (event: RunEvent) => void,
  onOpen?: () => void
): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  useEffect(() => {
    if (!runId) return;

    let socket: WebSocket | null = null;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const path = runId === "all" ? "/ws/runs" : `/ws/runs/${runId}`;

    function connect() {
      if (cancelled) return;
      socket = new WebSocket(WS_URL + path);

      socket.onopen = () => {
        attempt = 0;
        onOpenRef.current?.();
      };

      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as RunEvent;
          onEventRef.current(parsed);
        } catch {
          // Ignore malformed frames rather than crash the subscription.
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        const delay = BACKOFF_STEPS_MS[Math.min(attempt, BACKOFF_STEPS_MS.length - 1)];
        attempt++;
        reconnectTimer = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [runId]);
}
