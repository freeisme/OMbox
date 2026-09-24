import { api } from "./client";

export interface InspectionSite {
  id: string;
  code: string;
  name: string;
  siteType?: string;
  location?: string;
  remarks?: string;
  rackCount?: number;
  isActive?: unknown;
}

export interface InspectionRack {
  id: string;
  code: string;
  name: string;
  siteId: string;
  siteName?: string;
  heightU?: number;
  remarks?: string;
  isActive?: unknown;
}

export interface InspectionTemplate {
  id: string;
  code?: string;
  name: string;
  /** 适用对象：server_room / weak_room / meeting_room / both。 */
  siteType?: string;
  description?: string;
  scopeKind?: string;
  /** 列表接口返回的检查项数量（列表不带 items 明细）。 */
  itemCount?: number;
  isActive?: unknown;
  items?: InspectionTemplateItem[];
}

export interface InspectionTemplateItem {
  id?: string;
  seqNo?: number;
  category?: string;
  title: string;
  checkMethod?: string;
  valueType?: string;
  unit?: string;
  normalRange?: string;
  isRequired?: boolean;
}

export interface InspectionTask {
  id: string;
  number?: string;
  taskNo?: string;
  /** 一次多选开检的任务共用同一个批次号，用于横向导出本次巡检的目标。 */
  batchNo?: string;
  status: string;
  scopeKind?: string;
  scopeName?: string;
  /** 对象类型快照：server_room / weak_room / meeting_room（机柜为所属机房的类型）。 */
  siteType?: string;
  siteId?: string;
  siteName?: string;
  rackId?: string;
  rackName?: string;
  templateId?: string;
  templateName?: string;
  inspectorName?: string;
  startedAt?: string;
  submittedAt?: string;
  remarks?: string;
  abnormalSummary?: string;
  items?: InspectionTaskItem[];
}

export interface InspectionTaskItem {
  id: string;
  title: string;
  category?: string;
  checkMethod?: string;
  result?: string;
  notes?: string;
  valueText?: string;
  seqNo?: number;
  checkedByName?: string;
  checkedAt?: string;
}

export const INSPECTION_TASK_STATUS_LABELS: Record<string, string> = {
  running: "进行中",
  submitted: "已提交",
  void: "已作废",
};

export const INSPECTION_RESULT_OPTIONS = [
  { value: "ok", label: "正常" },
  // 与后端 CHECK_RESULTS 保持一致：pending / ok / fail / na
  { value: "fail", label: "异常" },
  { value: "na", label: "不适用" },
];

export async function fetchInspectionSites(): Promise<InspectionSite[]> {
  const payload = await api<{ sites?: InspectionSite[] }>("/api/inspection/sites");
  return payload.sites ?? [];
}

export async function fetchInspectionRacks(): Promise<InspectionRack[]> {
  const payload = await api<{ racks?: InspectionRack[] }>("/api/inspection/racks");
  return payload.racks ?? [];
}

export async function fetchInspectionTemplates(): Promise<InspectionTemplate[]> {
  const payload = await api<{ templates?: InspectionTemplate[] }>("/api/inspection/templates");
  return payload.templates ?? [];
}

/** 单个模板详情（含事项明细），编辑模板时用。 */
export async function fetchInspectionTemplate(templateId: string): Promise<InspectionTemplate> {
  const payload = await api<{ template: InspectionTemplate }>(
    `/api/inspection/templates/${encodeURIComponent(templateId)}`,
  );
  return payload.template;
}

export interface InspectionSitePayload {
  code: string;
  name: string;
  siteType: string;
  location?: string;
  remarks?: string;
}

/** 新建 / 修改机房或弱电间（PUT 需要传完整字段，调用方要带上已有的位置与备注）。 */
export async function saveInspectionSite(
  payload: InspectionSitePayload,
  siteId = "",
): Promise<void> {
  if (siteId) {
    await api(`/api/inspection/sites/${encodeURIComponent(siteId)}`, {
      method: "PUT",
      body: payload,
    });
    return;
  }
  await api("/api/inspection/sites", { method: "POST", body: payload });
}

export interface InspectionRackPayload {
  code: string;
  name: string;
  siteId: string;
  heightU: string;
  remarks?: string;
}

