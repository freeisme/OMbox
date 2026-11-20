<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { NAV_BY_PAGE, NAV_GROUPS, NAV_ITEMS, PAGE_BY_PATH, PATH_BY_PAGE } from "../navigation";
import { NAV_ICON_FALLBACK, NAV_ICON_PATHS } from "../navIcons";
import { canViewPage, firstVisiblePath, hasPermission, loadMeta, logout, session } from "../session";
import { checkUpdateStatus } from "../api/settings";
import { fetchNotifications } from "../api/service";
import { listNavLinks, type NavLink } from "../api/company";
import {
  canSwitchCompany,
  companyScope,
  companyScopeAllLabel,
  companyScopeLabel,
  loadCompanyScope,
  setCompanyScope,
} from "../companyScope";
import { installActivityTracking, isIdleBeyond } from "../activity";

const route = useRoute();
const router = useRouter();
const theme = ref(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const notificationCount = ref("");
const navLinks = ref<NavLink[]>([]);
const updateBanner = ref<{ latestVersion: string; targetTab: string } | null>(null);
let pollTimer: number | undefined;

/* ---------------- 侧栏：图标、分组折叠、图标栏 ---------------- */
const RAIL_STORAGE_KEY = "oa-rail-collapsed";
const GROUP_STORAGE_KEY = "oa-nav-collapsed-groups";
/** 窄屏（仍保留侧栏的区间）自动收成图标栏；<768 是顶部横向导航，不折叠。 */
const RAIL_AUTO_COLLAPSE_MAX = 1280;

const railCollapsed = ref(false);
const collapsedGroups = ref<string[]>([]);
/** <768px 时侧栏变成顶部横条，此时强制展开，避免图标栏挤在一整条横条里。 */
const compactViewport = ref(false);
const railIsCollapsed = computed(() => railCollapsed.value && !compactViewport.value);

function iconPath(page: string): string {
  return NAV_ICON_PATHS[page] ?? NAV_ICON_FALLBACK;
}

function groupItems(group: string) {
  return visibleItems.value.filter((item) => item.group === group);
}

function currentGroup(): string {
  const page = PAGE_BY_PATH[route.path] ?? "";
  return (page && NAV_BY_PAGE[page]?.group) || "";
}

function isGroupCollapsed(group: string): boolean {
  return collapsedGroups.value.includes(group);
}

function toggleGroup(group: string): void {
  collapsedGroups.value = isGroupCollapsed(group)
    ? collapsedGroups.value.filter((entry) => entry !== group)
    : [...collapsedGroups.value, group];
  window.localStorage.setItem(GROUP_STORAGE_KEY, JSON.stringify(collapsedGroups.value));
}

function toggleRail(): void {
  railCollapsed.value = !railCollapsed.value;
  window.localStorage.setItem(RAIL_STORAGE_KEY, railCollapsed.value ? "1" : "0");
}

function restoreNavState(): void {
  compactViewport.value = window.innerWidth < 768;
  const railStored = window.localStorage.getItem(RAIL_STORAGE_KEY);
  if (railStored === "1" || railStored === "0") {
    railCollapsed.value = railStored === "1";
  } else {
    railCollapsed.value = window.innerWidth >= 768 && window.innerWidth < RAIL_AUTO_COLLAPSE_MAX;
  }

  const groupsStored = window.localStorage.getItem(GROUP_STORAGE_KEY);
  if (groupsStored) {
    try {
      const parsed = JSON.parse(groupsStored);
      if (Array.isArray(parsed)) collapsedGroups.value = parsed.map((entry) => String(entry));
      return;
    } catch {
      // 存储损坏时退回默认策略
    }
  }
  // 默认只展开当前页所在分组，其余收起，保证一屏能看到全部入口
  const active = currentGroup();
  collapsedGroups.value = NAV_GROUPS.filter(
    (group) => group !== active && groupItems(group).length > 0,
  );
}

function onRailResize(): void {
  compactViewport.value = window.innerWidth < 768;
  // 小屏是顶部横条，不进入图标栏模式
  if (compactViewport.value) {
    railCollapsed.value = false;
    return;
  }
  // 用户手动选过就尊重选择，只有从未选择时才跟随窗口宽度
  if (window.localStorage.getItem(RAIL_STORAGE_KEY)) return;
  railCollapsed.value = window.innerWidth < RAIL_AUTO_COLLAPSE_MAX;
}

function dismissUpdateBanner(): void {
  updateBanner.value = null;
}

function onCompanyCommand(command: string): void {
  if (command === "__scope_all__") {
    setCompanyScope("");
    return;
  }
  setCompanyScope(String(command));
}

async function checkUpdateBanner(): Promise<void> {
  if (!hasPermission("system_updates", "update")) return;
  try {
    const status = await checkUpdateStatus();
    if (status.hasUpdate && status.latestVersion) {
      updateBanner.value = { latestVersion: status.latestVersion, targetTab: "updates" };
    }
  } catch {
    // 更新服务未配置或不可达时静默忽略，不打扰用户
  }
}

/** 版本号本身已带 v（如 v4.0.9），避免显示成 vv4.0.9。 */
const updateVersionLabel = computed(() => {
  const raw = String(updateBanner.value?.latestVersion ?? "").trim();
  if (!raw) return "";
  return /^v/i.test(raw) ? raw : `v${raw}`;
});

function goToUpdates(): void {
  const target = updateBanner.value;
  if (!canViewPage("settings")) {
    // 之前这里会静默跳转失败：路由守卫把没有「系统设置」的账号弹回首页，
    // 用户只觉得"点了没反应"。现在直接说明原因。
    ElMessage.warning("当前账号没有「设置」权限，无法打开发布更新页，请联系管理员。");
    return;
  }
  dismissUpdateBanner();
  void router.push({ path: PATH_BY_PAGE.settings, query: { tab: target?.targetTab ?? "updates" } });
}

function goToSettings(): void {
  if (!canViewPage("settings")) {
    ElMessage.warning("当前账号没有「设置」权限，请联系管理员。");
    return;
  }
  void router.push(PATH_BY_PAGE.settings);
}

function openExternalLink(link: NavLink): void {
  if (link.openMode === "same_tab") {
    window.location.href = link.url;
  } else {
    window.open(link.url, "_blank", "noopener,noreferrer");
  }
}

async function loadNavLinks(): Promise<void> {
  try {
    navLinks.value = await listNavLinks();
  } catch {
    navLinks.value = [];
  }
}

const visibleItems = computed(() => NAV_ITEMS.filter((item) => canViewPage(item.page)));
const currentTitle = computed(() => String(route.meta.title ?? "OMbox 运维（O&M）盒子"));
/** 个人工作台是独立门户：隐藏资产管理侧栏，只留一条顶栏。 */
const isPersonalPage = computed(() => route.path === "/me");

function goBackToConsole(): void {
  void router.push(firstVisiblePath());
}

const version = computed(() => session.meta?.version || __APP_VERSION__);
/** 系统名与 Logo 来自「设置 → 系统参数」，没设置时回落到产品默认样式。 */
const brandName = computed(() => session.appName.trim() || "OMbox");
const brandSubtitle = computed(() => (session.appName.trim() ? "" : "运维（O&M）盒子"));
const brandLogo = computed(() => session.appLogo || "");

function setTheme(next: string): void {
  theme.value = next;
  document.documentElement.dataset.theme = next;
  document.documentElement.classList.toggle("dark", next === "dark");
  window.localStorage.setItem("oa-theme", next);
}

function toggleTheme(): void {
  setTheme(theme.value === "dark" ? "light" : "dark");
}

function reloadData(): void {
  ElMessage.success("正在从数据库重新加载…");
  window.location.reload();
}

function openNotifications(): void {
  void router.push("/service-management");
}

async function refreshNotificationCount(): Promise<void> {
  if (!hasPermission("notifications")) return;
  try {
    const items = await fetchNotifications();
    const unread = items.filter((item) => !item.isRead).length;
    notificationCount.value = unread ? String(unread) : "";
  } catch {
    notificationCount.value = "";
  }
}

async function signOut(): Promise<void> {
  await logout();
  setCompanyScope("");
  await router.replace("/login");
}

onMounted(async () => {
  installActivityTracking();
  restoreNavState();
  window.addEventListener("resize", onRailResize);
  document.documentElement.classList.toggle("dark", theme.value === "dark");
  if (!session.meta) await loadMeta();
  await refreshNotificationCount();
  await loadNavLinks();
  await loadCompanyScope();
  await checkUpdateBanner();
  pollTimer = window.setInterval(() => {
    // 用户已经空闲超过会话时长（或页面在后台）时不再轮询：
    // 否则定时请求会不断刷新会话，服务端的"无操作超时"永远不会生效。
    if (document.visibilityState !== "visible" || isIdleBeyond(session.idleMinutes)) return;
    void refreshNotificationCount();
  }, 60_000);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
  window.removeEventListener("resize", onRailResize);
});
</script>

<template>
  <div class="oa-shell">
    <aside v-if="!isPersonalPage" class="oa-rail" :class="{ 'is-collapsed': railIsCollapsed }">
      <div class="oa-brand">
        <img v-if="brandLogo" class="oa-brand-logo" :src="brandLogo" alt="系统 Logo" />
        <span v-else class="oa-brand-mark">OM</span>
        <span v-if="!railIsCollapsed" class="oa-brand-text">
          <strong>{{ brandName }}</strong>
          <small v-if="brandSubtitle">{{ brandSubtitle }}</small>
        </span>
        <button
          type="button"
          class="oa-rail-toggle"
          :title="railIsCollapsed ? '展开侧栏' : '收起侧栏'"
          :aria-label="railIsCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="toggleRail"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path :d="railIsCollapsed ? 'M9 6l6 6-6 6' : 'M15 6l-6 6 6 6'" />
          </svg>
        </button>
      </div>

      <el-menu
        class="oa-nav"
        :default-active="route.path"
        router
        :collapse="railIsCollapsed"
        :collapse-transition="false"
      >
        <template v-for="group in NAV_GROUPS" :key="group">
          <template v-if="groupItems(group).length">
            <div v-if="railIsCollapsed" class="oa-nav-divider" />
            <div
              v-else
              class="oa-nav-group"
              role="button"
              tabindex="0"
              :aria-expanded="!isGroupCollapsed(group)"
              @click="toggleGroup(group)"
              @keydown.enter="toggleGroup(group)"
              @keydown.space.prevent="toggleGroup(group)"
            >
              <span>{{ group }}</span>
              <svg
                viewBox="0 0 24 24"
                class="oa-nav-caret"
                :class="{ 'is-collapsed': isGroupCollapsed(group) }"
                aria-hidden="true"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </div>
            <el-menu-item
              v-for="item in groupItems(group)"
              v-show="railIsCollapsed || !isGroupCollapsed(group)"
              :key="item.page"
              :index="item.path"
            >
              <svg viewBox="0 0 24 24" class="oa-nav-icon" aria-hidden="true">
                <path :d="iconPath(item.page)" />
              </svg>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </template>
        </template>
        <template v-if="navLinks.length">
          <div v-if="railIsCollapsed" class="oa-nav-divider" />
          <div v-else class="oa-nav-group is-static">外链应用</div>
          <el-menu-item v-for="link in navLinks" :key="link.id" @click="openExternalLink(link)">
            <svg viewBox="0 0 24 24" class="oa-nav-icon" aria-hidden="true">
              <path :d="NAV_ICON_FALLBACK" />
            </svg>
            <template #title>{{ link.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>

      <div v-if="!railIsCollapsed" class="oa-rail-footer">
        当前版本 v{{ version }}
        <br />
        {{ session.user?.displayName || session.user?.username || "" }}
      </div>
    </aside>

    <main class="oa-main">
      <header class="oa-topbar">
        <div class="oa-topbar-title">
          <h1>{{ currentTitle }}</h1>
          <el-tag size="small" effect="plain" type="info">v{{ version }}</el-tag>
        </div>
        <div class="oa-topbar-actions">
          <el-button v-if="isPersonalPage" text @click="goBackToConsole">返回资产系统</el-button>
          <el-dropdown
            v-if="canSwitchCompany && !isPersonalPage"
            trigger="click"
            placement="bottom-end"
            @command="onCompanyCommand"
          >
            <el-button
              text
              class="oa-company-switch"
              aria-label="切换公司视图（组织架构）"
              title="切换公司视图（影响组织架构）"
            >
              <span class="oa-company-switch-label">{{ companyScopeLabel }}</span>
              <span class="oa-company-switch-caret" aria-hidden="true">▾</span>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="__scope_all__">{{ companyScopeAllLabel }}</el-dropdown-item>
                <el-dropdown-item
                  v-for="item in companyScope.companies"
                  :key="item.id"
                  :command="item.id"
                >
                  {{ item.name }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-badge :value="notificationCount" :hidden="!notificationCount">
            <el-button text @click="openNotifications">消息</el-button>
          </el-badge>
          <el-button text @click="toggleTheme">{{ theme === "dark" ? "日间" : "夜间" }}</el-button>
          <el-button v-if="!isPersonalPage" text @click="reloadData">重新加载</el-button>
          <el-button v-if="!isPersonalPage" text @click="goToSettings">设置</el-button>
          <el-button v-if="!isPersonalPage" text @click="router.push('/me')">我的</el-button>
          <el-button text type="danger" @click="signOut">退出</el-button>
        </div>
      </header>

      <div v-if="updateBanner" class="oa-update-banner">
        <el-alert type="warning" :closable="true" show-icon @close="dismissUpdateBanner">
          <template #title>
            发现可用版本 <strong>{{ updateVersionLabel }}</strong>，是否立即更新？
          </template>
          <el-button type="primary" size="small" @click="goToUpdates">立即更新</el-button>
          <el-button size="small" @click="dismissUpdateBanner">稍后</el-button>
        </el-alert>
      </div>

      <section class="oa-content is-scroll">
        <slot />
      </section>
    </main>
  </div>
</template>
