import { api } from "./client";
import type { ComputerRow, EmployeeRow, OrgRow } from "./state";
import type { ImportSummary } from "./datacenter";

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
  /** 「从库存登记」时用来预填设备信息的字段（后端返回，可能为空）。 */
  inboundDate?: string;
  cpu?: string;
  memory?: string;
  storage?: string;
  gpu?: string;
}

/** IT 物资品牌：型号行里只有 brandId，预填「品牌」时要靠它换成名字。 */
export interface InventoryBrandRow {
  id: string;
  typeId: string;
  name: string;
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
  inventoryTypes: InventoryTypeRow[];
  inventoryBrands: InventoryBrandRow[];
  inventoryModels: InventoryModelRow[];
  inventoryStocks: WarehouseStockRow[];
}

interface FullStatePayload {
  stateRevision?: number;
  orgs?: OrgRow[];
  employees?: EmployeeRow[];
  warehouses?: WarehouseRow[];
  nonAssetTypes?: InventoryTypeRow[];
  inventoryBrands?: InventoryBrandRow[];
  inventoryModels?: InventoryModelRow[];
  warehouseStocks?: WarehouseStockRow[];
}

/** 某个仓库里某个型号的库存数量（「从库存登记」按这个扣减）。 */
export interface WarehouseStockRow {
  modelId: string;
  warehouseId: string;
  quantity: number | string;
}

/** IT 物资类型（判断型号是不是"电脑"类型用得到）。 */
export interface InventoryTypeRow {
  id: string;
  code: string;
  name: string;
}

/** 与后端 `_save_computer` 的判定保持一致：只有电脑类型的型号能用于「从库存登记」。 */
export const COMPUTER_TYPE_CODES = ["computer", "pc"];
export const COMPUTER_TYPE_NAMES = ["电脑", "办公终端", "办公设备终端", "computer", "pc"];

export function isComputerInventoryType(type?: InventoryTypeRow): boolean {
  const code = String(type?.code ?? "").trim().toLowerCase();
  const name = String(type?.name ?? "").trim().toLowerCase();
  return COMPUTER_TYPE_CODES.includes(code) || COMPUTER_TYPE_NAMES.includes(name);
}

let cache: { at: number; data: ComputersData } | null = null;

/**
 * 办公终端页需要的参考数据（组织 / 人员 / 仓库 / 库存型号）。
 * 列表本身走服务端分页接口 /api/list/computers，不再整包拉 /api/state。
 */
export async function loadComputersData(force = false): Promise<ComputersData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  const payload = await api<FullStatePayload>(
    "/api/state?include=orgs,employees,warehouses,nonAssetTypes,inventoryBrands,inventoryModels,warehouseStocks",
  );
  const data: ComputersData = {
    orgs: Array.isArray(payload.orgs) ? payload.orgs : [],
    employees: Array.isArray(payload.employees) ? payload.employees : [],
    warehouses: Array.isArray(payload.warehouses) ? payload.warehouses : [],
    inventoryTypes: Array.isArray(payload.nonAssetTypes) ? payload.nonAssetTypes : [],
    inventoryBrands: Array.isArray(payload.inventoryBrands) ? payload.inventoryBrands : [],
    inventoryModels: Array.isArray(payload.inventoryModels) ? payload.inventoryModels : [],
    inventoryStocks: Array.isArray(payload.warehouseStocks) ? payload.warehouseStocks : [],
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

/** 批量导入办公终端：dryRun=true 只预览不写库；mode=skip 跳过已有设备名，mode=update 覆盖。 */
export function importComputers(payload: {
  fileName: string;
  contentBase64: string;
  dryRun?: boolean;
  mode?: "skip" | "update";
}): Promise<ImportSummary> {
  return api<ImportSummary>("/api/computers/import", { method: "POST", body: payload });
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

/** 办公终端的一条流转事件：分配 / 归还 / 状态变更（服务端由历史数据拼出）。 */
export interface ComputerMovementEvent {
  id: string;
  type: string;
  occurredAt: string;
  employeeId?: string;
  employeeNo: string;
  employeeName: string;
  previousStatus: string;
  nextStatus: string;
  notes: string;
  operatedBy: string;
}

/** 办公终端流转记录：`GET /api/computers/{id}/movement-history`（权限 it_assets 查看）。 */
export async function fetchComputerMovementHistory(
  computerId: string,
): Promise<ComputerMovementEvent[]> {
  const payload = await api<{ events?: ComputerMovementEvent[] }>(
    `/api/computers/${encodeURIComponent(computerId)}/movement-history`,
  );
  return payload.events ?? [];
}

export const COMPUTER_STATUS_OPTIONS = ["in_use", "idle", "repair", "retired", "lost"];

export const COMPUTER_EXPORT_HEADER = [
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

/** 导出用的二维表：CSV 与 Excel 共用同一份数据。 */
export function computersToRows(
  rows: ComputerRow[],
  orgNameOf: (orgId: string) => string,
  userNameOf: (userId: string) => string,
): string[][] {
  return rows.map((row) => [
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
}
