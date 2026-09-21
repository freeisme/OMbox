import { api, downloadFile } from "./client";

/** 系统更新来源与通道，取值必须与后端保持一致。 */
export const UPDATE_SOURCES: Record<string, string> = {
  github: "GitHub 官方更新",
  custom: "自定义更新地址",
};

export const UPDATE_RELEASE_CHANNELS: Record<string, string> = {
  release: "发行版",
  beta: "Beta 版",
};

export const DEFAULT_UPDATE_RELEASE_CHANNEL = "beta";
export const GITHUB_UPDATE_REPOSITORY_URL = "https://github.com/freeisme/OMbox.git";

export const ROLE_CATEGORIES: Record<string, string> = {
  admin: "管理员",
  ordinary: "普通用户",
  custom: "自定义角色",
};

export const PERMISSION_ACTIONS: Array<{ action: string; label: string; flag: string }> = [
  { action: "view", label: "查看", flag: "canView" },
  { action: "create", label: "新增", flag: "canCreate" },
  { action: "update", label: "修改", flag: "canUpdate" },
  { action: "delete", label: "删除", flag: "canDelete" },
  { action: "approve", label: "审批", flag: "canApprove" },
  { action: "export", label: "导出", flag: "canExport" },
];

export const DATA_SCOPES: Record<string, string> = {
  all: "全部数据",
  organization: "所属部门及下属部门",
  own: "本人数据",
  submitted: "本人提交",
  assigned: "本人负责",
  none: "无数据",
};

/** 权限模块的中文名（后端 auth_module 里的名字可能带模块编码后缀）。 */
export const PERMISSION_MODULE_LABELS: Record<string, string> = {
  dashboard: "资产总览",
  it_assets: "办公终端",
  employees: "使用人员",
  organizations: "组织与资产关系",
  inventory_catalog: "IT物资",
  inventory_operations: "物资流转记录",
  warehouse_management: "仓库管理",
  scrap_management: "报废管理",
  rack_layout: "机房与机柜",
  quality: "数据质量",
  inspection_management: "巡检管理",
  audit_logs: "操作日志",
  backups: "备份",
  role_management: "角色与权限",
  system_settings: "系统设置",
  system_updates: "系统更新",
  user_management: "用户账号",
  sync: "同步与质量",
  tickets: "工单",
  changes: "变更管理",
  problems: "问题管理",
  knowledge: "知识库",
  forms: "表单",
  sla: "SLA策略",
  approvals: "审批流程",
  notifications: "消息提醒",
  service_management: "服务管理",
};

export function permissionModuleLabel(code: string): string {
  return PERMISSION_MODULE_LABELS[code] ?? code;
}

export interface AppSettings {
  app_name?: string;
  login_notice?: string;
  session_hours?: string;
  backup_enabled?: string;
  backup_time?: string;
  backup_retention_days?: string;
  [key: string]: string | undefined;
}

export interface UserRow {
  id: string;
  username: string;
  displayName: string;
  role: string;
  employeeId?: string;
  employeeName?: string;
  department?: string;
  orgName?: string;
  isActive: boolean;
  lastLoginAt?: string;
  createdAt?: string;
}

export interface BackupRow {
  id: string;
  fileName: string;
  fileSize: number | string;
  backupType: string;
  requestedByName?: string;
  status: string;
  fileAvailable: boolean;
  createdAt?: string;
}

export interface AccessModule {
  code: string;
  name: string;
  category?: string;
}

export interface AccessRole {
  id: string;
  code: string;
  name: string;
  category?: string;
  categoryName?: string;
  isActive?: boolean;
  isSuperAdmin?: boolean;
}

export interface PermissionEntry {
  moduleCode: string;
  actionCode: string;
  canView: boolean;
  canCreate: boolean;
  canUpdate: boolean;
  canDelete: boolean;
  canApprove: boolean;
  canExport: boolean;
  dataScope: string;
}

export interface UpdateVersion {
  sha: string;
  shortSha?: string;
  version?: string;
  tag?: string;
  subject?: string;
  authoredAt?: string;
  isCurrent?: boolean;
  isLatest?: boolean;
  isSelectable?: boolean;
  releaseNotes?: string;
}

export interface UpdateStatus {
  status?: string;
  currentVersion?: string;
  currentSha?: string;
  currentShortSha?: string;
  latestVersion?: string;
  latestSha?: string;
  latestShortSha?: string;
  latestVersionSha?: string;
  effectiveRepositoryUrl?: string;
  repositoryUrl?: string;
  releaseChannel?: string;
  availableVersions?: UpdateVersion[];
  latestReleaseNotes?: string;
  targetSha?: string;
  targetVersion?: string;
}

