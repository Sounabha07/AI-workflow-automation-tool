import { apiFetch } from "./client";
import type { BlockSchemaResponse } from "./types";

export function listBlockSchemas(): Promise<BlockSchemaResponse[]> {
  return apiFetch("/blocks");
}
