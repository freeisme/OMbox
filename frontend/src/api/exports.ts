/** 表格导出：CSV 在本地拼串，xlsx 交给后端渲染（带基础样式的模板）。 */
import { downloadFile } from "./client";

export type ExportFormat = "csv" | "xlsx";

/** 单元格统一转成字符串（导出单元格里 null / number / undefined 都当文本处理）。 */
export function asText(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

export function csvFromRows(header: string[], rows: string[][], title: string[][] = []): string {
  const escape = (value: string) => (/[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
  return [...title, header, ...rows]
    .map((row) => row.map((cell) => escape(String(cell ?? ""))).join(","))
    .join("\r\n");
}

function downloadBlob(blob: Blob, fileName: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(link.href);
}

/**
 * 导出二维表。`fileName` 不带扩展名：
 * - `csv`：浏览器本地生成（与历史导出格式一致）；
 * - `xlsx`：POST `/api/exports/xlsx`，由后端套用基础样式模板（表头填色、边框、冻结首行、自动筛选）。
 */
export async function downloadTable(options: {
  fileName: string;
  sheetName?: string;
  header: string[];
  rows: string[][];
  /** 表头之上的说明行（如巡检表的任务信息），CSV 与 Excel 都会保留。 */
  title?: string[][];
  format: ExportFormat;
}): Promise<void> {
  if (options.format === "csv") {
    const csv = `\ufeff${csvFromRows(options.header, options.rows, options.title)}`;
    downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), `${options.fileName}.csv`);
    return;
  }
  await downloadFile("/api/exports/xlsx", {
    fileName: options.fileName,
    sheetName: options.sheetName ?? "数据",
    title: options.title ?? [],
    header: options.header,
    rows: options.rows,
  });
}
