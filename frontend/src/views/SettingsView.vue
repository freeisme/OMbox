<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import { loadEmployeesData, type EmployeeDetailRow } from "../api/employees";
import {
  applyUpdate,
  changePassword,
  checkForUpdate,
  createBackup,
  createRole,
  DATA_SCOPES,
  DEFAULT_UPDATE_RELEASE_CHANNEL,
  downloadBackup,
  getUpdateProgress,
  GITHUB_UPDATE_REPOSITORY_URL,
  loadAccessControl,
  loadBackups,
  loadSettings,
  loadTargetPermissions,
  loadUsers,
  PERMISSION_ACTIONS,
  permissionModuleLabel,
  ROLE_CATEGORIES,
  saveSettings,
  saveTargetPermissions,
  saveUser,
  importUsers,
  UPDATE_SOURCES,
  type AccessModule,
  type AccessRole,
  type AppSettings,
  type BackupRow,
  type PermissionEntry,
  type UpdateProgress,
  type UpdateStatus,
  type UpdateVersion,
  type UserRow,
  updateRole,
} from "../api/settings";
import { deleteNavLink, listAllNavLinks, saveNavLink, type NavLink } from "../api/company";
import { loadMeta, hasPermission, session } from "../session";
import { confirmAction } from "../composables/useConfirm";
import ImportExcelDialog from "../components/ui/ImportExcelDialog.vue";
import {
  applyThemeColor,
  currentThemeColor,
  DEFAULT_THEME_COLOR,
  resetThemeColor,
  THEME_COLOR_PRESETS,
} from "../theme";

interface PermissionRow {
  code: string;
  label: string;
  scope: string;
  actions: Record<string, boolean>;
}

const health = ref<{ ok: boolean; requiredTables: number; requiredTableCount: number } | null>(null);
const healthError = ref("");
const frontendVersion = __APP_VERSION__;
const frontendBuildTime = __APP_BUILD_TIME__;
const themeColor = ref(currentThemeColor());
const loading = ref(true);
const saving = ref(false);
const route = useRoute();
const activeTab = ref("system");
const navLinks = ref<NavLink[]>([]);
const navLinkDialog = reactive<{
  visible: boolean;
  id: string;
  title: string;
  url: string;
  icon: string;
  sortOrder: number;
  openMode: "new_tab" | "same_tab";
  isActive: boolean;
}>({ visible: false, id: "", title: "", url: "", icon: "", sortOrder: 1000, openMode: "new_tab", isActive: true });
const navLinkSaving = ref(false);

const settings = ref<AppSettings>({});
const users = ref<UserRow[]>([]);
const backups = ref<BackupRow[]>([]);
const modules = ref<AccessModule[]>([]);
const roles = ref<AccessRole[]>([]);
const accessUsers = ref<Array<{ id: string; username: string; displayName: string }>>([]);
const employees = ref<EmployeeDetailRow[]>([]);

const systemForm = reactive({
  app_name: "",
  session_hours: 8,
  login_notice: "",
  /** 公司 Logo：PNG 的 data URI，存 system_setting.app_logo。 */
  app_logo: "",
  export_logo_enabled: false,
  /** 集团名称与模块开关。 */
  group_name: "",
  module_datacenter_enabled: true,
  module_inspection_enabled: true,
});
const passwordForm = reactive({ currentPassword: "", newPassword: "", confirmPassword: "" });
const backupForm = reactive({ backup_enabled: "0", backup_time: "02:00", backup_retention_days: "30" });

const userDialogVisible = ref(false);
const userEditingId = ref("");
const userForm = reactive({
  username: "",
  displayName: "",
  role: "operator",
  employeeId: "",
  isActive: true,
  password: "",
});

const userImportDialog = ref(false);

/** 账号导入模板：表头与后端 USER_IMPORT_ALIASES 对应。 */
const USER_IMPORT_FIELDS: Record<string, string> = {
  username: "用户名",
  displayName: "显示名称",
  role: "角色",
  password: "初始密码",
  employeeNo: "绑定人员工号",
  isActive: "是否启用",
};

const backupDownloadVisible = ref(false);
const backupDownloadTarget = ref<BackupRow | null>(null);
const backupDownloadPassword = ref("");

const accessTargetType = ref<"role" | "user">("role");
const accessTargetId = ref("");
const permissionRows = ref<PermissionRow[]>([]);
const roleForm = reactive({
  code: "",
  name: "",
  category: "custom",
  isSuperAdmin: false,
  rows: [] as PermissionRow[],
});

const roleEditDialog = reactive({
  visible: false,
  id: "",
  name: "",
  category: "custom",
  isSuperAdmin: false,
});

const updateSource = ref("github");
const updateRepositoryUrl = ref("");
const updateReleaseChannel = ref(DEFAULT_UPDATE_RELEASE_CHANNEL);
const updateStatus = ref<UpdateStatus | null>(null);
const updateSelectedSha = ref("");
const updateChecking = ref(false);
const updateApplying = ref(false);

const version = computed(() => session.meta?.version || frontendVersion);
const roleLabel = computed(() =>
  session.isSuperAdmin ? "超级管理员" : String(session.user?.role ?? "—"),
);
const canViewSettings = computed(() => hasPermission("system_settings"));
const canUpdateSettings = computed(() => hasPermission("system_settings", "update"));
const canViewBackups = computed(() => hasPermission("backups"));
const canViewUsers = computed(() => hasPermission("user_management"));
const canViewAccess = computed(() => hasPermission("role_management"));
const canUpdateAccess = computed(() => hasPermission("role_management", "update"));
const canUpdate = computed(() => hasPermission("system_updates", "update"));

const backupEnabled = computed(() => ["1", "true", "yes", "on"].includes(String(backupForm.backup_enabled).toLowerCase()));
const deployBusy = computed(() => ["queued", "running"].includes(String(updateStatus.value?.status ?? "")));
const updateBusy = computed(() => updateChecking.value || updateApplying.value || deployBusy.value);
const availableVersions = computed<UpdateVersion[]>(() => updateStatus.value?.availableVersions ?? []);
const selectableVersions = computed(() =>
  availableVersions.value.filter((item) => item.isSelectable !== false && !item.isCurrent),
);
const selectedVersion = computed(
  () =>
    selectableVersions.value.find((item) => item.sha === updateSelectedSha.value) ??
    selectableVersions.value.find((item) => item.isLatest) ??
    null,
);
const releaseNotes = computed(
  () => selectedVersion.value?.releaseNotes || updateStatus.value?.latestReleaseNotes || "",
);
const currentVersionText = computed(() => {
  const status = updateStatus.value;
  if (!status) return `v${version.value}`;
  const sha = status.currentShortSha || String(status.currentSha ?? "").slice(0, 7) || "-";
  return status.currentVersion ? `${status.currentVersion} · ${sha}` : `未发布版本 · ${sha}`;
});
const latestVersionText = computed(() => {
  const status = updateStatus.value;
  if (!status) return "—";
  const sha = String(status.latestVersionSha ?? status.latestSha ?? "").slice(0, 7);
  return status.latestVersion ? `${status.latestVersion} · ${sha}` : "暂无已发布版本";
});

