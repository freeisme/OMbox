import { api } from "./client";
import type { ComputerRow, EmployeeRow, OrgRow } from "./state";

export interface WarehouseRow {
  id: string;
  code: string;
  name: string;
  orgId: string;
  isActive: boolean | number;
}

export interface InventoryModelRow {
  id: string;
  typeId: string;
  brandId: string;
  name: string;
  quantity: number | string;
}

export interface ScrapReason {
  code: string;
  name: string;
  appliesTo: string;
}

export interface ComputersData {
  orgs: OrgRow[];
  employees: EmployeeRow[];
  warehouses: WarehouseRow[];
  inventoryModels: InventoryModelRow[];
}

interface FullStatePayload {
  stateRevision?: number;
  orgs?: OrgRow[];
  employees?: EmployeeRow[];
  warehouses?: WarehouseRow[];
  inventoryModels?: InventoryModelRow[];
}

let cache: { at: number; data: ComputersData } | null = null;

/**
 * 办公终端页需要的参考数据（组织 / 人员 / 仓库 / 库存型号）。
 * 列表本身走服务端分页接口 /api/list/computers，不再整包拉 /api/state。
 */
export async function loadComputersData(force = false): Promise<ComputersData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  const payload = await api<FullStatePayload>(
    "/api/state?include=orgs,employees,warehouses,inventoryModels",
  );
  const data: ComputersData = {
    orgs: Array.isArray(payload.orgs) ? payload.orgs : [],
    employees: Array.isArray(payload.employees) ? payload.employees : [],
    warehouses: Array.isArray(payload.warehouses) ? payload.warehouses : [],
    inventoryModels: Array.isArray(payload.inventoryModels) ? payload.inventoryModels : [],
  };
  cache = { at: Date.now(), data };
  return data;
}

export function invalidateComputersCache(): void {
  cache = null;
}

export interface ComputerFormPayload {
  deviceName: string;
  orgId: string;
  deviceType: string;
  status: string;
  brand: string;
  model: string;
  cpu: string;
  memory: string;
  storage: string;
  gpu: string;
  fixedAssetCode: string;
  snSt: string;
  wifiMac: string;
  ethernetMac: string;
  location: string;
  department: string;
  position: string;
  purchaseDate: string;
  registeredDate: string;
  remarks: string;
  registrationMode: "custom" | "warehouse";
  inventoryModelId?: string;
  warehouseId?: string;
}

export function emptyComputerForm(): ComputerFormPayload {
  return {
    deviceName: "",
    orgId: "",
    deviceType: "desktop",
    status: "idle",
    brand: "",
    model: "",
    cpu: "",
    memory: "",
    storage: "",
    gpu: "",
    fixedAssetCode: "",
    snSt: "",
    wifiMac: "",
    ethernetMac: "",
    location: "",
    department: "",
    position: "",
    purchaseDate: "",
    registeredDate: new Date().toISOString().slice(0, 10),
    remarks: "",
    registrationMode: "custom",
    inventoryModelId: "",
    warehouseId: "",
  };
}

export function formFromComputer(row: ComputerRow): ComputerFormPayload {
  return {
    ...emptyComputerForm(),
    deviceName: row.deviceName ?? "",
    orgId: row.orgId ?? "",
    deviceType: row.deviceType || "desktop",
    status: row.status || "idle",
    brand: row.brand ?? "",
    model: row.model ?? "",
    cpu: row.cpu ?? "",
    memory: row.memory ?? "",
    storage: row.storage ?? "",
    gpu: row.gpu ?? "",
    fixedAssetCode: row.fixedAssetCode ?? "",
    snSt: row.snSt ?? "",
    wifiMac: row.wifiMac ?? "",
    ethernetMac: row.ethernetMac ?? "",
    location: row.location ?? "",
    department: row.department ?? "",
    position: row.position ?? "",
    purchaseDate: row.purchaseDate ?? "",
    registeredDate: row.registeredDate ?? "",
    remarks: row.remarks ?? "",
    registrationMode: "custom",
  };
}

export async function saveComputer(
  payload: ComputerFormPayload,
  computerId = "",
): Promise<void> {
  const body: Record<string, unknown> = { ...payload };
  // 编辑时不重发登记方式，避免历史数据被改动；从库存登记仅在新增时可用。
  if (computerId) {
    delete body.registrationMode;
    delete body.inventoryModelId;
    delete body.warehouseId;
    await api(`/api/resources/computer/${computerId}`, { method: "PUT", body });
    return;
  }
  await api("/api/resources/computer", { method: "POST", body });
}

export async function scrapComputer(
  computerId: string,
  payload: { reasonCode: string; notes: string },
): Promise<void> {
  await api(`/api/computers/${computerId}/scrap`, { method: "POST", body: payload });
}

export async function fetchScrapReasons(): Promise<ScrapReason[]> {
  const payload = await api<{ reasons?: ScrapReason[]; scrapReasons?: ScrapReason[] }>(
    "/api/scrap-reasons",
  );
  const reasons = payload.reasons ?? payload.scrapReasons ?? [];
  return reasons.filter((item) => item.appliesTo !== "inventory");
}

export const COMPUTER_STATUS_OPTIONS = ["in_use", "idle", "repair", "retired", "lost"];

export function computersToCsv(
  rows: ComputerRow[],
  orgNameOf: (orgId: string) => string,
  userNameOf: (userId: string) => string,
): string {
  const header = [
    "设备名",
    "所属组织",
    "设备类型",
    "品牌",
    "型号",
    "CPU",
    "内存",
    "存储",
    "显卡",
    "固资编码",
    "SN/ST",
    "Wifi MAC",
    "网口 MAC",
    "位置",
    "部门",
    "岗位",
    "使用用户",
    "状态",
    "购置日期",
    "注册日期",
    "备注",
  ];
  const body = rows.map((row) => [
    row.deviceName,
    orgNameOf(row.orgId),
    row.deviceType,
    row.brand,
    row.model,
    row.cpu,
    row.memory,
    row.storage,
    row.gpu,
    row.fixedAssetCode,
    row.snSt,
    row.wifiMac,
    row.ethernetMac,
    row.location,
    row.department,
    row.position,
    userNameOf(row.userId),
    row.status,
    row.purchaseDate,
    row.registeredDate,
    row.remarks,
  ]);
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [header, ...body].map((line) => line.map(escape).join(",")).join("\r\n");
}
