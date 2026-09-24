import { useQuery } from "@tanstack/react-query";
import { listBlockSchemas } from "@/api/blocks";
import type { BlockTypeSchema } from "@/api/types";

/** GET /blocks, cached for the session (B7). */
export function useBlockSchemas() {
  return useQuery({
    queryKey: ["blockSchemas"],
    queryFn: listBlockSchemas,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

export function schemaFor(schemas: { type: string; schema: BlockTypeSchema }[] | undefined, type: string) {
  return schemas?.find((s) => s.type === type)?.schema;
}
