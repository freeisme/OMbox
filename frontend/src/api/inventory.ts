import { api } from "./client";

export interface WarehouseRow {
  id: string;
  code: string;
  name: string;
  orgId: string;
  managerEmployeeId?: string;
  managerName?: string;
  contactPhone?: string;
  address?: string;
  isActive?: unknown;
  remarks?: string;
}

export interface InventoryTypeRow {
  id: string;
  code: string;
  name: string;
  unit: string;
}

export interface InventoryBrandRow {
  id: string;
  typeId: string;
  name: string;
  sortOrder?: number;
}

export interface InventoryModelRow {
  id: string;
  typeId: string;
  brandId: string;
  name: string;
  batchKey?: string;
  quantity: number | string;
  inboundDate?: string;
  cpu?: string;
  memory?: string;
  storage?: string;
  gpu?: string;
  sortOrder?: number;
}

export interface WarehouseStockRow {
  warehouseId?: string;
  modelId?: string;
  quantity?: number | string;
}

export interface PurchaseLogRow {
  id: string;
  typeName?: string;
  brandName?: string;
  modelName?: string;
  quantity?: number | string;
  inboundDate?: string;
  sourceLabel?: string;
  note?: string;
  warehouseId?: string;
  createdAt?: string;
}

export interface InventoryData {
  warehouses: WarehouseRow[];
  types: InventoryTypeRow[];
  brands: InventoryBrandRow[];
  models: InventoryModelRow[];
  stocks: WarehouseStockRow[];
  purchaseLogs: PurchaseLogRow[];
  orgs: Array<{ id: string; name: string; code: string; parentId: string }>;
}

let cache: { at: number; data: InventoryData } | null = null;

/** 中文按拼音、数字按数值比较（型号里的 V2511 / 24D1FC 也能排得自然）。 */
function compareName(a: string, b: string): number {
  return String(a || "").localeCompare(String(b || ""), "zh-CN", {
    numeric: true,
    sensitivity: "base",
  });
}

/**
 * 目录三个层级各自排序，保证「每一级都排在自己的上一级下面」而不是按主键散排：
 * 类型按名称（它没有 sortOrder），品牌与型号先按 sortOrder 再按名称。
 */
function sortInventoryRefs(data: InventoryData): InventoryData {
  const byOrderThenName = <T extends { name: string; sortOrder?: unknown }>(rows: T[]): T[] =>
    [...rows].sort(
      (a, b) =>
        Number(a.sortOrder ?? 1000) - Number(b.sortOrder ?? 1000) || compareName(a.name, b.name),
    );
  return {
    ...data,
    types: [...data.types].sort((a, b) => compareName(a.name, b.name)),
    brands: byOrderThenName(data.brands),
    models: byOrderThenName(data.models),
  };
}

export async function loadInventoryData(force = false): Promise<InventoryData> {
  if (cache && !force && Date.now() - cache.at < 60_000) return cache.data;
  const payload = await api<Record<string, unknown>>(
    "/api/state?include=warehouses,nonAssetTypes,inventoryBrands,inventoryModels,warehouseStocks,inventoryPurchaseLogs,orgs",
  );
  const data: InventoryData = {
    warehouses: (payload.warehouses as WarehouseRow[]) ?? [],
    types: (payload.nonAssetTypes as InventoryTypeRow[]) ?? [],
    brands: (payload.inventoryBrands as InventoryBrandRow[]) ?? [],
    models: (payload.inventoryModels as InventoryModelRow[]) ?? [],
    stocks: (payload.warehouseStocks as WarehouseStockRow[]) ?? [],
    purchaseLogs: (payload.inventoryPurchaseLogs as PurchaseLogRow[]) ?? [],
    orgs: (payload.orgs as InventoryData["orgs"]) ?? [],
  };
  const sorted = sortInventoryRefs(data);
  cache = { at: Date.now(), data: sorted };
  return sorted;
}

export function invalidateInventoryCache(): void {
  cache = null;
}

export async function receiveInventory(payload: {
  modelId: string;
  warehouseId: string;
  quantity: number;
  inboundDate: string;
  sourceLabel: string;
  note: string;
}): Promise<void> {
  await api("/api/inventory/receipts", { method: "POST", body: payload });
}

export async function transferInventory(payload: {
  modelId: string;
  sourceWarehouseId: string;
  targetWarehouseId: string;
  quantity: number;
  note: string;
}): Promise<void> {
  await api("/api/inventory/transfers", { method: "POST", body: payload });
}

