import { api } from "./client";

export interface UsageItem {
  id?: string;
  typeId?: string;
  typeName?: string;
  brand?: string;
  model?: string;
  quantity?: number | string;
  displayName?: string;
  stockAdjusted?: unknown;
}

export interface EmployeeDetailRow {
  id: string;
  employeeNo: string;
  name: string;
  orgId: string;
  department: string;
  position: string;
  email: string;
  mobile: string;
  status: string;
  monitors?: UsageItem[];
  nonAssetItems?: UsageItem[];
}

export interface OrgRow {
  id: string;
  code: string;
  name: string;
  parentId: string;
  sortOrder: number;
}

export interface WarehouseBrief {
  id: string;
  name: string;
  code: string;
}

export interface EmployeesData {
  employees: EmployeeDetailRow[];
  orgs: OrgRow[];
  warehouses: WarehouseBrief[];
}

let cache: { at: number; data: EmployeesData } | null = null;

export async function loadEmployeesData(force = false): Promise<EmployeesData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  // 人员清单需要全量（组织树人数、离职转交候选人）；终端改用
  // /api/list/computers?fields=names 的精简行，所以这里不再请求 computers。
  const payload = await api<Partial<EmployeesData>>(
    "/api/state?include=employees,orgs,warehouses",
  );
  const data: EmployeesData = {
    employees: Array.isArray(payload.employees) ? payload.employees : [],
    orgs: Array.isArray(payload.orgs) ? payload.orgs : [],
    warehouses: Array.isArray(payload.warehouses) ? payload.warehouses : [],
  };
  cache = { at: Date.now(), data };
  return data;
}

export function invalidateEmployeesCache(): void {
  cache = null;
}

export interface EmployeeFormPayload {
  employeeNo: string;
  name: string;
  orgId: string;
  department: string;
  position: string;
  email: string;
  mobile: string;
  status: string;
}

export function emptyEmployeeForm(): EmployeeFormPayload {
  return {
    employeeNo: "",
    name: "",
    orgId: "",
    department: "",
    position: "",
    email: "",
    mobile: "",
    status: "active",
  };
}

export function formFromEmployee(row: EmployeeDetailRow): EmployeeFormPayload {
  return {
    employeeNo: row.employeeNo ?? "",
    name: row.name ?? "",
    orgId: row.orgId ?? "",
    department: row.department ?? "",
    position: row.position ?? "",
    email: row.email ?? "",
    mobile: row.mobile ?? "",
    status: row.status || "active",
  };
}

export async function saveEmployee(
  payload: EmployeeFormPayload,
  employeeId = "",
): Promise<void> {
  if (employeeId) {
    await api(`/api/resources/employee/${employeeId}`, { method: "PUT", body: payload });
    return;
  }
  await api("/api/resources/employee", { method: "POST", body: payload });
}

export interface OffboardItem {
  key: string;
  itemType: string;
  id: string;
  label: string;
  detail: string;
  quantity: number;
  status?: string;
  action?: string;
  actionLabel?: string;
  targetEmployeeId?: string;
  targetEmployeeName?: string;
  recoveryWarehouseId?: string;
  recoveryWarehouseName?: string;
}

export interface OffboardPreview {
  employee: { id: string; name: string; employeeNo: string; orgId: string; department?: string };
  items: OffboardItem[];
}

export async function fetchOffboardingPreview(employeeId: string): Promise<OffboardPreview> {
  return api<OffboardPreview>(`/api/employees/${employeeId}/offboarding-preview`);
}

export interface OffboardSubmission {
  leaveDate: string;
  leaveReason: string;
  leaveRemark: string;
  items: Array<{
    itemType: string;
    itemId: string;
    action: string;
    note: string;
    targetEmployeeId: string;
    recoveryWarehouseId: string;
  }>;
}

export async function offboardEmployee(
  employeeId: string,
  payload: OffboardSubmission,
): Promise<void> {
  await api(`/api/employees/${employeeId}/offboard`, { method: "POST", body: payload });
}

export const OFFBOARD_ACTIONS = [
  { value: "recover", label: "回收" },
  { value: "transfer", label: "转交他人" },
  { value: "exception", label: "异常待处理" },
];

export const EMPLOYEE_STATUS_OPTIONS = ["active", "inactive", "shared"];

