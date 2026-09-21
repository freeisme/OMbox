import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { NAV_ITEMS, PATH_BY_PAGE } from "../navigation";
import { canViewPage, firstVisiblePath, refreshSession, session } from "../session";

/** 页面组件一律按需加载，首屏只保留外壳与登录页。 */
const VIEW_LOADERS: Record<string, () => Promise<unknown>> = {
  dashboard: () => import("../views/DashboardView.vue"),
  computers: () => import("../views/ComputersView.vue"),
  dictionary: () => import("../views/DictionaryView.vue"),
  employees: () => import("../views/EmployeesView.vue"),
  flowControl: () => import("../views/FlowControlView.vue"),
  inventory: () => import("../views/InventoryView.vue"),
  governance: () => import("../views/GovernanceView.vue"),
  inspection: () => import("../views/InspectionView.vue"),
  leftEmployees: () => import("../views/LeftEmployeesView.vue"),
  scrapRecords: () => import("../views/ScrapRecordsView.vue"),
  serviceManagement: () => import("../views/ServiceManagementView.vue"),
  tickets: () => import("../views/TicketsView.vue"),
  settings: () => import("../views/SettingsView.vue"),
  audit: () => import("../views/AuditView.vue"),
  datacenterDevices: () => import("../views/DatacenterDeviceView.vue"),
  rackLayout: () => import("../views/RackLayoutView.vue"),
  devicePanel: () => import("../views/DevicePanelView.vue"),
  topology: () => import("../views/TopologyView.vue"),
};

const vueRoutes = NAV_ITEMS.filter((item) => VIEW_LOADERS[item.page]).map((item) => ({
  path: item.path,
  name: item.page,
  component: VIEW_LOADERS[item.page],
  meta: { title: item.title, page: item.page },
})) as RouteRecordRaw[];

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("../views/LoginView.vue"),
    meta: { title: "登录", public: true },
  },
  { path: "/", redirect: PATH_BY_PAGE.dashboard },
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
  const page = typeof to.meta.page === "string" ? to.meta.page : "";
  if (page && !canViewPage(page)) {
    return { path: firstVisiblePath() };
  }
  return true;
});
