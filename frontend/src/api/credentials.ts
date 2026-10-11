import { apiFetch } from "./client";
import type { Credential, CredentialType } from "./types";

export function listCredentials(): Promise<Credential[]> {
  return apiFetch("/credentials");
}

export function listCredentialTypes(): Promise<CredentialType[]> {
  return apiFetch("/credentials/types");
}

export function createCredential(body: {
  name: string;
  type: string;
  data: Record<string, string>;
}): Promise<Credential> {
  return apiFetch("/credentials", { method: "POST", body });
}

export function updateCredential(
  id: string,
  body: { name?: string; data?: Record<string, string> }
): Promise<Credential> {
  return apiFetch(`/credentials/${id}`, { method: "PATCH", body });
}

export function deleteCredential(id: string): Promise<void> {
  return apiFetch(`/credentials/${id}`, { method: "DELETE" });
}
