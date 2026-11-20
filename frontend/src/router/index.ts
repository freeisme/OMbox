import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { NAV_ITEMS, PATH_BY_PAGE } from "../navigation";
import { canViewPage, firstVisiblePath, refreshSession, session } from "../session";

/** 页面组件一律按需加载，首屏只保留外壳与登录页。 */
const VIEW_LOADERS: Record<string, () => Promise<unknown>> = {
  dashboard: () => import("../views/DashboardView.vue"),
  personal: () => import("../views/PersonalView.vue"),
  computers: () => import("../views/ComputersView.vue"),
  dictionary: () => import("../views/DictionaryView.vue"),
  employees: () => import("../views/EmployeesView.vue"),
  governance: () => import("../views/GovernanceView.vue"),
  inspection: () => import("../views/InspectionView.vue"),
  leftEmployees: () => import("../views/LeftEmployeesView.vue"),
  serviceManagement: () => import("../views/ServiceManagementView.vue"),
  tickets: () => import("../views/TicketsView.vue"),
  settings: () => import("../views/SettingsView.vue"),
  audit: () => import("../views/AuditView.vue"),
  // 机房四合一（页内页签）与物资三合一（页内页签）
  datacenter: () => import("../views/DatacenterView.vue"),
  inventoryHub: () => import("../views/InventoryHubView.vue"),
  meetingRooms: () => import("../views/MeetingRoomView.vue"),
  organizations: () => import("../views/OrganizationsView.vue"),
  lineguard: () => import("../views/LineGuardDashboardView.vue"),
  lineguardDevices: () => import("../views/LineGuardDevicesView.vue"),
  lineguardAlerts: () => import("../views/LineGuardAlertsView.vue"),
};

const vueRoutes = NAV_ITEMS.filter((item) => VIEW_LOADERS[item.page]).map((item) => ({
  path: item.path,
  name: item.page,
  component: VIEW_LOADERS[item.page],
  meta: { title: item.title, page: item.page },
})) as RouteRecordRaw[];

/** 机房/物资合并后保留的旧入口，一律跳到新页面的对应页签。 */
const LEGACY_REDIRECTS: RouteRecordRaw[] = [
  { path: "/datacenter-devices", redirect: () => ({ path: "/datacenter", query: { tab: "devices" } }) },
  { path: "/rack-layout", redirect: () => ({ path: "/datacenter", query: { tab: "racks" } }) },
  { path: "/device-panel", redirect: () => ({ path: "/datacenter", query: { tab: "panel" } }) },
  { path: "/topology", redirect: () => ({ path: "/datacenter", query: { tab: "topology" } }) },
  { path: "/inventory", redirect: () => ({ path: "/inventory-hub", query: { tab: "catalog" } }) },
  { path: "/flow-control", redirect: () => ({ path: "/inventory-hub", query: { tab: "flow" } }) },
  { path: "/scrap-records", redirect: () => ({ path: "/inventory-hub", query: { tab: "scrap" } }) },
] as RouteRecordRaw[];

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("../views/LoginView.vue"),
    meta: { title: "登录", public: true },
  },
  {
    path: "/group-setup",
    name: "group-setup",
    component: () => import("../views/GroupSetupView.vue"),
    meta: { title: "集团/公司初始化" },
  },
  { path: "/", redirect: PATH_BY_PAGE.dashboard },
  // 合并前的旧地址：收藏夹、外链、别人发的链接都还能用，自动落到对应页签。
  ...LEGACY_REDIRECTS,
  ...vueRoutes,
  { path: "/:pathMatch(.*)*", redirect: PATH_BY_PAGE.dashboard },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  if (!session.ready) await refreshSession();
  const isPublic = Boolean(to.meta.public);
  if (isPublic) {
    return session.user ? { path: firstVisiblePath() } : true;
  }
  if (!session.user) {
    return { path: "/login", query: to.fullPath === "/" ? {} : { redirect: to.fullPath } };
  }
  if (!session.groupSetupDone && to.path !== "/group-setup") {
    return { path: "/group-setup" };
  }
  if (session.groupSetupDone && to.path === "/group-setup") {
    return { path: firstVisiblePath() };
  }
  const page = typeof to.meta.page === "string" ? to.meta.page : "";
  if (page && !canViewPage(page)) {
    return { path: firstVisiblePath() };
  }
  return true;
});