export async function saveWarehouse(
  payload: {
    code: string;
    name: string;
    orgId: string;
    managerEmployeeId: string;
    contactPhone: string;
    address: string;
    remarks: string;
  },
  warehouseId = "",
): Promise<void> {
  if (warehouseId) {
    await api(`/api/inventory/warehouses/${warehouseId}`, { method: "PUT", body: payload });
    return;
  }
  await api("/api/inventory/warehouses", { method: "POST", body: payload });
}

export async function deleteWarehouse(warehouseId: string): Promise<void> {
  await api(`/api/inventory/warehouses/${warehouseId}`, { method: "DELETE" });
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

export async function saveInventoryBrand(
  payload: { typeId: string; name: string; sortOrder: number },
  brandId = "",
): Promise<{ id: string }> {
  const result = await api<{ inventoryBrand?: { id?: string } }>(
    brandId ? `/api/resources/inventory-brand/${brandId}` : "/api/resources/inventory-brand",
    { method: brandId ? "PUT" : "POST", body: payload },
  );
  return { id: String(result.inventoryBrand?.id ?? brandId) };
}

export interface InventoryModelPayload {
  typeId: string;
  brandId: string;
  name: string;
  batchKey: string;
  inboundDate: string;
  cpu: string;
  memory: string;
  storage: string;
  gpu: string;
  sortOrder: number;
}

export async function saveInventoryModel(
  payload: InventoryModelPayload,
  modelId = "",
): Promise<{ id: string }> {
  const result = await api<{ inventoryModel?: { id?: string } }>(
    modelId ? `/api/resources/inventory-model/${modelId}` : "/api/resources/inventory-model",
    { method: modelId ? "PUT" : "POST", body: payload },
  );
  return { id: String(result.inventoryModel?.id ?? modelId) };
}

/** 按差值调整某仓库的库存数量（正数走入库，负数走调整），用于型号维护里的数量列。 */
export async function adjustInventory(payload: {
  modelId: string;
  warehouseId: string;
  quantityDelta: number;
  note: string;
}): Promise<void> {
  await api("/api/inventory/adjustments", { method: "POST", body: payload });
}

export interface InventoryTreeType {
  id: string;
  /** 表格 row-key：类型 / 品牌 / 型号的主键各自独立会撞车，必须拼层级前缀。 */
  key: string;
  code: string;
  name: string;
  unit: string;
  level: "type";
  quantity: number;
  children: InventoryTreeBrand[];
}

export interface InventoryTreeBrand {
  id: string;
  key: string;
  typeId: string;
  name: string;
  unit?: string;
  level: "brand";
  quantity: number;
  children: InventoryTreeModel[];
}

export interface InventoryTreeModel {
  id: string;
  key: string;
  typeId: string;
  brandId: string;
  name: string;
  unit?: string;
  level: "model";
  quantity: number;
  inboundDate: string;
  config: string;
  batchKey: string;
}

export function buildInventoryTree(
  data: InventoryData,
  warehouseId: string,
): InventoryTreeType[] {
  const stockByModel = new Map<string, number>();
  data.stocks.forEach((row) => {
    const modelId = String(row.modelId ?? "");
    if (!modelId) return;
    if (warehouseId && String(row.warehouseId ?? "") !== warehouseId) return;
    stockByModel.set(modelId, (stockByModel.get(modelId) ?? 0) + Number(row.quantity ?? 0));
  });
  const quantityOf = (model: InventoryModelRow) =>
    warehouseId ? stockByModel.get(model.id) ?? 0 : Number(model.quantity ?? 0);

  return data.types.map((type) => {
    const brands = data.brands
      .filter((brand) => brand.typeId === type.id)
      .map((brand) => {
        const models = data.models
          .filter((model) => model.brandId === brand.id && quantityOf(model) > 0)
          .map((model) => ({
            id: model.id,
            key: `model:${model.id}`,
            typeId: type.id,
            brandId: brand.id,
            name: model.name,
            unit: type.unit || "件",
            level: "model" as const,
            quantity: quantityOf(model),
            inboundDate: model.inboundDate ?? "",
            config: [model.cpu, model.memory, model.storage, model.gpu].filter(Boolean).join(" / "),
            batchKey: model.batchKey ?? "",
          }));
        return {
          id: brand.id,
          key: `brand:${brand.id}`,
          typeId: type.id,
          name: brand.name,
          unit: type.unit || "件",
          level: "brand" as const,
          quantity: models.reduce((sum, item) => sum + item.quantity, 0),
          children: models,
        };
      })
      // 品牌即使当前仓库没有在库型号也保留，便于在页面上继续维护型号（与旧前端一致）。
    return {
      id: type.id,
      key: `type:${type.id}`,
      code: type.code,
      name: type.name,
      unit: type.unit || "件",
      level: "type" as const,
      quantity: brands.reduce((sum, item) => sum + item.quantity, 0),
      children: brands,
    };
  });
}