/** 新建 / 修改机柜；机柜必须归属一个机房或弱电间。 */
export async function saveInspectionRack(
  payload: InspectionRackPayload,
  rackId = "",
): Promise<void> {
  if (rackId) {
    await api(`/api/inspection/racks/${encodeURIComponent(rackId)}`, {
      method: "PUT",
      body: payload,
    });
    return;
  }
  await api("/api/inspection/racks", { method: "POST", body: payload });
}

/** 删除机房 / 弱电间；下面还挂着机柜或已有巡检记录时后端会拒绝。 */
export async function deleteInspectionSite(siteId: string, reason = ""): Promise<void> {
  await api(`/api/inspection/sites/${encodeURIComponent(siteId)}`, {
    method: "DELETE",
    body: { reason },
  });
}

/** 删除机柜；柜内有已上架设备、端口链路或巡检记录时后端会拒绝。 */
export async function deleteInspectionRack(rackId: string, reason = ""): Promise<void> {
  await api(`/api/inspection/racks/${encodeURIComponent(rackId)}`, {
    method: "DELETE",
    body: { reason },
  });
}

export interface InspectionTemplateItemPayload {
  category: string;
  title: string;
  checkMethod: string;
  valueType: string;
  unit: string;
  normalRange: string;
  isRequired: boolean;
}

export interface InspectionTemplatePayload {
  code: string;
  name: string;
  siteType: string;
  description: string;
  items: InspectionTemplateItemPayload[];
}

export async function saveInspectionTemplate(
  payload: InspectionTemplatePayload,
  templateId = "",
): Promise<void> {
  if (templateId) {
    await api(`/api/inspection/templates/${encodeURIComponent(templateId)}`, {
      method: "PUT",
      body: payload,
    });
    return;
  }
  await api("/api/inspection/templates", { method: "POST", body: payload });
}

/** 删除巡检模板；历史巡检任务保留当时的模板名称与事项快照。 */
export async function deleteInspectionTemplate(templateId: string, reason = ""): Promise<void> {
  await api(`/api/inspection/templates/${encodeURIComponent(templateId)}`, {
    method: "DELETE",
    body: { reason },
  });
}

// ------------------------------------------------------- 巡检对象里的设备（会议室）

export interface SiteDevice {
  id: string;
  source: "inventory" | "custom";
  name: string;
  deviceType: string;
  brand: string;
  model: string;
  quantity: number;
  status: string;
  notes: string;
  modelId?: string;
  warehouseId?: string;
  warehouseName?: string;
  createdAt?: string;
}

export interface SiteDevicePayload {
  source: "inventory" | "custom";
  modelId?: string;
  warehouseId?: string;
  name?: string;
  deviceType?: string;
  brand?: string;
  model?: string;
  quantity?: number;
  notes?: string;
}

export async function fetchSiteDevices(
  siteId: string,
): Promise<{ site: { id: string; name: string; siteType: string }; devices: SiteDevice[] }> {
  return api(`/api/inspection/sites/${encodeURIComponent(siteId)}/devices`);
}

export async function addSiteDevice(siteId: string, payload: SiteDevicePayload): Promise<unknown> {
  return api(`/api/inspection/sites/${encodeURIComponent(siteId)}/devices`, {
    method: "POST",
    body: payload,
  });
}

export async function removeSiteDevice(
  deviceId: string,
  payload: { reason?: string; warehouseId?: string } = {},
): Promise<unknown> {
  return api(`/api/inspection/site-devices/${encodeURIComponent(deviceId)}`, {
    method: "DELETE",
    body: payload,
  });
}

export async function fetchInspectionTasks(): Promise<InspectionTask[]> {
  const payload = await api<{ tasks?: InspectionTask[] }>("/api/inspection/tasks");
  return payload.tasks ?? [];
}

export async function fetchInspectionTask(taskId: string): Promise<InspectionTask> {
  const payload = await api<{ task: InspectionTask }>(`/api/inspection/tasks/${taskId}`);
  return payload.task;
}

export interface InspectionTargetPayload {
  kind: "site" | "rack";
  id: string;
}

export interface InspectionStartResult {
  batchNo: string;
  taskCount: number;
  tasks: Array<{ id: string; taskNo: string; scopeLabel?: string; itemTotal?: number }>;
}

