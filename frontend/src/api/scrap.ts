import { api } from "./client";

export interface ScrapRecord {
  kind: "inventory" | "asset" | string;
  id: string;
  scrapAt: string;
  quantity: number | string;
  reason: string;
  notes?: string;
  stockAdjusted?: number | boolean;
  operatedByName?: string;
  employeeName?: string;
  employeeNo?: string;
  deviceName?: string;
  brandName?: string;
  modelName?: string;
  typeName?: string;
  warehouseName?: string;
  assetCode?: string;
  serialNumber?: string;
}

export function scrapKindLabel(kind: string): string {
  return kind === "asset" ? "办公终端" : "IT物资";
}

export function scrapRecordTitle(record: ScrapRecord): string {
  if (record.kind === "asset") return record.deviceName || "办公终端";
  return (
    [record.brandName, record.modelName].filter(Boolean).join(" ") || record.typeName || "IT物资"
  );
}

export function scrapRecordSubtitle(record: ScrapRecord): string {
  if (record.kind === "asset") {
    return [record.brandName, record.modelName].filter(Boolean).join(" · ") || "未填写品牌型号";
  }
  return [record.typeName, record.warehouseName].filter(Boolean).join(" · ") || "未关联库存类型";
}

export async function fetchScrapRecords(kind = "", limit = 500): Promise<ScrapRecord[]> {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  params.set("limit", String(limit));
  const payload = await api<{ records?: ScrapRecord[] }>(`/api/scrap-records?${params.toString()}`);
  return Array.isArray(payload.records) ? payload.records : [];
}

export function scrapRecordsToCsv(records: ScrapRecord[]): string {
  const header = [
    "报废时间",
    "类型",
    "物品",
    "数量",
    "使用人",
    "人员编号",
    "报废原因",
    "说明",
    "操作人",
    "库存影响",
  ];
  const body = records.map((record) => [
    record.scrapAt,
    scrapKindLabel(record.kind),
    scrapRecordTitle(record),
    Number(record.quantity || 0) || 1,
    record.employeeName,
    record.employeeNo,
    record.reason,
    record.notes,
    record.operatedByName,
    Number(record.stockAdjusted) === 1 ? "已扣库存 · 不返还" : "未扣库存 · 无变化",
  ]);
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [header, ...body].map((line) => line.map(escape).join(",")).join("\r\n");
}