export async function loadSettings(): Promise<AppSettings> {
  const payload = await api<{ settings?: AppSettings }>("/api/settings");
  return payload.settings ?? {};
}

export async function saveSettings(settings: Partial<AppSettings>): Promise<AppSettings> {
  const payload = await api<{ settings?: AppSettings }>("/api/settings", {
    method: "PUT",
    body: { settings },
  });
  return payload.settings ?? {};
}

export async function loadUsers(): Promise<UserRow[]> {
  const payload = await api<{ users?: UserRow[] }>("/api/users");
  return payload.users ?? [];
}

export interface UserPayload {
  username: string;
  displayName: string;
  role: string;
  employeeId: string;
  isActive: boolean;
  password?: string;
}

export async function saveUser(payload: UserPayload, userId = ""): Promise<void> {
  if (userId) {
    await api(`/api/users/${encodeURIComponent(userId)}`, { method: "PUT", body: payload });
    return;
  }
  await api("/api/users", { method: "POST", body: payload });
}

export interface AccessControlData {
  modules: AccessModule[];
  roles: AccessRole[];
  users: Array<{ id: string; username: string; displayName: string }>;
}

export async function loadAccessControl(): Promise<AccessControlData> {
  const payload = await api<Partial<AccessControlData>>("/api/access-control");
  return {
    modules: payload.modules ?? [],
    // 后端返回的角色主键是数字、用户主键是字符串，统一成字符串，避免下拉框匹配不上。
    roles: (payload.roles ?? []).map((role) => ({
      ...role,
      id: String(role.id),
      isActive: Boolean(role.isActive),
      isSuperAdmin: Boolean(role.isSuperAdmin),
    })),
    users: (payload.users ?? []).map((user) => ({ ...user, id: String(user.id) })),
  };
}

export async function loadTargetPermissions(
  targetType: "role" | "user",
  targetId: string,
): Promise<PermissionEntry[]> {
  const base = targetType === "role" ? "/api/roles" : "/api/users";
  const payload = await api<{ permissions?: PermissionEntry[] }>(
    `${base}/${encodeURIComponent(targetId)}/permissions`,
  );
  return payload.permissions ?? [];
}

export async function saveTargetPermissions(
  targetType: "role" | "user",
  targetId: string,
  permissions: PermissionEntry[],
): Promise<void> {
  const base = targetType === "role" ? "/api/roles" : "/api/users";
  await api(`${base}/${encodeURIComponent(targetId)}/permissions`, {
    method: "PUT",
    body: { permissions },
  });
}

export async function createRole(payload: {
  code: string;
  name: string;
  category: string;
  isSuperAdmin: boolean;
  permissions: PermissionEntry[];
}): Promise<AccessRole> {
  const result = await api<{ role?: AccessRole }>("/api/roles", { method: "POST", body: payload });
  const role = result.role ?? { id: "", code: payload.code, name: payload.name };
  return { ...role, id: String(role.id) };
}

export async function loadBackups(): Promise<BackupRow[]> {
  const payload = await api<{ backups?: BackupRow[] }>("/api/backups");
  return payload.backups ?? [];
}

export async function createBackup(): Promise<BackupRow | null> {
  const payload = await api<{ backups?: BackupRow[]; backup?: BackupRow }>("/api/backups", {
    method: "POST",
    body: {},
  });
  return payload.backup ?? null;
}

/** 下载备份需要重新验证当前账号密码，成功后浏览器直接下载。 */
export async function downloadBackup(backupId: string, password: string): Promise<string> {
  return downloadFile(`/api/backups/${encodeURIComponent(backupId)}/download`, { password });
}

export async function changePassword(payload: {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}): Promise<void> {
  await api("/api/auth/change-password", { method: "POST", body: payload });
}

export async function checkForUpdate(payload: {
  repositoryUrl: string;
  releaseChannel: string;
  persistRepositoryUrl: boolean;
}): Promise<UpdateStatus> {
  return api<UpdateStatus>("/api/updates/check", { method: "POST", body: payload });
}

export async function applyUpdate(payload: {
  targetSha: string;
  repositoryUrl: string;
  releaseChannel: string;
}): Promise<UpdateStatus> {
  return api<UpdateStatus>("/api/updates/apply", { method: "POST", body: payload });
}