/**
 * 开始巡检：targets 可以是一个或多个对象（机房 / 弱电间 / 会议室 / 机柜），
 * 一个对象生成一张任务，同批次号用于横向导出本次巡检的目标。
 */
export async function createInspectionTask(body: {
  templateId: string;
  targets: InspectionTargetPayload[];
  inspectorUserId: string;
  remarks: string;
}): Promise<InspectionStartResult> {
  return api<InspectionStartResult>("/api/inspection/tasks", { method: "POST", body });
}

export async function checkInspectionItem(
  taskId: string,
  itemId: string,
  body: { result: string; notes: string; valueText: string },
): Promise<void> {
  await api(`/api/inspection/tasks/${taskId}/items/${itemId}/check`, { method: "POST", body });
}

export async function submitInspectionTask(
  taskId: string,
  body: { abnormalSummary: string; remarks: string },
): Promise<void> {
  await api(`/api/inspection/tasks/${taskId}/submit`, { method: "POST", body });
}

export async function voidInspectionTask(taskId: string, reason: string): Promise<void> {
  await api(`/api/inspection/tasks/${taskId}/void`, { method: "POST", body: { reason } });
}

/** 删除已作废的巡检任务（含明细）；未作废的任务必须先作废。 */
export async function deleteInspectionTask(taskId: string, reason = ""): Promise<void> {
  await api(`/api/inspection/tasks/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
    body: { reason },
  });
}

/** 巡检表导入的列（与「下载模板」生成的表头一致）。 */
export const INSPECTION_IMPORT_COLUMNS = [
  "巡检对象",
  "机柜",
  "检查项分类",
  "检查项",
  "检查方法",
  "结论",
  "实测值",
  "说明",
] as const;

export interface InspectionImportResult {
  id: string;
  taskNo: string;
  siteName: string;
  rackName: string;
  itemTotal: number;
  itemOk: number;
  itemFail: number;
  itemNa: number;
  errors: Array<{ row: number; message: string }>;
  errorCount: number;
}

/** 按模板上传表格并生成一份"已提交"的巡检记录。 */
export async function importInspectionTask(payload: {
  fileName: string;
  contentBase64: string;
  remarks?: string;
}): Promise<InspectionImportResult> {
  return api<InspectionImportResult>("/api/inspection/tasks/import", {
    method: "POST",
    body: payload,
  });
}

export interface SyncRun {
  id: string;
  sourceCode?: string;
  status: string;
  recordsTotal?: number;
  recordsValid?: number;
  recordsInvalid?: number;
  recordsApplied?: number;
  startedAt?: string;
  completedAt?: string;
}

export interface QualityIssue {
  id: string;
  title: string;
  status: string;
  severityLabel?: string;
  ruleLabel?: string;
  entityTypeLabel?: string;
  firstDetectedAt?: string;
  details?: string;
  resolutionResult?: string;
}

export const SYNC_RUN_STATUS_LABELS: Record<string, string> = {
  staged: "已暂存",
  validated: "已校验",
  applied: "已应用",
  failed: "失败",
  cancelled: "已取消",
};

export async function fetchSyncRuns(): Promise<SyncRun[]> {
  const payload = await api<{ runs?: SyncRun[] }>("/api/sync-runs");
  return payload.runs ?? [];
}

export async function applySyncRun(runId: string): Promise<void> {
  await api(`/api/sync-runs/${runId}/apply`, { method: "POST", body: {} });
}

export async function fetchQualityIssues(status = "open"): Promise<QualityIssue[]> {
  const payload = await api<{ issues?: QualityIssue[] }>(
    `/api/data-quality/issues?status=${encodeURIComponent(status)}`,
  );
  return payload.issues ?? [];
}

export async function runQualityCheck(): Promise<void> {
  await api("/api/data-quality/run", { method: "POST", body: {} });
}

export async function resolveQualityIssue(issueId: string, resolutionResult: string): Promise<void> {
  await api(`/api/data-quality/issues/${issueId}/resolve`, {
    method: "POST",
    body: { resolutionResult },
  });
}

export async function ignoreQualityIssue(issueId: string, reason: string): Promise<void> {
  await api(`/api/data-quality/issues/${issueId}/ignore`, {
    method: "POST",
    body: { reason },
  });
}
