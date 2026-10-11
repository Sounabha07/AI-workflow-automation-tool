import { useQuery } from "@tanstack/react-query";
import { listCredentials, listCredentialTypes } from "@/api/credentials";

export function useCredentials() {
  return useQuery({ queryKey: ["credentials"], queryFn: listCredentials });
}

/** The types are fixed by the server's providers, so cache for the session. */
export function useCredentialTypes() {
  return useQuery({
    queryKey: ["credentialTypes"],
    queryFn: listCredentialTypes,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
