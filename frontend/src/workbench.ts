import { hasPermission } from "./session";

export interface WorkbenchModuleDef {
  key: string;
  title: string;
  hint: string;
  /** 12 栅格布局下占用的列宽 */
  span: number;
  /** 任一模块具备 view 权限即可见；空数组表示所有登录用户可见 */
  modules: string[];
}

/** 模块数量刻意控制在 9 个以内，并把待办、快捷入口、核心统计放在首屏。 */
export const WORKBENCH_MODULES: WorkbenchModuleDef[] = [
  { key: "todos", title: "待办事项", hint: "需要你处理的事项", span: 8, modules: [] },
  { key: "quickActions", title: "快捷入口", hint: "按权限提供的常用操作", span: 4, modules: [] },
  { key: "assets", title: "核心统计", hint: "资产与人员概况", span: 12, modules: [] },
  { key: "notifications", title: "通知公告", hint: "与你相关的消息", span: 6, modules: [] },
  {
    key: "progress",
    title: "处理进度",
    hint: "服务与巡检进展",
    span: 6,
    modules: ["tickets", "changes", "problems", "approvals", "inspection_management", "quality"],
  },
  { key: "recentAssets", title: "最近登记资产", hint: "按注册日期倒序", span: 6, modules: ["it_assets"] },
  { key: "myAssets", title: "我的设备", hint: "名下办公终端", span: 6, modules: [] },
  {
    key: "recentInbound",
    title: "最近入库物资",
    hint: "库存增加记录",
    span: 6,
    modules: ["inventory_catalog", "warehouse_management"],
  },
  { key: "quality", title: "数据质量待办", hint: "待处理的数据问题", span: 6, modules: ["quality"] },
];

export function moduleAvailable(def: WorkbenchModuleDef): boolean {
  if (!def.modules.length) return true;
  return def.modules.some((module) => hasPermission(module, "view"));
}

export function availableModules(): WorkbenchModuleDef[] {
  return WORKBENCH_MODULES.filter(moduleAvailable);
}

export interface WorkbenchPrefs {
  hidden: string[];
  order: string[];
}

function prefsKey(userKey: string): string {
  return `oa-workbench-${userKey || "default"}`;
}

export function loadPrefs(userKey: string): WorkbenchPrefs {
  try {
    const raw = window.localStorage.getItem(prefsKey(userKey));
    if (!raw) return { hidden: [], order: [] };
    const parsed = JSON.parse(raw) as Partial<WorkbenchPrefs>;
    return {
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden.filter((item) => typeof item === "string") : [],
      order: Array.isArray(parsed.order) ? parsed.order.filter((item) => typeof item === "string") : [],
    };
  } catch {
    return { hidden: [], order: [] };
  }
}

export function savePrefs(userKey: string, prefs: WorkbenchPrefs): void {
  try {
    window.localStorage.setItem(prefsKey(userKey), JSON.stringify(prefs));
  } catch {
    // 隐私模式下写入失败时忽略，仅影响本次会话的自定义
  }
}

export function resetPrefs(userKey: string): void {
  try {
    window.localStorage.removeItem(prefsKey(userKey));
  } catch {
    // 忽略
  }
}

/** 角色可用的模块 ∩ 用户自定义（顺序 + 隐藏）。 */
export function resolveModules(userKey: string): WorkbenchModuleDef[] {
  const available = availableModules();
  const prefs = loadPrefs(userKey);
  const indexOf = (key: string) => {
    const index = prefs.order.indexOf(key);
    return index === -1 ? Number.MAX_SAFE_INTEGER : index;
  };
  const ordered = [...available].sort((left, right) => {
    const diff = indexOf(left.key) - indexOf(right.key);
    if (diff !== 0) return diff;
    return available.indexOf(left) - available.indexOf(right);
  });
  return ordered.filter((module) => !prefs.hidden.includes(module.key));
}
