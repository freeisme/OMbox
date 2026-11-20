import { api } from "./client";

export interface ApiCredentialRow {
  id: string;
  name: string;
  prefix: string;
  lastUsedAt?: string;
  expiresAt?: string;
  revoked?: number | boolean;
  createdAt?: string;
}

export interface IssuedCredential {
  token: string;
  credential: ApiCredentialRow;
}

export async function listMyCredentials(): Promise<ApiCredentialRow[]> {
  const payload = await api<{ credentials?: ApiCredentialRow[] }>("/api/me/credentials");
  return (payload.credentials ?? []).map((row) => ({ ...row, id: String(row.id) }));
}

export function issueMyCredential(name: string, expiresDays = 0): Promise<IssuedCredential> {
  return api<IssuedCredential>("/api/me/credentials", {
    method: "POST",
    body: { name, expiresDays },
  });
}

export async function revokeMyCredential(id: string): Promise<void> {
  await api("/api/me/credentials/" + encodeURIComponent(id), { method: "DELETE" });
}

export interface MyTicketRow {
  id: string;
  number: string;
  title: string;
  status: string;
  type?: string;
  createdAt?: string;
}

export async function listMyTickets(): Promise<MyTicketRow[]> {
  const payload = await api<{ tickets?: MyTicketRow[] }>("/api/tickets?requester=me");
  return payload.tickets ?? [];
}
