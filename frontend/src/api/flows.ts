import { api } from "./client";

export interface FlowRecord {
  id: string;
  direction: string;
  typeName: string;
  brandName: string;
  modelName: string;
  quantity: number | string;
  sourceLabel: string;
  targetLabel: string;
  note: string;
  originalNote?: string;
  effectiveNote?: string;
  noteCorrections?: Array<{ correctedNote?: string; correctionReason?: string; createdAt?: string }>;
  relatedEmployeeNo: string;
  relatedEmployeeName: string;
  triggerAction: string;
  occurredAt: string;
}

export interface FlowDefinition {
  label: string;
  category: string;
  stockDelta?: number;
}

/** 与旧前端 flowRecordDefinitions 保持一致（业务类型 / 分类 / 库存影响）。 */
export const FLOW_DEFINITIONS: Record<string, FlowDefinition> = {
  inventory_receipt: { label: "仓库入库", category: "库存入库", stockDelta: 1 },
  inventory_adjustment: { label: "库存调整", category: "库存管理" },
  inventory_transfer: { label: "仓库调拨", category: "库存调拨", stockDelta: 0 },
  import: { label: "导入入库", category: "库存入库", stockDelta: 1 },
  manual_create: { label: "手工入库", category: "库存入库", stockDelta: 1 },
  manual_adjustment: { label: "库存调整", category: "库存管理" },
  computer_inventory_adjustment: { label: "终端库存调整", category: "库存管理" },
  assignment: { label: "领用发放", category: "领用发放", stockDelta: -1 },
  // 新版库存领用/归还命令写入的动作码（旧前端映射表未覆盖，会显示原始英文码）
  inventory_allocation: { label: "库存领用", category: "领用发放", stockDelta: -1 },
  inventory_return: { label: "库存归还", category: "归还回收", stockDelta: 1 },
  return: { label: "归还回收", category: "归还回收", stockDelta: 1 },
  return_adjustment: { label: "归还回收", category: "归还回收", stockDelta: 1 },
  employee_device_recovery: { label: "设备回收", category: "归还回收", stockDelta: 1 },
  leave_recovery: { label: "离职回收", category: "归还回收", stockDelta: 1 },
  employee_delete_recovery: { label: "人员删除回收", category: "归还回收", stockDelta: 1 },
  delete_monitor: { label: "显示器回收", category: "归还回收", stockDelta: 1 },
  delete_nonasset: { label: "物资回收", category: "归还回收", stockDelta: 1 },
  delete_type: { label: "删除类型", category: "库存管理", stockDelta: -1 },
  delete_inventory_model: { label: "删除型号", category: "库存管理", stockDelta: -1 },
};

export function flowDefinition(record: FlowRecord): FlowDefinition {
  const found = FLOW_DEFINITIONS[record.triggerAction];
  if (found) return { ...found };
  return {
    label: record.triggerAction || (record.direction === "increase" ? "增加" : "减少"),
    category: "其他变动",
  };
}

export function flowStockImpact(record: FlowRecord): string {
  const definition = flowDefinition(record);
  if (definition.stockDelta === 0) return "不变";
  return record.direction === "decrease" ? "减少" : "增加";
}

export function flowNoteText(record: FlowRecord): string {
  return record.effectiveNote || record.note || record.originalNote || "";
}

export async function loadFlowRecords(force = false): Promise<FlowRecord[]> {
  // 流转记录只要 movementLogs 一块：整包约 567 KB，裁剪后约 115 KB。
  const payload = await api<{ inventoryMovementLogs?: FlowRecord[] }>(
    "/api/state?include=inventoryMovementLogs",
  );
  const logs = Array.isArray(payload.inventoryMovementLogs) ? payload.inventoryMovementLogs : [];
  if (force) return logs;
  return logs;
}

export async function correctFlowNote(
  movementLogId: string,
  payload: { correctedNote: string; correctionReason: string },
): Promise<void> {
  await api(`/api/inventory/movement-logs/${movementLogId}/note-corrections`, {
    method: "POST",
    body: payload,
  });
}

export function flowRecordsToCsv(records: FlowRecord[]): string {
  const header = [
    "时间",
    "业务类型",
    "业务分类",
    "物资类型",
    "品牌",
    "型号",
    "数量",
    "库存影响",
    "调出方",
    "接收方",
    "关联人员",
    "备注",
    "修正次数",
  ];
  const body = records.map((record) => [
    record.occurredAt,
    flowDefinition(record).label,
    flowDefinition(record).category,
    record.typeName,
    record.brandName,
    record.modelName,
    record.quantity,
    flowStockImpact(record),
    record.sourceLabel,
    record.targetLabel,
    [record.relatedEmployeeName, record.relatedEmployeeNo].filter(Boolean).join(" / "),
    flowNoteText(record),
    (record.noteCorrections ?? []).length,
  ]);
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  return [header, ...body].map((line) => line.map(escape).join(",")).join("\r\n");
}
