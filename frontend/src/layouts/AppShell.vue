<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { NAV_GROUPS, NAV_ITEMS, PATH_BY_PAGE } from "../navigation";
import { canViewPage, hasPermission, loadMeta, logout, session } from "../session";
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

function goToUpdates(): void {
  const target = updateBanner.value;
  dismissUpdateBanner();
  void router.push({ path: PATH_BY_PAGE.settings, query: { tab: target?.targetTab ?? "updates" } });
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
  await router.replace("/login");
}

onMounted(async () => {
  installActivityTracking();
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
});
</script>

<template>
  <div class="oa-shell">
    <aside class="oa-rail">
      <div class="oa-brand">
        <img v-if="brandLogo" class="oa-brand-logo" :src="brandLogo" alt="系统 Logo" />
        <span v-else class="oa-brand-mark">OM</span>
        <span class="oa-brand-text">
          <strong>{{ brandName }}</strong>
          <small v-if="brandSubtitle">{{ brandSubtitle }}</small>
        </span>
      </div>

      <el-menu class="oa-nav" :default-active="route.path" router>
        <template v-for="group in NAV_GROUPS" :key="group">
          <template v-if="visibleItems.some((item) => item.group === group)">
            <div class="oa-nav-group">{{ group }}</div>
            <el-menu-item
              v-for="item in visibleItems.filter((entry) => entry.group === group)"
              :key="item.page"
              :index="item.path"
            >
              {{ item.title }}
            </el-menu-item>
          </template>
        </template>
        <template v-if="navLinks.length">
          <div class="oa-nav-group">外链应用</div>
          <el-menu-item v-for="link in navLinks" :key="link.id" @click="openExternalLink(link)">
            {{ link.title }}
          </el-menu-item>
        </template>
      </el-menu>

      <div class="oa-rail-footer">
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
          <el-dropdown
            v-if="canSwitchCompany"
            trigger="click"
            placement="bottom-end"
            @command="onCompanyCommand"
          >
            <el-button
              text
              class="oa-company-switch"
              aria-label="切换公司视图"
              title="切换公司视图"
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
          <el-button text @click="reloadData">重新加载</el-button>
          <el-button text @click="router.push(PATH_BY_PAGE.settings)">设置</el-button>
          <el-button text type="danger" @click="signOut">退出</el-button>
        </div>
      </header>

      <div v-if="updateBanner" class="oa-update-banner">
        <el-alert type="warning" :closable="true" show-icon @close="dismissUpdateBanner">
          <template #title>
            发现可用版本 <strong>v{{ updateBanner.latestVersion }}</strong>，是否立即更新？
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
