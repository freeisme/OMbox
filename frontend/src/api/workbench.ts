import { api } from "./client";

export interface WorkbenchComputer {
  id: string;
  deviceName: string;
  orgId: string;
  orgName: string;
  deviceType: string;
  brand: string;
  model: string;
  location: string;
  status: string;
  userId: string;
  userName: string;
  registeredDate: string;
}

export interface WorkbenchMovement {
  id: string;
  typeName: string;
  brandName: string;
  modelName: string;
  quantity: number;
  sourceLabel: string;
  occurredAt: string;
}

export interface WorkbenchNotification {
  id: string;
  type: string;
  title: string;
  content: string;
  isRead: boolean;
  createdAt: string;
}

export interface WorkbenchQualityIssue {
  id: string;
  title: string;
  severityLabel: string;
  ruleLabel: string;
  entityTypeLabel: string;
  firstDetectedAt: string;
}

export interface WorkbenchAssets {
  computers: number;
  inUse: number;
  idle: number;
  attention: number;
  employees: number;
  nonAssetItems: number;
  rootOrgs: number;
}

export interface WorkbenchService {
  ticketStatus?: Record<string, number>;
  openTickets?: number;
  slaBreached?: number;
  pendingApprovals?: number;
  changes?: number;
  problems?: number;
}

export interface WorkbenchSummary {
  generatedAt: string;
  stateRevision: number;
  assets: WorkbenchAssets;
  recentComputers: WorkbenchComputer[];
  recentInbound: WorkbenchMovement[];
  myAssets: WorkbenchComputer[];
  service?: WorkbenchService;
  inspection?: { running: number; submitted: number };
  quality?: { open: number; top: WorkbenchQualityIssue[] };
  notifications?: { unread: number; recent: WorkbenchNotification[] };
}

const EMPTY_SUMMARY: WorkbenchSummary = {
  generatedAt: "",
  stateRevision: 0,
  assets: {
    computers: 0,
    inUse: 0,
    idle: 0,
    attention: 0,
    employees: 0,
    nonAssetItems: 0,
    rootOrgs: 0,
  },
  recentComputers: [],
  recentInbound: [],
  myAssets: [],
};

/** 工作台首屏数据：一次请求拿到计数与少量最近记录（服务端已按权限过滤）。 */
export async function fetchWorkbench(force = false): Promise<WorkbenchSummary> {
  const payload = await api<Partial<WorkbenchSummary>>(
    `/api/workbench/summary${force ? "?refresh=1" : ""}`,
  );
  return {
    ...EMPTY_SUMMARY,
    ...payload,
    assets: { ...EMPTY_SUMMARY.assets, ...(payload.assets ?? {}) },
    recentComputers: payload.recentComputers ?? [],
    recentInbound: payload.recentInbound ?? [],
    myAssets: payload.myAssets ?? [],
  };
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await api(`/api/notifications/${notificationId}/read`, { method: "POST", body: {} });
}