/** 在用领用记录（用于归还：优先按 allocation 归还，没有 allocation 时回落到 usage 记录）。 */
export interface ActiveAllocation {
  id: string;
  allocationType: string;
  employeeId: string;
  usageRecordId: string;
  modelId: string;
  modelName?: string;
  warehouseId: string;
}

export async function fetchActiveAllocations(): Promise<ActiveAllocation[]> {
  const payload = await api<{ allocations?: ActiveAllocation[] }>(
    "/api/inventory/allocations?status=active",
  );
  return payload.allocations ?? [];
}

/** 把办公终端分配给人员（只能给在职或公用人员，后端会再校验）。 */
export async function assignComputerToEmployee(
  computerId: string,
  employeeId: string,
  notes = "",
): Promise<void> {
  await api(`/api/computers/${computerId}/assignments`, {
    method: "POST",
    body: { employeeId, notes },
  });
}

/** 解除人员的办公终端分配，设备回到闲置。 */
export async function releaseComputerFromEmployee(computerId: string, notes = ""): Promise<void> {
  await api(`/api/computers/${computerId}/assignments/return`, {
    method: "POST",
    body: { nextStatus: "idle", notes },
  });
}

/**
 * 给人员领用显示屏或非资产物资。
 *
 * 两种走法：
 * - 库存型号：传 `modelId` + `warehouseId`，按仓库库存扣减；
 * - 自定义（无库存记录，用来补台账里没有的物资）：传 `typeId` + `brand` + `model`，
 *   并把 `stockAdjusted` 设为 false——不扣库存，回收时再入库并自动补品牌型号。
 */
export async function allocateInventoryToEmployee(payload: {
  allocationType: "monitor" | "non_asset";
  employeeId: string;
  modelId?: string;
  typeId?: string;
  brand?: string;
  model?: string;
  displayName?: string;
  stockAdjusted?: boolean;
  quantity: number;
  warehouseId?: string;
  notes?: string;
}): Promise<void> {
  await api("/api/inventory/allocations", { method: "POST", body: payload });
}

/** 归还人员名下的显示屏 / 非资产物资，回收到指定仓库。 */
export async function returnEmployeeUsage(
  employeeId: string,
  allocationType: string,
  usageRecordId: string,
  warehouseId: string,
  notes = "",
): Promise<void> {
  const allocations = await fetchActiveAllocations();
  const matches = allocations.filter(
    (item) =>
      String(item.employeeId) === String(employeeId) &&
      item.allocationType === allocationType &&
      String(item.usageRecordId) === String(usageRecordId),
  );
  if (matches.length) {
    for (const allocation of matches) {
      await api(`/api/inventory/allocations/${allocation.id}/return`, {
        method: "POST",
        body: { warehouseId, notes },
      });
    }
    return;
  }
  await api(
    `/api/inventory/usage/${encodeURIComponent(allocationType)}/${encodeURIComponent(usageRecordId)}/return`,
    { method: "POST", body: { warehouseId, notes } },
  );
}

export function employeeUsageLabel(item: UsageItem): string {
  const name = item.typeName || item.displayName || "物资";
  const extras = [item.brand, item.model].filter(Boolean).join(" ");
  const quantity = Number(item.quantity ?? 0);
  return `${name}${extras ? ` ${extras}` : ""}${quantity > 1 ? ` x${quantity}` : ""}`;
}

export function employeesToCsv(
  rows: EmployeeDetailRow[],
  orgNameOf: (orgId: string) => string,
  computerNamesOf: (employeeId: string) => string[],
): string {
  const header = [
    "工号",
    "姓名",
    "组织",
    "部门",
    "岗位",
    "邮箱",
    "手机",
    "状态",
    "办公终端",
    "显示屏 / 非资产物资",
  ];
  const body = rows.map((row) => [
    row.employeeNo,
    row.name,
    orgNameOf(row.orgId),
    row.department,
    row.position,
    row.email,
    row.mobile,
    row.status,
    computerNamesOf(row.id).join("；"),
    [...(row.monitors ?? []), ...(row.nonAssetItems ?? [])].map(employeeUsageLabel).join("；"),
  ]);
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [header, ...body].map((line) => line.map(escape).join(",")).join("\r\n");
}
