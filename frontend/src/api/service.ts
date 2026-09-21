import { api } from "./client";

export interface TicketRow {
  id: string;
  number?: string;
  title: string;
  status: string;
  type?: string;
  impact?: string;
  urgency?: string;
  priority?: string;
  slaState?: string;
  slaDueAt?: string;
  slaRemainingMinutes?: number | null;
  approvalStatus?: string;
  assignedToName?: string;
  requesterName?: string;
  orgName?: string;
  relatedComputerName?: string;
  resolution?: string;
  createdAt?: string;
  updatedAt?: string;
  summary?: string;
  description?: string;
}

export interface TicketDetail extends TicketRow {
  notes?: Array<{ id?: string; content?: string; isPublic?: unknown; createdByName?: string; createdAt?: string }>;
}

/** 与后端 TICKET_TRANSITIONS 保持一致。 */
export const TICKET_TRANSITIONS: Record<string, string[]> = {
  new: ["assigned", "in_progress", "cancelled"],
  assigned: ["in_progress", "pending", "resolved", "cancelled"],
  in_progress: ["pending", "resolved", "cancelled"],
  pending: ["in_progress", "resolved", "cancelled"],
  resolved: ["closed", "in_progress"],
  closed: [],
  cancelled: [],
};

export const TICKET_TYPE_OPTIONS = [
  { value: "incident", label: "故障" },
  { value: "request", label: "服务请求" },
];

export const PRIORITY_OPTIONS = [
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
];

export interface ChangeRow {
  id: string;
  number?: string;
  title: string;
  status: string;
  type?: string;
  impact?: string;
  risk?: string;
  plannedStartAt?: string;
  plannedEndAt?: string;
  assignedToName?: string;
}

export interface ProblemRow {
  id: string;
  title: string;
  status: string;
  impact?: string;
  description?: string;
}

export interface KnowledgeRow {
  id: string;
  title: string;
  status: string;
  visibility?: string;
  ownerName?: string;
  publishedAt?: string;
  updatedAt?: string;
}

export interface SlaPolicyRow {
  id: string;
  name: string;
  priority?: string;
  responseMinutes?: number;
  resolutionMinutes?: number;
  isActive?: unknown;
}

export interface ApprovalRow {
  id: string;
  recordType?: string;
  recordId?: string;
  title?: string;
  status: string;
  requestedByName?: string;
  createdAt?: string;
  comment?: string;
}

export interface NotificationRow {
  id: string;
  type: string;
  title: string;
  content?: string;
  isRead: boolean | number;
  createdAt?: string;
}

export async function fetchTickets(filters: Record<string, string> = {}): Promise<TicketRow[]> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const payload = await api<{ tickets?: TicketRow[] }>(`/api/tickets?${params.toString()}`);
  return payload.tickets ?? [];
}

export async function fetchTicket(ticketId: string): Promise<TicketDetail> {
  const payload = await api<{ ticket: TicketDetail }>(`/api/tickets/${ticketId}`);
  return payload.ticket;
}

export async function createTicket(body: Record<string, unknown>): Promise<void> {
  await api("/api/tickets", { method: "POST", body });
}

export async function transitionTicket(
  ticketId: string,
  payload: { status: string; resolution?: string },
): Promise<void> {
  await api(`/api/tickets/${ticketId}/transitions`, { method: "POST", body: payload });
}

export async function addTicketNote(ticketId: string, content: string): Promise<void> {
  await api(`/api/tickets/${ticketId}/notes`, {
    method: "POST",
    body: { content, isPublic: true },
  });
}

export async function fetchChanges(): Promise<ChangeRow[]> {
  const payload = await api<{ changes?: ChangeRow[] }>("/api/changes");
  return payload.changes ?? [];
}

export async function createChange(body: Record<string, unknown>): Promise<void> {
  await api("/api/changes", { method: "POST", body });
}

export async function fetchProblems(): Promise<ProblemRow[]> {
  const payload = await api<{ problems?: ProblemRow[] }>("/api/problems");
  return payload.problems ?? [];
}

export async function createProblem(body: Record<string, unknown>): Promise<void> {
  await api("/api/problems", { method: "POST", body });
}

export async function fetchKnowledge(): Promise<KnowledgeRow[]> {
  const payload = await api<{ articles?: KnowledgeRow[] }>("/api/knowledge");
  return payload.articles ?? [];
}

export async function createKnowledge(body: Record<string, unknown>): Promise<void> {
  await api("/api/knowledge", { method: "POST", body });
}

export async function fetchSlaPolicies(): Promise<SlaPolicyRow[]> {
  const payload = await api<{ policies?: SlaPolicyRow[] }>("/api/sla/policies");
  return payload.policies ?? [];
}

export async function createSlaPolicy(body: Record<string, unknown>): Promise<void> {
  await api("/api/sla/policies", { method: "POST", body });
}

export async function fetchApprovals(): Promise<ApprovalRow[]> {
  const payload = await api<{ approvals?: ApprovalRow[] }>("/api/approvals");
  return payload.approvals ?? [];
}

export async function decideApproval(
  approvalId: string,
  decision: "approved" | "rejected",
  comment: string,
): Promise<void> {
  await api(`/api/approvals/${approvalId}/decision`, {
    method: "POST",
    body: { decision, comment },
  });
}

export async function fetchNotifications(): Promise<NotificationRow[]> {
  const payload = await api<{ notifications?: NotificationRow[] }>("/api/notifications");
  return payload.notifications ?? [];
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await api(`/api/notifications/${notificationId}/read`, { method: "POST", body: {} });
}
