import { api } from "./client";

export interface LeftDeviceRow {
  label?: string;
  detail?: string;
  quantity?: number;
  action?: string;
  actionLabel?: string;
  targetEmployeeName?: string;
  targetEmployeeNo?: string;
  handlingNote?: string;
}

export interface LeftEmployeeRow {
  id: string;
  sourceEmployeeId?: string;
  employeeNo: string;
  name: string;
  orgId: string;
  orgPath: string;
  department: string;
  position: string;
  email: string;
  mobile: string;
  leaveDate: string;
  leaveInfo: string;
  leaveRemark: string;
  archivedAt: string;
  devices: LeftDeviceRow[];
}

export interface OrgNode {
  id: string;
  code: string;
  name: string;
  parentId: string;
  sortOrder: number;
}

export interface NonAssetTypeRow {
  id: string;
  code: string;
  name: string;
  unit: string;
}

export interface DirectoryEmployeeRow {
  id: string;
  name: string;
  department: string;
  monitors?: Array<{ typeId?: string; quantity?: unknown }>;
  nonAssetItems?: Array<{ typeId?: string; quantity?: unknown }>;
}

export interface DirectoryData {
  leftEmployees: LeftEmployeeRow[];
  orgs: OrgNode[];
  nonAssetTypes: NonAssetTypeRow[];
  employees: DirectoryEmployeeRow[];
}

let cache: { at: number; data: DirectoryData } | null = null;

export async function loadDirectoryData(force = false): Promise<DirectoryData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  // 只要这四块：整包约 567 KB，裁剪后约 105 KB。
  const payload = await api<Partial<DirectoryData>>(
    "/api/state?include=leftEmployees,orgs,nonAssetTypes,employees",
  );
  const data: DirectoryData = {
    leftEmployees: Array.isArray(payload.leftEmployees) ? payload.leftEmployees : [],
    orgs: Array.isArray(payload.orgs) ? payload.orgs : [],
    nonAssetTypes: Array.isArray(payload.nonAssetTypes) ? payload.nonAssetTypes : [],
    employees: Array.isArray(payload.employees) ? payload.employees : [],
  };
  cache = { at: Date.now(), data };
  return data;
}

export function invalidateDirectoryCache(): void {
  cache = null;
}

export function orgPathName(orgId: string, orgs: OrgNode[]): string {
  const byId = new Map(orgs.map((item) => [item.id, item] as const));
  const names: string[] = [];
  let current = byId.get(orgId);
  let guard = 0;
  while (current && guard < 20) {
    names.unshift(current.name);
    current = current.parentId ? byId.get(current.parentId) : undefined;
    guard += 1;
  }
  return names.join(" / ");
}

export function offboardDeviceActionText(device: LeftDeviceRow): string {
  const actionLabel = device.actionLabel || "";
  if (!actionLabel) return "";
  const target = [device.targetEmployeeName, device.targetEmployeeNo ? `(${device.targetEmployeeNo})` : ""]
    .filter(Boolean)
    .join(" ");
  return [actionLabel, target ? `接收人：${target}` : "", device.handlingNote || ""]
    .filter(Boolean)
    .join(" · ");
}

export async function saveOrganization(
  payload: { code: string; name: string; parentId: string; sortOrder: number },
  orgId = "",
): Promise<void> {
  if (orgId) {
    await api(`/api/resources/organization/${orgId}`, { method: "PUT", body: payload });
    return;
  }
  await api("/api/resources/organization", { method: "POST", body: payload });
}

export async function saveInventoryType(
  payload: { code: string; name: string; unit: string },
  typeId = "",
): Promise<void> {
  if (typeId) {
    await api(`/api/resources/inventory-type/${typeId}`, { method: "PUT", body: payload });
    return;
  }
  await api("/api/resources/inventory-type", { method: "POST", body: payload });
}
