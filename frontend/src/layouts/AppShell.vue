<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { NAV_GROUPS, NAV_ITEMS, PATH_BY_PAGE } from "../navigation";
import { canViewPage, hasPermission, loadMeta, logout, session } from "../session";
import { fetchNotifications } from "../api/service";
import { installActivityTracking, isIdleBeyond } from "../activity";

const route = useRoute();
const router = useRouter();
const theme = ref(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const notificationCount = ref("");
let pollTimer: number | undefined;

const visibleItems = computed(() => NAV_ITEMS.filter((item) => canViewPage(item.page)));
const currentTitle = computed(() => String(route.meta.title ?? "OMbox 运维（O&M）盒子"));
const version = computed(() => session.meta?.version || __APP_VERSION__);

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
        <span class="oa-brand-mark">OM</span>
        <span class="oa-brand-text">
          <strong>OMbox</strong>
          <small>运维（O&amp;M）盒子</small>
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
          <el-badge :value="notificationCount" :hidden="!notificationCount">
            <el-button text @click="openNotifications">消息</el-button>
          </el-badge>
          <el-button text @click="toggleTheme">{{ theme === "dark" ? "日间" : "夜间" }}</el-button>
          <el-button text @click="reloadData">重新加载</el-button>
          <el-button text @click="router.push(PATH_BY_PAGE.settings)">设置</el-button>
          <el-button text type="danger" @click="signOut">退出</el-button>
        </div>
      </header>

      <section class="oa-content is-scroll">
        <slot />
      </section>
    </main>
  </div>
</template>
