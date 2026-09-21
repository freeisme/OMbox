/** 与旧前端 statusLabels / deviceTypeLabels 保持一致的展示标签。 */

export const STATUS_LABELS: Record<string, string> = {
  in_use: "在用",
  idle: "闲置",
  repair: "维修",
  retired: "报废",
  lost: "丢失",
  active: "在职",
  inactive: "停用",
  left: "离职",
  shared: "公用",
};

export const DEVICE_TYPE_LABELS: Record<string, string> = {
  laptop: "笔记本",
  desktop: "台式机",
  workstation: "工作站",
  mini_pc: "迷你主机",
};

export const COMPUTER_STATUS_OPTIONS = ["in_use", "idle", "repair", "retired", "lost"];

/** 机柜 / 机房设备类型（与后端 category 枚举一致）。 */
export const RACK_CATEGORY_LABELS: Record<string, string> = {
  server: "服务器",
  network: "网络设备",
  "patch-panel": "配线架",
  power: "供电（UPS/PDU）",
  storage: "存储",
  kvm: "KVM",
  "av-media": "音视频",
  cooling: "散热",
  shelf: "层板",
  blank: "挡板",
  "cable-management": "理线",
  other: "其他",
};

/** 机房设备台账状态（与后端 datacenter_device.status 一致）。 */
export const DATACENTER_STATUS_LABELS: Record<string, string> = {
  stock: "未上架",
  installed: "上架",
  repair: "维修",
  scrapped: "报废",
};

export function rackCategoryLabel(value: string): string {
  return RACK_CATEGORY_LABELS[value] || value || "其他";
}

export function datacenterStatusLabel(value: string): string {
  return DATACENTER_STATUS_LABELS[value] || value || "—";
}

export function datacenterStatusTagType(value: string): "success" | "info" | "warning" | "danger" {
  if (value === "installed") return "success";
  if (value === "repair") return "warning";
  if (value === "scrapped") return "danger";
  return "info";
}

export const TICKET_STATUS_LABELS: Record<string, string> = {
  new: "新建",
  assigned: "已分配",
  in_progress: "处理中",
  pending: "挂起",
  resolved: "已解决",
  closed: "已关闭",
  cancelled: "已取消",
};

export const TICKET_OPEN_STATUSES = ["new", "assigned", "in_progress", "pending"];

export const INSPECTION_TASK_STATUS_LABELS: Record<string, string> = {
  running: "进行中",
  submitted: "已提交",
  void: "已作废",
};

export const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  ticket: "工单",
  change: "变更",
  problem: "问题",
  knowledge: "知识库",
  approval: "审批",
  system: "系统",
};

export function statusLabel(value: string): string {
  return STATUS_LABELS[value] || value || "—";
}

export function deviceTypeLabel(value: string): string {
  return DEVICE_TYPE_LABELS[value] || value || "";
}

export function statusTagType(value: string): "success" | "info" | "warning" | "danger" {
  if (value === "in_use" || value === "active") return "success";
  if (value === "repair") return "warning";
  if (value === "retired" || value === "lost") return "danger";
  return "info";
}

export function ticketStatusLabel(value: string): string {
  return TICKET_STATUS_LABELS[value] || value || "—";
}

export function ticketStatusTagType(value: string): "success" | "info" | "warning" | "danger" {
  if (value === "resolved" || value === "closed") return "success";
  if (value === "in_progress") return "warning";
  if (value === "cancelled") return "info";
  return "danger";
}

export function notificationTypeLabel(value: string): string {
  return NOTIFICATION_TYPE_LABELS[value] || value || "系统";
}

export function formatDateTimeText(value: string | undefined | null): string {
  if (!value) return "—";
  return String(value).replace("T", " ").slice(0, 16);
}
