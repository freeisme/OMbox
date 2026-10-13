import { api } from "./client";
import { asText } from "./exports";
import { deviceTypeLabel } from "../labels";

export interface ScrapRecord {
  kind: string;
  id: string;
  scrapAt: string;
  quantity: number | string;
  reason: string;
  notes?: string;
  operatedByName?: string;
  employeeName?: string;
  employeeNo?: string;
  /** 办公终端报废快照（asset_scrap_record）。 */
  deviceName?: string;
  deviceType?: string;
  brandName?: string;
  modelName?: string;
  cpu?: string;
  memory?: string;
  storage?: string;
  gpu?: string;
  fixedAssetCode?: string;
  snSt?: string;
  purchaseDate?: string;
  registeredDate?: string;
  previousStatus?: string;
}

/**
 * 报废记录页只列办公终端的报废：IT 物资的报废不进这个页面，只在「操作日志」里留痕。
 */
export async function fetchAssetScrapRecords(limit = 500): Promise<ScrapRecord[]> {
  const params = new URLSearchParams({ kind: "asset", limit: String(limit) });
  const payload = await api<{ records?: ScrapRecord[] }>(`/api/scrap-records?${params.toString()}`);
  return Array.isArray(payload.records) ? payload.records : [];
}

/** 办公终端点「报废」后状态显示为「待报废」（设备已归档，实际处置前仍可追溯）。 */
export const SCRAP_STATUS_LABEL = "待报废";

/** 品牌型号合成一列，空值统一显示破折号。 */
export function scrapModelLabel(record: ScrapRecord): string {
  return [record.brandName, record.modelName].filter(Boolean).join(" ") || "—";
}

/** 配置合成一列：CPU / 内存 / 存储 / 显卡。 */
export function scrapConfigLabel(record: ScrapRecord): string {
  return [record.cpu, record.memory, record.storage, record.gpu].filter(Boolean).join(" / ") || "—";
}

export const SCRAP_EXPORT_HEADER = [
  "报废时间",
  "设备名称",
  "设备类型",
  "品牌型号",
  "配置",
  "固资编码",
  "SN/ST",
  "使用人",
  "人员编号",
  "状态",
  "报废原因",
  "说明",
  "操作人",
];

/** 导出用的二维表：CSV 与 Excel 共用同一份数据。 */
export function scrapRecordsToRows(records: ScrapRecord[]): string[][] {
  return records.map((record) =>
    [
      record.scrapAt,
      record.deviceName,
      deviceTypeLabel(record.deviceType),
      scrapModelLabel(record),
      scrapConfigLabel(record),
      record.fixedAssetCode,
      record.snSt,
      record.employeeName,
      record.employeeNo,
      SCRAP_STATUS_LABEL,
      record.reason,
      record.notes,
      record.operatedByName,
    ].map(asText),
  );
}
