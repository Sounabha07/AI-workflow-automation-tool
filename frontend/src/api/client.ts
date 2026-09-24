export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

/** Thrown on any non-2xx response. `detail` and `problems` come straight off
 * the backend's JSON body (see app/main.py's exception handlers). */
export class ApiError extends Error {
  status: number;
  problems?: string[];

  constructor(status: number, detail: string, problems?: string[]) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.problems = problems;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(API_URL + path);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params } = options;

  const res = await fetch(buildUrl(path, params), {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText || `Request failed with status ${res.status}`;
    let problems: string[] | undefined;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      if (Array.isArray(data.problems)) problems = data.problems;
    } catch {
      // Non-JSON error body; fall back to the status text above.
    }
    throw new ApiError(res.status, detail, problems);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
