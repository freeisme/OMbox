import { api } from "./client";
import { withCompanyQuery } from "../companyScope";
import type { ImportSummary } from "./datacenter";

export interface LeftDeviceRow {
  category?: string;
  label?: string;
  detail?: string;
  quantity?: number;
  action?: string;
  actionLabel?: string;
  targetEmployeeName?: string;
  targetEmployeeNo?: string;
  handlingNote?: string;
  /** 异常项结清：只有 action=exception 的条目才有 exceptionIndex。 */
  exceptionIndex?: number;
  resolved?: boolean;
  resolution?: string;
  resolutionLabel?: string;
  resolutionNote?: string;
  resolvedBy?: string;
  resolvedAt?: string;
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
  deviceCount?: number;
  /** 按「异常待处理」归档的项目总数（含已结清）。 */
  exceptionCount?: number;
  /** 其中尚未结清的数量，列表红标用它。 */
  exceptionOpenCount?: number;
  exceptionLabels?: string[];
  exceptionOpenLabels?: string[];
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

/** 结清一条离职异常项：resolution = recovered / scrapped / compensated / other。 */
export function resolveLeftException(
  archiveId: string,
  exceptionIndex: number,
  payload: { resolution: string; note?: string },
): Promise<{ ok: boolean; resolved: boolean }> {
  return api(
    withCompanyQuery("/api/left-employees/" + archiveId + "/exceptions/" + exceptionIndex + "/resolve"),
    { method: "POST", body: payload },
  );
}

/** 撤销结清（误点恢复），保留操作记录。 */
export function revokeLeftException(
  archiveId: string,
  exceptionIndex: number,
): Promise<{ ok: boolean; resolved: boolean }> {
  return api(
    withCompanyQuery("/api/left-employees/" + archiveId + "/exceptions/" + exceptionIndex + "/revoke"),
    { method: "POST", body: {} },
  );
}

let cache: { at: number; data: DirectoryData } | null = null;

export async function loadDirectoryData(force = false): Promise<DirectoryData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  // 只要这四块：整包约 567 KB，裁剪后约 105 KB。
  const payload = await api<Partial<DirectoryData>>(
    withCompanyQuery("/api/state?include=leftEmployees,orgs,nonAssetTypes,employees"),
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

/** 修改离职人员备注：只允许改 leave_remark，其余归档信息不动。 */
export async function updateLeftEmployeeRemark(archiveId: string, remark: string): Promise<void> {
  await api(`/api/left-employees/${encodeURIComponent(archiveId)}`, {
    method: "PUT",
    body: { remark },
  });
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

/** 批量导入组织架构（xlsx / csv，表头：组织编码 / 组织名称 / 上级组织 / 排序 / 启用）。 */
export function importOrganizations(payload: {
  fileName: string;
  contentBase64: string;
  dryRun?: boolean;
  mode?: "skip" | "update";
}): Promise<ImportSummary> {
  return api<ImportSummary>("/api/organizations/import", { method: "POST", body: payload });
}
