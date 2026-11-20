export interface NavItem {
  page: string;
  path: string;
  title: string;
  group: string;
  /** 决定菜单可见性的权限资源（任一 action=view 可见即显示） */
  modules: string[];
}

const SERVICE_MODULES = [
  "tickets",
  "changes",
  "problems",
  "knowledge",
  "forms",
  "sla",
  "approvals",
  "notifications",
];

export const NAV_ITEMS: NavItem[] = [
  // 个人工作台：任何已登录账号都可见（canViewPage 对 personal 特判），不需要授权模块
  { page: "personal", path: "/me", title: "我的工作台", group: "个人中心", modules: [] },
  { page: "dashboard", path: "/dashboard", title: "工作台", group: "资产台账", modules: ["dashboard"] },
  { page: "computers", path: "/computers", title: "办公终端", group: "资产台账", modules: ["it_assets"] },
  { page: "employees", path: "/employees", title: "使用人员", group: "资产台账", modules: ["employees"] },
  { page: "leftEmployees", path: "/left-employees", title: "离职人员", group: "资产台账", modules: ["employees"] },
  { page: "organizations", path: "/organizations", title: "组织架构", group: "资产台账", modules: ["organizations"] },
  // 机房四合一：设备清单 / 机柜视图 / 设备面板 / 网络拓扑 收进一个页面，
  // 页内用页签切换（见 views/DatacenterView.vue），旧地址在 router 里保留跳转。
  { page: "datacenter", path: "/datacenter", title: "机房", group: "机房管理", modules: ["rack_layout"] },
  // 巡检独立成一个模块：机房 / 弱电间 / 会议室都要巡检，不再挂在"机房管理"下。
  {
    page: "inspection",
    path: "/inspection",
    title: "巡检中心",
    group: "巡检管理",
    modules: ["inspection_management"],
  },
  {
    page: "meetingRooms",
    path: "/meeting-rooms",
    title: "会议室",
    group: "巡检管理",
    modules: ["inspection_management"],
  },
  // 物资三合一：台账 / 流转记录 / 报废记录 收进一个页面（见 views/InventoryHubView.vue）。
  // 入口可见性取三个模块的并集，页内页签再按各自权限过滤。
  {
    page: "inventoryHub",
    path: "/inventory-hub",
    title: "物资管理",
    group: "资源与审计",
    modules: ["inventory_catalog", "warehouse_management", "inventory_operations", "scrap_management"],
  },
  { page: "dictionary", path: "/dictionary", title: "基础字典", group: "资源与审计", modules: ["organizations"] },
  { page: "audit", path: "/audit", title: "操作日志", group: "服务管理", modules: ["audit_logs"] },
  { page: "tickets", path: "/tickets", title: "工单", group: "系统", modules: ["tickets"] },
  {
    page: "serviceManagement",
    path: "/service-management",
    title: "服务管理",
    group: "服务管理",
    modules: SERVICE_MODULES,
  },
  { page: "governance", path: "/governance", title: "同步与质量", group: "服务管理", modules: ["sync"] },
  {
    page: "lineguard",
    path: "/lineguard",
    title: "工控机总览",
    group: "产线设备",
    modules: ["lineguard"],
  },
  {
    page: "lineguardDevices",
    path: "/lineguard/devices",
    title: "工控机台账",
    group: "产线设备",
    modules: ["lineguard"],
  },
  {
    page: "lineguardAlerts",
    path: "/lineguard/alerts",
    title: "工控机告警",
    group: "产线设备",
    modules: ["lineguard"],
  },
  {
    page: "settings",
    path: "/settings",
    title: "设置",
    group: "服务管理",
    // 页面里每个页签都有自己的权限：只给了「系统更新」或「备份」的用户也要能进来，
    // 否则顶栏的「立即更新」跳转会因整页被拦而静默失败。
    modules: [
      "system_settings",
      "system_updates",
      "backups",
      "user_management",
      "role_management",
    ],
  },
];

export const NAV_GROUPS = ["个人中心", ..."资产台账", "机房管理", "巡检管理", "产线设备", "资源与审计", "系统", "服务管理"];

export const PAGE_BY_PATH: Record<string, string> = Object.fromEntries(
  NAV_ITEMS.map((item) => [item.path, item.page]),
);

export const PATH_BY_PAGE: Record<string, string> = Object.fromEntries(
  NAV_ITEMS.map((item) => [item.page, item.path]),
);

export const NAV_BY_PAGE: Record<string, NavItem> = Object.fromEntries(
  NAV_ITEMS.map((item) => [item.page, item]),
);