/** 权限配置的目标下拉项：按“角色 / 用户覆盖”切换。 */
const accessTargetOptions = computed(() =>
  accessTargetType.value === "role"
    ? roles.value.map((role) => ({
        value: role.id,
        label: `${role.name || role.code} · ${role.categoryName || ROLE_CATEGORIES[role.category ?? ""] || "自定义角色"}`,
      }))
    : accessUsers.value.map((user) => ({
        value: user.id,
        label: user.displayName || user.username,
      })),
);

const tabs = computed(() => {
  const items = [
    { key: "system", label: "系统参数", visible: canViewSettings.value },
    { key: "security", label: "安全与密码", visible: true },
    { key: "backup", label: "数据库备份", visible: canViewBackups.value },
    { key: "accounts", label: "账号管理", visible: canViewUsers.value },
    { key: "access", label: "角色与权限", visible: canViewAccess.value },
    { key: "updates", label: "系统更新", visible: canUpdate.value },
    { key: "navLinks", label: "外链应用", visible: session.isSuperAdmin },
  ];
  return items.filter((item) => item.visible);
});

function formatTime(value: string | undefined): string {
  if (!value) return "—";
  return String(value).replace("T", " ").slice(0, 19);
}

function formatFileSize(value: unknown): string {
  const bytes = Math.max(0, Number(value ?? 0));
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${units[index]}`;
}

function backupStatusLabel(row: BackupRow): string {
  if (row.status === "expired") return "已清理";
  if (row.status === "failed") return "失败";
  return row.fileAvailable ? "可下载" : "文件缺失";
}

function buildPermissionRows(
  moduleList: AccessModule[],
  entries: PermissionEntry[],
): PermissionRow[] {
  const byKey = new Map(entries.map((item) => [`${item.moduleCode}:${item.actionCode}`, item]));
  return moduleList.map((module) => {
    const scope = entries.find((item) => item.moduleCode === module.code)?.dataScope ?? "none";
    return {
      code: module.code,
      label: permissionModuleLabel(module.code),
      scope,
      actions: Object.fromEntries(
        PERMISSION_ACTIONS.map(({ action, flag }) => [
          action,
          Boolean((byKey.get(`${module.code}:${action}`) as unknown as Record<string, unknown>)?.[flag]),
        ]),
      ),
    };
  });
}

function emptyPermissionRows(): PermissionRow[] {
  return buildPermissionRows(modules.value, []);
}

/** 把界面上的勾选还原成后端要的权限条目。 */
function toPermissionEntries(rows: PermissionRow[]): PermissionEntry[] {
  const entries: PermissionEntry[] = [];
  rows.forEach((row) => {
    PERMISSION_ACTIONS.forEach(({ action, flag }) => {
      const entry: Record<string, unknown> = {
        moduleCode: row.code,
        actionCode: action,
        canView: false,
        canCreate: false,
        canUpdate: false,
        canDelete: false,
        canApprove: false,
        canExport: false,
        dataScope: row.scope,
      };
      entry[flag] = Boolean(row.actions[action]);
      entries.push(entry as unknown as PermissionEntry);
    });
  });
  return entries;
}

function pickThemeColor(color: string): void {
  themeColor.value = applyThemeColor(color);
}

function restoreDefaultTheme(): void {
  themeColor.value = resetThemeColor();
}

async function loadAll(): Promise<void> {
  loading.value = true;
  try {
    const loaded = await loadSettings();
    settings.value = loaded;
    systemForm.app_name = loaded.app_name ?? "";
    systemForm.session_hours = Number(loaded.session_hours ?? 8) || 8;
    systemForm.login_notice = loaded.login_notice ?? "";
    systemForm.app_logo = loaded.app_logo ?? "";
    systemForm.export_logo_enabled = String(loaded.export_logo_enabled ?? "0") === "1";
    systemForm.group_name = loaded.group_name ?? "";
    systemForm.module_datacenter_enabled = String(loaded.module_datacenter_enabled ?? "1") === "1";
    systemForm.module_inspection_enabled = String(loaded.module_inspection_enabled ?? "1") === "1";
    backupForm.backup_enabled = loaded.backup_enabled ?? "0";
    backupForm.backup_time = loaded.backup_time ?? "02:00";
    backupForm.backup_retention_days = loaded.backup_retention_days ?? "30";
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "系统设置加载失败。");
  }
  if (canViewBackups.value) {
    try {
      backups.value = await loadBackups();
    } catch {
      backups.value = [];
    }
  }
  if (canViewUsers.value || canViewAccess.value) {
    try {
      users.value = await loadUsers();
    } catch {
      users.value = [];
    }
  }
  if (canViewAccess.value) {
    await loadAccess();
  }
  if (!tabs.value.some((item) => item.key === activeTab.value)) {
    activeTab.value = tabs.value[0]?.key ?? "security";
  }
  await loadNavLinks();
  loading.value = false;
}

async function loadAccess(): Promise<void> {
  try {
    const access = await loadAccessControl();
    modules.value = access.modules;
    roles.value = access.roles;
    accessUsers.value = access.users;
    roleForm.rows = emptyPermissionRows();
    if (!accessTargetId.value) {
      accessTargetId.value = String(
        accessTargetType.value === "role" ? access.roles[0]?.id ?? "" : access.users[0]?.id ?? "",
      );
    }
    await loadPermissionRows();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "权限数据加载失败。");
  }
}

async function loadPermissionRows(): Promise<void> {
  if (!accessTargetId.value) {
    permissionRows.value = emptyPermissionRows();
    return;
  }
  try {
    const entries = await loadTargetPermissions(accessTargetType.value, accessTargetId.value);
    permissionRows.value = buildPermissionRows(modules.value, entries);
  } catch (error) {
    permissionRows.value = emptyPermissionRows();
    ElMessage.error(error instanceof Error ? error.message : "权限明细加载失败。");
  }
}

function onAccessTargetTypeChange(): void {
  accessTargetId.value = String(
    accessTargetType.value === "role" ? roles.value[0]?.id ?? "" : accessUsers.value[0]?.id ?? "",
  );
}

function toggleAllPermissions(rows: PermissionRow[], checked: boolean): void {
  rows.forEach((row) => {
    PERMISSION_ACTIONS.forEach(({ action }) => {
      row.actions[action] = checked;
    });
    if (checked && row.scope === "none") row.scope = "organization";
  });
}

/** Logo 只收 PNG，读到 data URI 存进设置；后端保存时会再校验一次。 */
async function onLogoChange(file: { raw?: File }): Promise<void> {
  const raw = file.raw;
  if (!raw) return;
  if (!raw.name.toLowerCase().endsWith(".png") || raw.type !== "image/png") {
    ElMessage.warning("请选择 PNG 图片。");
    return;
  }
  if (raw.size > 300 * 1024) {
    ElMessage.warning("图片请控制在 300KB 以内（建议高度 80 像素左右）。");
    return;
  }
  const bytes = new Uint8Array(await raw.arrayBuffer());
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  systemForm.app_logo = `data:image/png;base64,${window.btoa(binary)}`;
}

async function submitSystemSettings(): Promise<void> {
  if (!canUpdateSettings.value) {
    ElMessage.warning("只有具备系统设置修改权限的账号可以保存。");
    return;
  }
  if (!systemForm.app_name.trim()) {
    ElMessage.warning("系统名称不能为空。");
    return;
  }
  const hours = Number(systemForm.session_hours);
  if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
    ElMessage.warning("登录会话时长必须在 1-168 小时之间。");
    return;
  }
  saving.value = true;
  try {
    const saved = await saveSettings({
      app_name: systemForm.app_name.trim(),
      login_notice: systemForm.login_notice,
      session_hours: String(hours),
      app_logo: systemForm.app_logo,
      export_logo_enabled: systemForm.export_logo_enabled ? "1" : "0",
      group_name: systemForm.group_name.trim(),
      module_datacenter_enabled: systemForm.module_datacenter_enabled ? "1" : "0",
      module_inspection_enabled: systemForm.module_inspection_enabled ? "1" : "0",
    });
    settings.value = { ...settings.value, ...saved };
    // 左上角的系统名与图标立刻跟着变，不用重新登录
    session.appName = String(saved.app_name ?? systemForm.app_name.trim());
    session.appLogo = String(saved.app_logo ?? systemForm.app_logo);
    session.groupName = String(saved.group_name ?? systemForm.group_name.trim());
    session.moduleDatacenterEnabled =
      String(saved.module_datacenter_enabled ?? "1") === "1";
    session.moduleInspectionEnabled =
      String(saved.module_inspection_enabled ?? "1") === "1";
    ElMessage.success("系统设置已保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存系统设置失败。");
  } finally {
    saving.value = false;
  }
}

async function submitPassword(): Promise<void> {
  if (!passwordForm.currentPassword || !passwordForm.newPassword) {
    ElMessage.warning("请填写当前密码与新密码。");
    return;
  }
  if (passwordForm.newPassword.length < 8) {
    ElMessage.warning("新密码至少 8 位。");
    return;
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    ElMessage.warning("两次输入的新密码不一致。");
    return;
  }
  saving.value = true;
  try {
    await changePassword({
      currentPassword: passwordForm.currentPassword,
      newPassword: passwordForm.newPassword,
      confirmPassword: passwordForm.confirmPassword,
    });
    passwordForm.currentPassword = "";
    passwordForm.newPassword = "";
    passwordForm.confirmPassword = "";
    ElMessage.success("密码已修改。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "修改密码失败。");
  } finally {
    saving.value = false;
  }
}

async function submitBackupSchedule(): Promise<void> {
  saving.value = true;
  try {
    const saved = await saveSettings({
      backup_enabled: backupEnabled.value ? "1" : "0",
      backup_time: backupForm.backup_time,
      backup_retention_days: backupForm.backup_retention_days,
    });
    settings.value = { ...settings.value, ...saved };
    ElMessage.success("数据库备份计划已保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存备份计划失败。");
  } finally {
    saving.value = false;
  }
}

async function submitCreateBackup(): Promise<void> {
  saving.value = true;
  try {
    const created = await createBackup();
    backups.value = await loadBackups();
    ElMessage.success(`数据库备份已创建：${created?.fileName ?? ""}`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建数据库备份失败。");
  } finally {
    saving.value = false;
  }
}

function openBackupDownload(row: BackupRow): void {
  if (!row.fileAvailable) {
    ElMessage.warning("该备份文件当前不可下载。");
    return;
  }
  backupDownloadTarget.value = row;
  backupDownloadPassword.value = "";
  backupDownloadVisible.value = true;
}

async function submitBackupDownload(): Promise<void> {
  const target = backupDownloadTarget.value;
  if (!target) return;
  if (!backupDownloadPassword.value) {
    ElMessage.warning("请输入当前登录账号密码。");
    return;
  }
  saving.value = true;
  try {
    const filename = await downloadBackup(target.id, backupDownloadPassword.value);
    backupDownloadVisible.value = false;
    ElMessage.success(`已开始下载：${filename}`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "下载数据库备份失败。");
  } finally {
    saving.value = false;
  }
}

async function openUserDialog(row?: UserRow): Promise<void> {
  userEditingId.value = row?.id ?? "";
  userForm.username = row?.username ?? "";
  userForm.displayName = row?.displayName ?? "";
  userForm.role = row?.role ?? roles.value[0]?.code ?? "operator";
  userForm.employeeId = row?.employeeId ?? "";
  userForm.isActive = row?.isActive ?? true;
  userForm.password = "";
  if (!employees.value.length) {
    try {
      employees.value = (await loadEmployeesData()).employees;
    } catch {
      employees.value = [];
    }
  }
  userDialogVisible.value = true;
}

async function submitUser(): Promise<void> {
  const username = userForm.username.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$/.test(username)) {
    ElMessage.warning("登录账号需使用 3-64 位字母、数字、点、下划线或短横线。");
    return;
  }
  if (!userForm.displayName.trim()) {
    ElMessage.warning("显示名称必填。");
    return;
  }
  if (!userEditingId.value && !userForm.password) {
    ElMessage.warning("新账号必须填写初始密码。");
    return;
  }
  saving.value = true;
  try {
    const payload = {
      username,
      displayName: userForm.displayName.trim(),
      role: userForm.role,
      employeeId: userForm.employeeId,
      isActive: userForm.isActive,
      ...(userForm.password.trim() ? { password: userForm.password } : {}),
    };
    await saveUser(payload, userEditingId.value);
    users.value = await loadUsers();
    userDialogVisible.value = false;
    ElMessage.success(userEditingId.value ? "账号已更新。" : "账号已创建。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存账号失败。");
  } finally {
    saving.value = false;
  }
}

function employeeOptions(): Array<{ value: string; label: string }> {
  return [{ value: "", label: "仅超级管理员可不绑定人员" }].concat(
    employees.value
      .filter((item) => !["left", "shared"].includes(item.status))
      .map((item) => ({
        value: item.id,
        label: `${item.name} · ${item.department || item.employeeNo || "未分配部门"}`,
      })),
  );
}

async function submitPermissions(): Promise<void> {
  if (!accessTargetId.value) {
    ElMessage.warning("请先选择角色或用户。");
    return;
  }
  saving.value = true;
  try {
    await saveTargetPermissions(
      accessTargetType.value,
      accessTargetId.value,
      toPermissionEntries(permissionRows.value),
    );
    ElMessage.success("权限已保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "权限保存失败。");
  } finally {
    saving.value = false;
  }
}

async function submitRole(): Promise<void> {
  if (!/^[a-z][a-z0-9._-]{2,63}$/.test(roleForm.code.trim())) {
    ElMessage.warning("角色编码需使用 3-64 位小写字母、数字、点、下划线或短横线。");
    return;
  }
  if (!roleForm.name.trim()) {
    ElMessage.warning("角色名称必填。");
    return;
  }
  saving.value = true;
  try {
    const created = await createRole({
      code: roleForm.code.trim(),
      name: roleForm.name.trim(),
      category: roleForm.category,
      isSuperAdmin: roleForm.isSuperAdmin,
      permissions: toPermissionEntries(roleForm.rows),
    });
    roleForm.code = "";
    roleForm.name = "";
    roleForm.category = "custom";
    roleForm.isSuperAdmin = false;
    await loadAccess();
    if (created.id) {
      accessTargetType.value = "role";
      accessTargetId.value = created.id;
      await loadPermissionRows();
    }
    ElMessage.success("角色已创建。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建角色失败。");
  } finally {
    saving.value = false;
  }
}

function openRoleEdit(): void {
  if (accessTargetType.value !== "role") return;
  const role = roles.value.find((item) => String(item.id) === String(accessTargetId.value));
  if (!role) {
    ElMessage.warning("请先在「目标对象」里选择一个角色。");
    return;
  }
  roleEditDialog.id = String(role.id);
  roleEditDialog.name = role.name ?? "";
  roleEditDialog.category = role.category ?? "custom";
  roleEditDialog.isSuperAdmin = Boolean(role.isSuperAdmin);
  roleEditDialog.visible = true;
}

async function submitRoleEdit(): Promise<void> {
  if (!roleEditDialog.name.trim()) {
    ElMessage.warning("角色名称必填。");
    return;
  }
  saving.value = true;
  try {
    await updateRole(roleEditDialog.id, {
      name: roleEditDialog.name.trim(),
      category: roleEditDialog.category,
      isSuperAdmin: roleEditDialog.isSuperAdmin,
    });
    roleEditDialog.visible = false;
    await loadAccess();
    ElMessage.success("角色已更新。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新角色失败。");
  } finally {
    saving.value = false;
  }
}

function updateStatusLabel(status: string | undefined): string {
  if (status === "update_available") return "发现可用版本";
  if (status === "queued") return "手动更新已排队";
  if (status === "running") return "更新正在执行";
  if (status === "up_to_date") return "当前已是最新版本";
  if (status === "no_releases") return "暂无已发布版本";
  if (status === "no_release_available") return "暂无更高发布版本";
  return "尚未检查";
}

function updateStatusDetail(status: string | undefined): string {
  if (status === "update_available") return "请选择版本号更高的已发布版本，再手动执行更新。推送不会自动部署。";
  if (status === "queued") return "服务器将按所选发布版本构建应用，完成后请刷新页面。";
  if (status === "running") return "应用服务可能会短暂重启，请稍后刷新页面。";
  if (status === "up_to_date") return "当前部署版本与所选项目地址一致。";
  if (status === "no_releases") return "所选项目地址中还没有 vMAJOR.MINOR.PATCH 格式的已发布版本标签。";
  if (status === "no_release_available") return "当前部署版本没有更高的已发布版本。";
  return "点击按钮读取项目地址中已发布的语义化版本标签。";
}

function effectiveUpdateRepositoryUrl(): string {
  return updateSource.value === "github" ? GITHUB_UPDATE_REPOSITORY_URL : updateRepositoryUrl.value.trim();
}

async function submitUpdateCheck(): Promise<void> {
  if (!canUpdate.value) {
    ElMessage.warning("当前账号没有系统更新权限。");
    return;
  }
  if (updateSource.value === "custom" && !updateRepositoryUrl.value.trim()) {
    ElMessage.warning("请填写自定义项目地址。");
    return;
  }
  updateChecking.value = true;
  try {
    const repositoryUrl = effectiveUpdateRepositoryUrl();
    const payload = await checkForUpdate({
      repositoryUrl,
      releaseChannel: updateReleaseChannel.value,
      persistRepositoryUrl: updateSource.value === "custom",
    });
    updateStatus.value = payload;
    updateReleaseChannel.value = payload.releaseChannel || updateReleaseChannel.value;
    const first = (payload.availableVersions ?? []).find(
      (item) => item.isSelectable !== false && !item.isCurrent,
    );
    updateSelectedSha.value = payload.status === "update_available" ? first?.sha ?? "" : "";
    if (payload.status === "up_to_date") {
      ElMessage.success(`当前已是最新版本 ${payload.currentVersion ?? payload.currentShortSha ?? ""}`);
    } else if (payload.status === "update_available") {
      ElMessage.success(`发现可用版本 ${payload.latestVersion ?? ""}，请选择后手动更新。`);
    } else if (payload.status === "no_releases") {
      ElMessage.warning("检查完成：项目地址中暂无已发布版本。");
    } else if (payload.status === "no_release_available") {
      ElMessage.success("检查完成：当前没有版本号更高的已发布版本。");
    } else {
      ElMessage.success("版本列表已更新。");
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "检查版本更新失败。");
  } finally {
    updateChecking.value = false;
  }
}

async function submitUpdateApply(): Promise<void> {
  const target = selectedVersion.value;
  if (!target) {
    ElMessage.warning("请先检查并选择一个目标版本。");
    return;
  }
  const label = target.version || target.tag || target.shortSha || target.sha.slice(0, 7);
  const confirmed = await confirmAction(`确定更新到 ${label}：${target.subject ?? ""} 吗？`, {
    title: "执行版本更新",
    confirmText: "更新",
  });
  if (!confirmed) return;
  updateApplying.value = true;
  try {
    const payload = await applyUpdate({
      targetSha: target.sha,
      repositoryUrl: effectiveUpdateRepositoryUrl(),
      releaseChannel: updateReleaseChannel.value,
    });
    updateStatus.value = payload;
    updateSelectedSha.value = payload.targetSha || target.sha;
    const targetSha = String(payload.targetSha || target.sha);
    if (payload.status === "queued" || payload.status === "running") {
      startUpdatePolling(targetSha);
      ElMessage.success(`版本 ${payload.targetVersion ?? label} 已进入更新队列，正在显示进度。`);
    } else if (payload.status === "up_to_date") {
      markUpdateDone();
      ElMessage.success("目标版本已经部署完成。");
    } else {
      startUpdatePolling(targetSha);
      ElMessage.success("版本更新请求已提交。");
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "执行版本更新失败。");
  } finally {
    updateApplying.value = false;
  }
}

// ---- 更新执行进度：点击更新后轮询部署状态，完成后提示刷新页面 ----
const updateProgress = ref<UpdateProgress | null>(null);
const updatePolling = ref(false);
const updateReloadReady = ref(false);
const updateTargetSha = ref("");
const updateStartedAt = ref(0);
const updateElapsed = ref(0);
let updatePollTimer: number | null = null;
let updateElapsedTimer: number | null = null;

const updateProgressPercent = computed(() => {
  const value = Number(updateProgress.value?.progress ?? 0);
  return Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));
});
const updateProgressPhase = computed(() => {
  if (updateReloadReady.value) return "completed";
  const phase = String(updateProgress.value?.phase ?? "").trim();
  return phase || (updateApplying.value ? "queued" : "idle");
});
const updateProgressText = computed(() => {
  if (updateReloadReady.value) return "更新完成，刷新页面即可使用新版本。";
  return String(updateProgress.value?.message ?? "").trim() || "正在获取更新进度…";
});
const updateElapsedText = computed(() => {
  if (!updateStartedAt.value) return "";
  const seconds = Math.max(0, updateElapsed.value);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `已用时 ${minutes} 分 ${rest} 秒` : `已用时 ${rest} 秒`;
});

function stopUpdatePolling(): void {
  if (updatePollTimer !== null) {
    window.clearInterval(updatePollTimer);
    updatePollTimer = null;
  }
  if (updateElapsedTimer !== null) {
    window.clearInterval(updateElapsedTimer);
    updateElapsedTimer = null;
  }
  updatePolling.value = false;
}

function markUpdateDone(): void {
  stopUpdatePolling();
  updateReloadReady.value = true;
  // 让「检查版本 / 更新」按钮重新可用，避免状态停在 queued 一直灰着。
  if (updateStatus.value) {
    updateStatus.value = { ...updateStatus.value, status: "up_to_date" };
  }
  updateProgress.value = {
    ...(updateProgress.value ?? {}),
    phase: "completed",
    progress: 100,
    message: "更新完成，刷新页面即可使用新版本。",
  };
}

async function pollUpdateProgress(): Promise<void> {
  try {
    const payload = await getUpdateProgress();
    updateProgress.value = payload;
    if (String(payload.phase ?? "") === "completed") {
      markUpdateDone();
      return;
    }
    const target = updateTargetSha.value.toLowerCase();
    const current = String(payload.currentSha ?? "").toLowerCase();
    if (target && current && target === current) {
      markUpdateDone();
    }
  } catch {
    // 部署过程中服务会短暂重启，这一两轮轮询失败属于正常现象，继续等待。
  }
}

function startUpdatePolling(targetSha: string): void {
  stopUpdatePolling();
  updateTargetSha.value = targetSha || "";
  updateReloadReady.value = false;
  updateProgress.value = { phase: "queued", progress: 8, message: "已提交更新请求，正在排队执行。" };
  updateStartedAt.value = Date.now();
  updateElapsed.value = 0;
  updatePolling.value = true;
  updateElapsedTimer = window.setInterval(() => {
    updateElapsed.value = Math.floor((Date.now() - updateStartedAt.value) / 1000);
  }, 1000);
  void pollUpdateProgress();
  updatePollTimer = window.setInterval(() => {
    void pollUpdateProgress();
  }, 3000);
}

function reloadPage(): void {
  window.location.reload();
}

onBeforeUnmount(stopUpdatePolling);

async function loadNavLinks(): Promise<void> {
  try {
    navLinks.value = await listAllNavLinks();
  } catch {
    navLinks.value = [];
  }
}

function openNavLinkDialog(link: NavLink | null): void {
  navLinkDialog.id = link?.id ?? "";
  navLinkDialog.title = link?.title ?? "";
  navLinkDialog.url = link?.url ?? "";
  navLinkDialog.icon = link?.icon ?? "";
  navLinkDialog.sortOrder = link?.sortOrder ?? 1000;
  navLinkDialog.openMode = link?.openMode ?? "new_tab";
  navLinkDialog.isActive = link?.isActive !== false;
  navLinkDialog.visible = true;
}

async function submitNavLink(): Promise<void> {
  if (!navLinkDialog.title.trim() || !navLinkDialog.url.trim()) {
    ElMessage.warning("外链名称与地址不能为空。");
    return;
  }
  if (!/^https?:\/\//i.test(navLinkDialog.url.trim())) {
    ElMessage.warning("外链地址必须以 http:// 或 https:// 开头。");
    return;
  }
  navLinkSaving.value = true;
  try {
    await saveNavLink(
      {
        title: navLinkDialog.title.trim(),
        url: navLinkDialog.url.trim(),
        icon: navLinkDialog.icon.trim(),
        sortOrder: navLinkDialog.sortOrder,
        openMode: navLinkDialog.openMode,
        isActive: navLinkDialog.isActive,
      },
      navLinkDialog.id,
    );
    navLinkDialog.visible = false;
    ElMessage.success("外链应用已保存。");
    await loadNavLinks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存外链应用失败。");
  } finally {
    navLinkSaving.value = false;
  }
}

async function removeNavLink(link: NavLink): Promise<void> {
  const ok = await confirmAction(`确定删除外链「${link.title}」吗？`, {
    title: "删除外链",
    danger: true,
  });
  if (!ok) return;
  try {
    await deleteNavLink(link.id);
    ElMessage.success("外链应用已删除。");
    await loadNavLinks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除外链应用失败。");
  }
}

onMounted(async () => {
  const requestedTab = String(route.query.tab ?? "");
  if (requestedTab) activeTab.value = requestedTab;
  await loadMeta();
  try {
    health.value = await api<{ ok: boolean; requiredTables: number; requiredTableCount: number }>(
      "/api/health",
    );
  } catch (error) {
    healthError.value = error instanceof Error ? error.message : "健康检查失败。";
  }
  await loadAll();
});
</script>

<template>
  <PageHeader
    title="设置"
    description="外观主题、系统信息、系统参数、备份、账号与权限、同步与版本更新的统一下发入口"
  />

  <DataPanel class="oa-panel-gap" title="外观主题" :hint="`当前主题色 ${themeColor}`">
    <div class="oa-flex-row">
      <button
        v-for="preset in THEME_COLOR_PRESETS"
        :key="preset.key"
        type="button"
        :title="preset.label"
        :style="{
          width: '34px',
          height: '34px',
          borderRadius: '8px',
          border:
            themeColor === preset.color
              ? '2px solid var(--el-text-color-primary)'
              : '1px solid var(--el-border-color)',
          background: preset.color,
          cursor: 'pointer',
          color: 'var(--el-color-white)',
          lineHeight: '1',
        }"
        @click="pickThemeColor(preset.color)"
      >
        <span v-if="themeColor === preset.color">✓</span>
      </button>
      <el-color-picker
        :model-value="themeColor"
        :predefine="THEME_COLOR_PRESETS.map((item) => item.color)"
        @change="(value: string | null) => pickThemeColor(value || DEFAULT_THEME_COLOR)"
      />
      <el-button @click="restoreDefaultTheme">恢复默认</el-button>
    </div>
  </DataPanel>

  <DataPanel class="oa-panel-gap" title="系统信息">
    <template #actions>
      <el-tag type="success" effect="dark">当前系统版本 v{{ version }}</el-tag>
    </template>
    <el-descriptions :column="2" border>
      <el-descriptions-item label="当前系统版本">
        <strong>v{{ version }}</strong>
      </el-descriptions-item>
      <el-descriptions-item label="前端构建版本">v{{ frontendVersion }}</el-descriptions-item>
      <el-descriptions-item label="前端构建时间">{{ formatTime(frontendBuildTime) }}</el-descriptions-item>
      <el-descriptions-item label="服务端时间">
        {{ formatTime(session.meta?.serverTime) }} {{ session.meta?.timeZone || "" }}
      </el-descriptions-item>
      <el-descriptions-item label="登录账号">
        {{ session.user?.displayName || session.user?.username || "—" }}（{{ roleLabel }}）
      </el-descriptions-item>
      <el-descriptions-item label="数据库">
        <template v-if="health">
          {{ health.ok ? "连接正常" : "异常" }} ·
          {{ health.requiredTables }}/{{ health.requiredTableCount }} 张必需表
        </template>
        <template v-else-if="healthError">{{ healthError }}</template>
        <template v-else>检测中…</template>
      </el-descriptions-item>
    </el-descriptions>
  </DataPanel>

  <DataPanel class="oa-panel-gap" title="系统设置">
    <el-tabs v-model="activeTab" v-loading="loading">
      <el-tab-pane
        v-for="tab in tabs"
        :key="tab.key"
        :label="tab.label"
        :name="tab.key"
      >
        <template v-if="tab.key === 'system'">
          <el-form label-position="top" style="max-width: 620px">
            <el-form-item label="系统名称" required>
              <el-input
                v-model="systemForm.app_name"
                :disabled="!canUpdateSettings"
                placeholder="显示在登录页、左上角和导出文件里"
              />
            </el-form-item>
            <el-form-item label="公司 Logo">
              <div class="oa-flex-row">
                <span class="oa-logo-preview">
                  <img v-if="systemForm.app_logo" :src="systemForm.app_logo" alt="Logo 预览" />
                  <span v-else class="oa-muted">未上传</span>
                </span>
                <el-upload
                  :auto-upload="false"
                  :show-file-list="false"
                  :disabled="!canUpdateSettings"
                  accept="image/png"
                  :on-change="onLogoChange"
                >
                  <el-button :disabled="!canUpdateSettings">选择 PNG</el-button>
                </el-upload>
                <el-button
                  v-if="systemForm.app_logo"
                  :disabled="!canUpdateSettings"
                  @click="systemForm.app_logo = ''"
                >
                  移除
                </el-button>
              </div>
              <div class="oa-hint">
                只支持 PNG，300KB 以内（建议横向、高度 80 像素左右）。上传后替换左上角的 OM 图标，
                同时用于登录页。
              </div>
            </el-form-item>
            <el-form-item label="导出时附带 Logo">
              <el-switch
                v-model="systemForm.export_logo_enabled"
                :disabled="!canUpdateSettings || !systemForm.app_logo"
                active-text="导出的 Excel 左上角带上公司 Logo"
                inactive-text="导出不带 Logo"
              />
            </el-form-item>
            <el-form-item label="无操作自动退出（小时）" required>
              <el-input-number
                v-model="systemForm.session_hours"
                :min="1"
                :max="168"
                :disabled="!canUpdateSettings"
                class="oa-full-width"
              />
              <div class="oa-hint">
                连续无操作超过这个时长就结束会话，页面会退回登录页；有操作时自动顺延。
              </div>
            </el-form-item>
            <el-form-item label="集团名称">
              <el-input
                v-model="systemForm.group_name"
                :disabled="!canUpdateSettings"
                placeholder="集团名称，显示在组织架构树与左上角"
              />
            </el-form-item>
            <el-form-item label="机房管理">
              <el-switch
                v-model="systemForm.module_datacenter_enabled"
                :disabled="!canUpdateSettings"
                active-text="开启"
                inactive-text="关闭"
              />
              <div class="oa-hint">关闭后网络设备/服务器、机柜视图、设备面板与网络拓扑整组隐藏。</div>
            </el-form-item>
            <el-form-item label="巡检管理">
              <el-switch
                v-model="systemForm.module_inspection_enabled"
                :disabled="!canUpdateSettings"
                active-text="开启"
                inactive-text="关闭"
              />
              <div class="oa-hint">关闭后巡检中心与会议室整组隐藏。</div>
            </el-form-item>
            <el-form-item label="登录页提示语">
              <el-input
                v-model="systemForm.login_notice"
                type="textarea"
                :rows="4"
                :disabled="!canUpdateSettings"
                placeholder="例如：请使用公司账号登录"
              />
            </el-form-item>
            <el-button
              type="primary"
              :loading="saving"
              :disabled="!canUpdateSettings"
              @click="submitSystemSettings"
            >
              保存系统设置
            </el-button>
            <span
              v-if="!canUpdateSettings"
              class="oa-hint oa-ml-3"
            >
              当前账号只能查看系统级设置。
            </span>
          </el-form>
        </template>

        <template v-else-if="tab.key === 'security'">
          <el-form label-position="top" style="max-width: 620px">
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="密码至少 8 位，修改后当前会话仍保持有效，其他会话会退出登录。"
              class="oa-mb-3"
            />
            <el-form-item label="当前密码" required>
              <el-input v-model="passwordForm.currentPassword" type="password" show-password />
            </el-form-item>
            <el-row :gutter="12">
              <el-col :xs="24" :sm="12">
                <el-form-item label="新密码" required>
                  <el-input v-model="passwordForm.newPassword" type="password" show-password />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="确认新密码" required>
                  <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
                </el-form-item>
              </el-col>
            </el-row>
            <el-button type="primary" :loading="saving" @click="submitPassword">保存新密码</el-button>
          </el-form>
        </template>

        <template v-else-if="tab.key === 'backup'">
          <el-form label-position="top" style="max-width: 720px">
            <el-form-item label="自动备份">
              <el-switch
                v-model="backupForm.backup_enabled"
                active-value="1"
                inactive-value="0"
                active-text="启用每日自动备份"
              />
            </el-form-item>
            <el-row :gutter="12">
              <el-col :xs="24" :sm="12">
                <el-form-item label="每日备份时间">
                  <el-input v-model="backupForm.backup_time" placeholder="02:00" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="保留天数">
                  <el-input v-model="backupForm.backup_retention_days" placeholder="0 表示不自动清理" />
                </el-form-item>
              </el-col>
            </el-row>
            <div class="oa-flex-row">
              <el-button type="primary" :loading="saving" @click="submitBackupSchedule">
                保存备份计划
              </el-button>
              <el-button :loading="saving" @click="submitCreateBackup">立即备份</el-button>
            </div>
          </el-form>
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="下载任意备份时，系统会要求再次输入当前登录账号密码；备份文件不会暴露在网页静态目录中。"
            class="oa-my-3"
          />
          <el-table :data="backups" size="small" border empty-text="尚无数据库备份记录">
            <el-table-column prop="createdAt" label="创建时间" width="170" />
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                {{ row.backupType === "scheduled" ? "定时备份" : "手动备份" }}
              </template>
            </el-table-column>
            <el-table-column prop="fileName" label="备份文件" min-width="220" show-overflow-tooltip />
            <el-table-column label="大小" width="110">
              <template #default="{ row }">{{ formatFileSize(row.fileSize) }}</template>
            </el-table-column>
            <el-table-column prop="requestedByName" label="创建人" width="130" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.fileAvailable ? 'success' : 'info'">
                  {{ backupStatusLabel(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="!row.fileAvailable" @click="openBackupDownload(row)">
                  下载
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template v-else-if="tab.key === 'accounts'">
          <div class="oa-flex-between oa-mb-2">
            <span class="oa-hint">
              共 {{ users.length }} 个账号，创建账号时填写登录账号和显示名称，再分配角色。
            </span>
            <span class="oa-flex-row">
              <el-button @click="userImportDialog = true">导入 Excel</el-button>
              <el-button type="primary" @click="openUserDialog()">＋ 新增账号</el-button>
            </span>
          </div>
          <el-table :data="users" size="small" border empty-text="暂无账号记录">
            <el-table-column label="账号" min-width="160">
              <template #default="{ row }">
                <strong>{{ row.username }}</strong>
                <el-tag
                  v-if="String(row.id) === String(session.user?.id)"
                  size="small"
                  type="success"
                  class="oa-ml-1"
                >
                  当前账号
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="displayName" label="显示名称" width="130" />
            <el-table-column label="绑定人员" min-width="170">
              <template #default="{ row }">
                {{ row.employeeName ? `${row.employeeName} · ${row.department || row.orgName || ""}` : "未绑定" }}
              </template>
            </el-table-column>
            <el-table-column label="角色" width="130">
              <template #default="{ row }">
                {{ roles.find((item) => item.code === row.role)?.name || row.role }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.isActive ? 'success' : 'info'">
                  {{ row.isActive ? "启用" : "停用" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最后登录" width="170">
              <template #default="{ row }">{{ formatTime(row.lastLoginAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openUserDialog(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template v-else-if="tab.key === 'access'">
          <el-row :gutter="12">
            <el-col :xs="24" :md="14">
              <el-form label-position="top">
                <el-row :gutter="12">
                  <el-col :xs="12" :sm="8">
                    <el-form-item label="配置对象">
                      <el-select v-model="accessTargetType" class="oa-full-width" @change="onAccessTargetTypeChange">
                        <el-option label="角色" value="role" />
                        <el-option label="用户覆盖" value="user" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="12" :sm="10">
                    <el-form-item label="目标对象">
                      <el-select
                        v-model="accessTargetId"
                        filterable
                        class="oa-full-width"
                        @change="loadPermissionRows"
                      >
                        <el-option
                          v-for="option in accessTargetOptions"
                          :key="option.value"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form>
              <div class="oa-flex-row oa-mb-2">
                <el-button size="small" @click="toggleAllPermissions(permissionRows, true)">
                  全选权限
                </el-button>
                <el-button size="small" @click="toggleAllPermissions(permissionRows, false)">
                  清空权限
                </el-button>
                <el-button
                  v-if="accessTargetType === 'role'"
                  size="small"
                  :disabled="!canUpdateAccess || !accessTargetId"
                  @click="openRoleEdit"
                >
                  编辑角色
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  :loading="saving"
                  :disabled="!canUpdateAccess || !accessTargetId"
                  @click="submitPermissions"
                >
                  保存权限
                </el-button>
              </div>
              <el-table :data="permissionRows" size="small" border max-height="520">
                <el-table-column prop="label" label="模块" min-width="150" />
                <el-table-column
                  v-for="action in PERMISSION_ACTIONS"
                  :key="action.action"
                  :label="action.label"
                  width="70"
                  align="center"
                >
                  <template #default="{ row }">
                    <el-checkbox v-model="row.actions[action.action]" :disabled="!canUpdateAccess" />
                  </template>
                </el-table-column>
                <el-table-column label="数据范围" width="180">
                  <template #default="{ row }">
                    <el-select v-model="row.scope" size="small" :disabled="!canUpdateAccess" class="oa-full-width">
                      <el-option
                        v-for="(label, value) in DATA_SCOPES"
                        :key="value"
                        :label="label"
                        :value="value"
                      />
                    </el-select>
                  </template>
                </el-table-column>
              </el-table>
            </el-col>
            <el-col :xs="24" :md="10">
              <el-card shadow="never">
                <template #header><strong>创建角色</strong></template>
                <el-form label-position="top">
                  <el-form-item label="角色编码" required>
                    <el-input v-model="roleForm.code" placeholder="小写字母、数字、点、下划线或连字符" />
                  </el-form-item>
                  <el-form-item label="角色名称" required>
                    <el-input v-model="roleForm.name" placeholder="例如：部门资产管理员" />
                  </el-form-item>
                  <el-form-item label="角色类别">
                    <el-select v-model="roleForm.category" class="oa-full-width">
                      <el-option
                        v-for="(label, value) in ROLE_CATEGORIES"
                        :key="value"
                        :label="label"
                        :value="value"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="超级管理员">
                    <el-switch v-model="roleForm.isSuperAdmin" />
                  </el-form-item>
                </el-form>
                <div class="oa-flex-row oa-mb-2">
                  <el-button size="small" @click="toggleAllPermissions(roleForm.rows, true)">全选</el-button>
                  <el-button size="small" @click="toggleAllPermissions(roleForm.rows, false)">清空</el-button>
                </div>
                <el-table :data="roleForm.rows" size="small" border max-height="300">
                  <el-table-column prop="label" label="模块" min-width="120" />
                  <el-table-column label="查看" width="60" align="center">
                    <template #default="{ row }">
                      <el-checkbox v-model="row.actions.view" />
                    </template>
                  </el-table-column>
                  <el-table-column label="新增" width="60" align="center">
                    <template #default="{ row }">
                      <el-checkbox v-model="row.actions.create" />
                    </template>
                  </el-table-column>
                  <el-table-column label="修改" width="60" align="center">
                    <template #default="{ row }">
                      <el-checkbox v-model="row.actions.update" />
                    </template>
                  </el-table-column>
                  <el-table-column label="删除" width="60" align="center">
                    <template #default="{ row }">
                      <el-checkbox v-model="row.actions.delete" />
                    </template>
                  </el-table-column>
                </el-table>
                <el-button
                  type="primary"
                  :loading="saving"
                  :disabled="!canUpdateAccess"
                  style="margin-top: 10px; width: 100%"
                  @click="submitRole"
                >
                  创建角色
                </el-button>
              </el-card>
            </el-col>
          </el-row>
        </template>

        <template v-else-if="tab.key === 'updates'">
          <el-form label-position="top" style="max-width: 760px">
            <el-form-item label="更新来源">
              <el-select v-model="updateSource" :disabled="updateBusy" class="oa-full-width">
                <el-option
                  v-for="(label, value) in UPDATE_SOURCES"
                  :key="value"
                  :label="label"
                  :value="value"
                />
              </el-select>
            </el-form-item>
            <el-form-item v-if="updateSource === 'custom'" label="自定义项目地址">
              <el-input
                v-model="updateRepositoryUrl"
                :disabled="updateBusy"
                placeholder="填写 GitHub 或内网 Git 仓库地址"
              />
            </el-form-item>
            <el-alert
              v-else
              type="info"
              :closable="false"
              show-icon
              :title="`内置地址：${GITHUB_UPDATE_REPOSITORY_URL}`"
              class="oa-mb-3"
            />
            <el-descriptions :column="2" border class="oa-mb-3">
              <el-descriptions-item label="当前版本">{{ currentVersionText }}</el-descriptions-item>
              <el-descriptions-item label="来源最新发布版本">{{ latestVersionText }}</el-descriptions-item>
            </el-descriptions>
            <el-form-item label="目标版本">
              <el-select
                v-model="updateSelectedSha"
                :disabled="updateBusy || !selectableVersions.length"
                placeholder="请选择要更新的版本"
                class="oa-full-width"
              >
                <el-option
                  v-for="item in selectableVersions"
                  :key="item.sha"
                  :label="`${item.version || item.tag || '未知版本'} · ${item.subject || '无提交说明'} · ${(item.shortSha || item.sha).slice(0, 7)}${item.isLatest ? '（最新）' : ''}`"
                  :value="item.sha"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="版本更新说明">
              <el-input
                :model-value="releaseNotes || '该版本暂无匹配的 VERSION_NOTES.md 说明。'"
                type="textarea"
                :rows="8"
                readonly
              />
            </el-form-item>
            <el-alert
              type="warning"
              :closable="false"
              show-icon
              :title="`${updateStatusLabel(updateStatus?.status)}：${updateStatusDetail(updateStatus?.status)}`"
              class="oa-mb-3"
            />
            <div class="oa-flex-row">
              <el-button :loading="updateChecking" :disabled="updateBusy" @click="submitUpdateCheck">
                {{ updateSource === "github" ? "从 GitHub 检查更新" : "检查版本" }}
              </el-button>
              <el-button
                type="primary"
                :loading="updateApplying"
                :disabled="updateBusy || !selectedVersion"
                @click="submitUpdateApply"
              >
                更新到所选版本
              </el-button>
            </div>
            <template v-if="updatePolling || updateReloadReady">
              <el-alert
                :type="updateReloadReady ? 'success' : 'info'"
                :closable="false"
                show-icon
                :title="updateProgressText"
                class="oa-mb-3"
              />
              <el-progress
                :percentage="updateProgressPercent"
                :status="updateReloadReady ? 'success' : undefined"
                :stroke-width="14"
                text-inside
                class="oa-mb-3"
              />
              <div class="oa-flex-between oa-mb-3">
                <span class="oa-hint">{{ updateElapsedText }}</span>
                <el-button v-if="updateReloadReady" type="primary" @click="reloadPage">刷新页面</el-button>
                <span v-else class="oa-hint">部署期间服务可能短暂重启，进度会自动继续。</span>
              </div>
            </template>
          </el-form>
        </template>

        <template v-else-if="tab.key === 'navLinks'">
          <div class="oa-flex-between oa-mb-3">
            <div class="oa-hint">维护显示在左侧导航栏「外链应用」分组里的外部链接，点击后新标签页打开。</div>
            <el-button type="primary" @click="openNavLinkDialog(null)">新增外链</el-button>
          </div>
          <el-table :data="navLinks" border>
            <el-table-column prop="title" label="名称" min-width="160" />
            <el-table-column prop="url" label="地址" min-width="260" show-overflow-tooltip />
            <el-table-column prop="sortOrder" label="排序" width="80" />
            <el-table-column label="打开方式" width="110">
              <template #default="{ row }">{{ row.openMode === "same_tab" ? "当前页" : "新标签页" }}</template>
            </el-table-column>
            <el-table-column label="启用" width="80">
              <template #default="{ row }">
                <el-tag :type="row.isActive ? 'success' : 'info'" size="small">{{ row.isActive ? "启用" : "停用" }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openNavLinkDialog(row)">编辑</el-button>
                <el-button link type="danger" @click="removeNavLink(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-dialog v-model="navLinkDialog.visible" :title="navLinkDialog.id ? '编辑外链' : '新增外链'" width="480px">
            <el-form label-position="top">
              <el-form-item label="名称" required>
                <el-input v-model="navLinkDialog.title" placeholder="例如 帮助中心" />
              </el-form-item>
              <el-form-item label="地址" required>
                <el-input v-model="navLinkDialog.url" placeholder="https://…" />
              </el-form-item>
              <el-form-item label="排序">
                <el-input-number v-model="navLinkDialog.sortOrder" :min="0" />
              </el-form-item>
              <el-form-item label="打开方式">
                <el-radio-group v-model="navLinkDialog.openMode">
                  <el-radio label="new_tab">新标签页</el-radio>
                  <el-radio label="same_tab">当前页</el-radio>
                </el-radio-group>
              </el-form-item>
              <el-form-item label="启用">
                <el-switch v-model="navLinkDialog.isActive" />
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="navLinkDialog.visible = false">取消</el-button>
              <el-button type="primary" :loading="navLinkSaving" @click="submitNavLink">保存</el-button>
            </template>
          </el-dialog>
        </template>
      </el-tab-pane>
    </el-tabs>
  </DataPanel>

  <ImportExcelDialog
    v-model="userImportDialog"
    title="导入用户账号"
    :field-labels="USER_IMPORT_FIELDS"
    :template-header="['用户名', '显示名称', '角色', '初始密码', '绑定人员工号', '是否启用']"
    :template-sample="['zhangsan', '张三', 'operator', 'ChangeMe#2026', 'EMP001', '1']"
    template-file-name="用户账号导入模板.csv"
    hint="表头需包含「用户名」。角色写角色编码或名称（admin / operator / viewer / user）；新建账号必须填初始密码（8 位以上），更新已存在账号时留空则不改密码；普通角色必须绑定在职人员工号，超级管理员角色只有超级管理员能分配。"
    :import-fn="importUsers"
    @imported="loadAll()"
  />

  <FormDialog
    v-model="userDialogVisible"
    :title="userEditingId ? '编辑账号' : '新增账号'"
    size="md"
    :confirm-text="userEditingId ? '保存账号' : '创建账号'"
    :loading="saving"
    @confirm="submitUser"
  >
    <el-form label-position="top">
      <el-form-item label="登录账号" required>
        <el-input
          v-model="userForm.username"
          :disabled="Boolean(userEditingId)"
          placeholder="3-64 位字母、数字、点、下划线或短横线"
        />
      </el-form-item>
      <el-form-item label="显示名称" required>
        <el-input v-model="userForm.displayName" />
      </el-form-item>
      <el-form-item label="角色" required>
        <el-select v-model="userForm.role" class="oa-full-width">
          <el-option
            v-for="role in roles"
            :key="role.id"
            :label="role.name || role.code"
            :value="role.code"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="绑定人员（普通账号必填）">
        <el-select v-model="userForm.employeeId" filterable clearable class="oa-full-width">
          <el-option
            v-for="option in employeeOptions()"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="账号状态">
        <el-switch v-model="userForm.isActive" active-text="启用" inactive-text="停用" />
      </el-form-item>
      <el-form-item :label="userEditingId ? '重置密码（可选）' : '初始密码'">
        <el-input
          v-model="userForm.password"
          type="password"
          show-password
          :placeholder="userEditingId ? '留空表示不修改' : '至少 8 位'"
        />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="backupDownloadVisible"
    title="下载数据库备份"
    size="sm"
    confirm-text="确认下载"
    :loading="saving"
    @confirm="submitBackupDownload"
  >
    <p class="oa-mt-0 oa-mb-3">
      <strong>{{ backupDownloadTarget?.fileName }}</strong>
      <span class="oa-hint">
        {{ formatFileSize(backupDownloadTarget?.fileSize) }} ·
        {{ formatTime(backupDownloadTarget?.createdAt) }}
      </span>
    </p>
    <el-form label-position="top">
      <el-form-item label="当前账号密码" required>
        <el-input v-model="backupDownloadPassword" type="password" show-password />
      </el-form-item>
    </el-form>
  </FormDialog>

  <el-dialog v-model="roleEditDialog.visible" title="编辑角色" width="440px">
    <el-form label-position="top">
      <el-form-item label="角色名称" required>
        <el-input v-model="roleEditDialog.name" />
      </el-form-item>
      <el-form-item label="角色类别">
        <el-select v-model="roleEditDialog.category" class="oa-full-width">
          <el-option
            v-for="(label, value) in ROLE_CATEGORIES"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="超级管理员">
        <el-switch v-model="roleEditDialog.isSuperAdmin" />
        <div class="oa-hint">开启后该角色的所有账号将拥有全部数据与权限（超管角色类别须为「管理员」）。</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="roleEditDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submitRoleEdit">保存</el-button>
    </template>
  </el-dialog>
</template>
