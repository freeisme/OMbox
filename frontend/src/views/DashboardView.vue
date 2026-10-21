<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { fetchWorkbench, markNotificationRead, type WorkbenchSummary } from "../api/workbench";
import DataPanel from "../components/ui/DataPanel.vue";
import EmptyHint from "../components/ui/EmptyHint.vue";
import MetricCard from "../components/ui/MetricCard.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import StatusTag from "../components/ui/StatusTag.vue";
import { hasPermission, session } from "../session";
import { deviceTypeLabel, formatDateTimeText, notificationTypeLabel } from "../labels";
import {
  availableModules,
  loadPrefs,
  resetPrefs,
  resolveModules,
  savePrefs,
  type WorkbenchModuleDef,
} from "../workbench";

const router = useRouter();
const loading = ref(true);
const refreshing = ref(false);
const summary = ref<WorkbenchSummary>({
  generatedAt: "",
  stateRevision: 0,
  assets: {
    computers: 0,
    inUse: 0,
    idle: 0,
    attention: 0,
    employees: 0,
    nonAssetItems: 0,
    rootOrgs: 0,
  },
  recentComputers: [],
  recentInbound: [],
  myAssets: [],
});

const userKey = computed(() => session.user?.username || "default");
const modules = ref<WorkbenchModuleDef[]>(resolveModules(userKey.value));
const customizing = ref(false);
const draft = ref<Array<{ key: string; title: string; visible: boolean }>>([]);

const today = new Date().toISOString().slice(0, 10);
const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 6) return "夜班辛苦";
  if (hour < 12) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
});

const metrics = computed(() => {
  const assets = summary.value.assets;
  return {
    total: assets.computers,
    inUse: assets.inUse,
    idle: assets.idle,
    attention: assets.attention,
    active: assets.employees,
    nonAsset: assets.nonAssetItems,
    inUseRate: assets.computers ? Math.round((assets.inUse / assets.computers) * 100) : 0,
    rootOrgs: assets.rootOrgs,
  };
});

const service = computed(() => summary.value.service ?? {});
const openTickets = computed(() => service.value.openTickets ?? 0);
const pendingApprovals = computed(() => service.value.pendingApprovals ?? 0);
const slaBreached = computed(() => service.value.slaBreached ?? 0);
const runningInspections = computed(() => summary.value.inspection?.running ?? 0);
const submittedInspections = computed(() => summary.value.inspection?.submitted ?? 0);

interface TodoItem {
  key: string;
  label: string;
  count: number;
  path: string;
  hint: string;
  urgent?: boolean;
}

const todos = computed<TodoItem[]>(() => {
  const items: TodoItem[] = [];
  const add = (enabled: boolean, item: TodoItem) => {
    if (enabled && item.count > 0) items.push(item);
  };
  add(Boolean(slaBreached.value), {
    key: "sla",
    label: "工单 SLA 超时",
    count: slaBreached.value,
    path: "/tickets",
    hint: "已超过响应或解决时限",
    urgent: true,
  });
  add(hasPermission("tickets"), {
    key: "tickets",
    label: "待处理工单",
    count: openTickets.value,
    path: "/tickets",
    hint: "新建 / 处理中 / 挂起",
  });
  add(hasPermission("approvals"), {
    key: "approvals",
    label: "待我审批",
    count: pendingApprovals.value,
    path: "/service-management",
    hint: "等待审批意见",
    urgent: true,
  });
  add(hasPermission("inspection_management"), {
    key: "inspection",
    label: "机房巡检待办",
    count: runningInspections.value,
    path: "/inspection",
    hint: "进行中的巡检任务",
  });
  add(hasPermission("it_assets"), {
    key: "attention",
    label: "待关注资产",
    count: metrics.value.attention,
    path: "/computers",
    hint: "维修 / 丢失 / 待报废状态",
  });
  add(hasPermission("quality"), {
    key: "quality",
    label: "数据质量待处理",
    count: summary.value.quality?.open ?? 0,
    path: "/governance",
    hint: "影响数据完整性的问题",
  });
  add(hasPermission("changes"), {
    key: "changes",
    label: "进行中变更",
    count: service.value.changes ?? 0,
    path: "/service-management",
    hint: "变更执行进度跟踪",
  });
  add(hasPermission("problems"), {
    key: "problems",
    label: "问题记录",
    count: service.value.problems ?? 0,
    path: "/service-management",
    hint: "待定位或待关闭的问题",
  });
  return items.sort((left, right) => Number(Boolean(right.urgent)) - Number(Boolean(left.urgent)));
});

const quickActions = computed(() => {
  const actions: Array<{ key: string; label: string; path: string }> = [];
  const add = (allowed: boolean, action: { key: string; label: string; path: string }) => {
    if (allowed) actions.push(action);
  };
  add(hasPermission("it_assets", "create"), {
    key: "computer",
    label: "新建办公终端",
    path: "/computers",
  });
  add(hasPermission("tickets", "create"), { key: "ticket", label: "创建工单", path: "/tickets" });
  add(hasPermission("employees", "create"), {
    key: "employee",
    label: "新增使用人员",
    path: "/employees",
  });
  add(hasPermission("inventory_catalog", "create"), {
    key: "receipt",
    label: "物资入库",
    path: "/inventory",
  });
  add(hasPermission("inspection_management", "create"), {
    key: "inspection",
    label: "发起机房巡检",
    path: "/inspection",
  });
  add(hasPermission("rack_layout"), {
    key: "datacenter",
    label: "设备台账",
    path: "/datacenter-devices",
  });
  add(hasPermission("audit_logs"), { key: "audit", label: "操作日志", path: "/audit" });
  add(hasPermission("quality", "update"), {
    key: "quality",
    label: "数据质量检查",
    path: "/governance",
  });
  return actions;
});

const unreadNotifications = computed(() => summary.value.notifications?.unread ?? 0);

const recentNotifications = computed(() => summary.value.notifications?.recent ?? []);

const ticketStatusSummary = computed(() =>
  Object.entries(service.value.ticketStatus ?? {}).map(([status, count]) => ({ status, count })),
);

const ticketTotal = computed(() =>
  ticketStatusSummary.value.reduce((total, item) => total + Number(item.count || 0), 0),
);
const ticketCompleted = computed(() =>
  ticketStatusSummary.value
    .filter((item) => item.status === "resolved" || item.status === "closed")
    .reduce((total, item) => total + Number(item.count || 0), 0),
);
const ticketCompletionRate = computed(() =>
  ticketTotal.value ? Math.round((ticketCompleted.value / ticketTotal.value) * 100) : 0,
);

const inspectionRate = computed(() => {
  const total = runningInspections.value + submittedInspections.value;
  return total ? Math.round((submittedInspections.value / total) * 100) : 0;
});

const myAssets = computed(() => summary.value.myAssets);
const recentComputers = computed(() => summary.value.recentComputers);
const recentInbound = computed(() => summary.value.recentInbound);
const qualityTop = computed(() => summary.value.quality?.top ?? []);
const visibleModuleKeys = computed(() => new Set(modules.value.map((item) => item.key)));
const showTodos = computed(() => visibleModuleKeys.value.has("todos"));
const showProgress = computed(() => visibleModuleKeys.value.has("progress"));
const showAssets = computed(() => visibleModuleKeys.value.has("assets"));
const showQuickActions = computed(() => visibleModuleKeys.value.has("quickActions"));
const showNotifications = computed(() => visibleModuleKeys.value.has("notifications"));
const showQuality = computed(() => visibleModuleKeys.value.has("quality"));
const activityModuleOrder = ["recentAssets", "myAssets", "recentInbound"];
const activityModules = computed(() =>
  modules.value.filter((module) => activityModuleOrder.includes(module.key)),
);
const activeActivityTab = ref("recentAssets");
const qualityExpanded = ref<string[]>(["issues"]);

watch(
  () => activityModules.value.map((module) => module.key),
  (keys) => {
    if (!keys.includes(activeActivityTab.value)) activeActivityTab.value = keys[0] || "";
  },
  { immediate: true },
);

function moduleTitle(key: string, fallback: string): string {
  return modules.value.find((module) => module.key === key)?.title || fallback;
}

function hardwareSummary(row: { deviceType: string; brand: string; model: string }): string {
  return [deviceTypeLabel(row.deviceType), [row.brand, row.model].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(" · ");
}

async function load(force = false): Promise<void> {
  summary.value = await fetchWorkbench(force);
}

async function refresh(): Promise<void> {
  refreshing.value = true;
  try {
    await load(true);
    ElMessage.success("工作台数据已刷新。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "刷新失败。");
  } finally {
    refreshing.value = false;
  }
}

function openCustomize(): void {
  const visibleKeys = modules.value.map((item) => item.key);
  const permitted = availableModules();
  const ordered = [
    ...permitted.filter((item) => visibleKeys.includes(item.key)),
    ...permitted.filter((item) => !visibleKeys.includes(item.key)),
  ];
  draft.value = ordered.map((item) => ({
    key: item.key,
    title: item.title,
    visible: visibleKeys.includes(item.key),
  }));
  customizing.value = true;
}

function moveModule(index: number, delta: number): void {
  const target = index + delta;
  if (target < 0 || target >= draft.value.length) return;
  const next = [...draft.value];
  [next[index], next[target]] = [next[target], next[index]];
  draft.value = next;
}

function applyCustomize(): void {
  const order = draft.value.map((item) => item.key);
  const hidden = draft.value.filter((item) => !item.visible).map((item) => item.key);
  savePrefs(userKey.value, { order, hidden });
  modules.value = resolveModules(userKey.value);
  customizing.value = false;
  ElMessage.success("工作台布局已保存。");
}

function restoreDefault(): void {
  resetPrefs(userKey.value);
  modules.value = resolveModules(userKey.value);
  customizing.value = false;
  ElMessage.success("已恢复默认布局。");
}

async function readNotification(id: string): Promise<void> {
  try {
    await markNotificationRead(id);
    await load(false);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "标记已读失败。");
  }
}

onMounted(async () => {
  loading.value = true;
  try {
    await load(false);
    if (loadPrefs(userKey.value).order.length === 0) {
      modules.value = resolveModules(userKey.value);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "工作台数据加载失败。");
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="oa-dashboard" v-loading="loading">
    <section class="oa-dashboard-grid oa-dashboard-top">
      <PageHeader
        class="oa-dashboard-top__main"
        :title="`${greeting}，${session.user?.displayName || session.user?.username || '同事'}`"
        :description="`${today} · 待办 ${todos.length} 项 · 未读通知 ${unreadNotifications} 条`"
      >
        <template #actions>
          <el-button :loading="refreshing" @click="refresh">刷新数据</el-button>
          <el-button @click="openCustomize">自定义工作台</el-button>
        </template>
      </PageHeader>

      <DataPanel
        v-if="showNotifications"
        class="oa-dashboard-top__notifications"
        title="系统通知"
        hint="与你相关的最近消息"
      >
        <template #actions>
          <el-tag v-if="unreadNotifications" size="small" type="danger" effect="plain">
            未读 {{ unreadNotifications }}
          </el-tag>
        </template>
        <div v-if="recentNotifications.length" class="oa-note-list">
          <div
            v-for="item in recentNotifications.slice(0, 3)"
            :key="item.id"
            class="oa-note-item"
            :class="{ 'is-unread': !item.isRead }"
          >
            <span class="oa-note-dot" />
            <span class="oa-note-main">
              <span class="oa-note-title">{{ item.title }}</span>
              <span class="oa-cell-sub">
                {{ notificationTypeLabel(item.type) }} · {{ formatDateTimeText(item.createdAt) }}
              </span>
            </span>
            <button
              v-if="!item.isRead"
              type="button"
              class="oa-note-action"
              @click="readNotification(item.id)"
            >
              标记已读
            </button>
          </div>
        </div>
        <EmptyHint v-else description="暂无通知" :size="52" />
      </DataPanel>
    </section>

    <section
      v-if="showAssets || showQuickActions"
      class="oa-dashboard-grid oa-dashboard-core"
    >
      <div v-if="showAssets" class="oa-dashboard-core__metrics">
        <MetricCard
          label="办公终端资产"
          :value="metrics.total"
          :hint="`${metrics.active} 名使用人员 · ${metrics.rootOrgs} 个根组织`"
          clickable
          @click="router.push('/computers')"
        />
        <MetricCard
          label="在用设备"
          :value="metrics.inUse"
          :hint="`在用率 ${metrics.inUseRate}%`"
          tone="success"
          clickable
          @click="router.push('/computers')"
        />
        <MetricCard
          label="闲置可用"
          :value="metrics.idle"
          hint="可用于新人员配置"
          clickable
          @click="router.push('/computers')"
        />
        <MetricCard
          label="待关注"
          :value="metrics.attention"
          tone="warning"
          :hint="`${metrics.nonAsset} 件非资产设备在账`"
          clickable
          @click="router.push('/computers')"
        />
      </div>

      <DataPanel
        v-if="showQuickActions"
        class="oa-dashboard-core__quick"
        :title="moduleTitle('quickActions', '快捷入口')"
        hint="按权限提供的常用操作"
      >
        <div v-if="quickActions.length" class="oa-quick-grid">
          <el-button
            v-for="action in quickActions"
            :key="action.key"
            class="oa-quick-action"
            @click="router.push(action.path)"
          >
            {{ action.label }}
          </el-button>
        </div>
        <EmptyHint v-else description="当前账号没有可用的快捷操作" :size="52" />
      </DataPanel>
    </section>

    <section
      v-if="showTodos || showProgress || activityModules.length"
      class="oa-dashboard-grid oa-dashboard-workspace"
    >
      <DataPanel
        v-if="showTodos || showProgress"
        class="oa-dashboard-workspace__tasks"
        :title="showTodos ? '待办与进度' : moduleTitle('progress', '处理进度')"
        hint="工单、巡检与待处理事项"
      >
        <template #actions>
          <el-tag v-if="showTodos && todos.length" size="small" type="warning" effect="plain">
            {{ todos.length }} 项待办
          </el-tag>
        </template>

        <div v-if="showProgress" class="oa-progress-summary">
          <div v-if="hasPermission('tickets')" class="oa-progress-card">
            <div class="oa-progress-card__head">
              <span>工单完成率</span>
              <strong class="oa-tabular">{{ ticketCompletionRate }}%</strong>
            </div>
            <el-progress
              :percentage="ticketCompletionRate"
              :stroke-width="8"
              :show-text="false"
            />
            <div class="oa-progress-card__meta">
              <span>{{ ticketCompleted }} / {{ ticketTotal }} 已解决或关闭</span>
              <span v-if="slaBreached" class="oa-danger-text">SLA 超时 {{ slaBreached }}</span>
            </div>
          </div>

          <div v-if="hasPermission('inspection_management')" class="oa-progress-card">
            <div class="oa-progress-card__head">
              <span>巡检完成率</span>
              <strong class="oa-tabular">{{ inspectionRate }}%</strong>
            </div>
            <el-progress :percentage="inspectionRate" :stroke-width="8" :show-text="false" />
            <div class="oa-progress-card__meta">
              <span>{{ submittedInspections }} / {{ runningInspections + submittedInspections }}</span>
              <span>进行中 {{ runningInspections }}</span>
            </div>
          </div>
        </div>

        <div v-if="showProgress && hasPermission('tickets')" class="oa-ticket-status">
          <span class="oa-section-label">工单状态</span>
          <div class="oa-tag-row">
            <StatusTag
              v-for="item in ticketStatusSummary"
              :key="item.status"
              :value="item.status"
              kind="ticket"
            />
            <span v-if="!ticketStatusSummary.length" class="oa-cell-sub">暂无工单</span>
          </div>
        </div>

        <div v-if="showProgress && hasPermission('approvals')" class="oa-inline-summary">
          <span>待审批事项</span>
          <strong class="oa-tabular">{{ pendingApprovals }}</strong>
        </div>

        <div v-if="showTodos" class="oa-task-section">
          <div class="oa-task-section__head">
            <span class="oa-section-label">待办事项</span>
            <span class="oa-cell-sub">按紧急程度排序</span>
          </div>
          <div v-if="todos.length" class="oa-todo-list">
            <div
              v-for="item in todos"
              :key="item.key"
              class="oa-todo-item"
              role="button"
              tabindex="0"
              @click="router.push(item.path)"
              @keydown.enter="router.push(item.path)"
              @keydown.space.prevent="router.push(item.path)"
            >
              <span class="oa-todo-dot" :class="item.urgent ? 'is-urgent' : ''" />
              <div class="oa-todo-main">
                <div>{{ item.label }}</div>
                <div class="oa-cell-sub">{{ item.hint }}</div>
              </div>
              <strong :class="item.urgent ? 'oa-todo-count is-urgent' : 'oa-todo-count'">
                {{ item.count }}
              </strong>
            </div>
          </div>
          <EmptyHint v-else description="当前没有待办事项" :size="52" />
        </div>

        <EmptyHint
          v-if="
            showProgress &&
            !hasPermission('tickets') &&
            !hasPermission('approvals') &&
            !hasPermission('inspection_management')
          "
          description="当前账号没有可查看的进度数据"
          :size="52"
        />
      </DataPanel>

      <DataPanel
        v-if="activityModules.length"
        class="oa-dashboard-workspace__activity"
        title="最近动态"
        hint="资产登记、名下设备与物资入库"
      >
        <el-tabs v-model="activeActivityTab" class="oa-activity-tabs">
          <el-tab-pane
            v-for="module in activityModules"
            :key="module.key"
            :label="module.title"
            :name="module.key"
          >
            <el-table
              v-if="module.key === 'recentAssets'"
              :data="recentComputers"
              size="small"
              empty-text="暂无办公终端记录"
            >
              <el-table-column prop="deviceName" label="设备名" min-width="150" />
              <el-table-column label="组织 / 使用人" min-width="150">
                <template #default="{ row }">
                  {{ row.orgName || "—" }} / {{ row.userName || "未分配" }}
                </template>
              </el-table-column>
              <el-table-column label="类型 / 品牌型号" min-width="170">
                <template #default="{ row }">{{ hardwareSummary(row) || "—" }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <StatusTag :value="row.status" kind="computer" />
                </template>
              </el-table-column>
            </el-table>

            <template v-else-if="module.key === 'myAssets'">
              <div v-if="!session.user?.employeeId" class="oa-cell-sub">
                当前账号未绑定人员档案，暂不显示名下设备。
              </div>
              <el-table v-else :data="myAssets" size="small" empty-text="名下暂无办公终端">
                <el-table-column prop="deviceName" label="设备名" min-width="150" />
                <el-table-column label="品牌型号" min-width="150">
                  <template #default="{ row }">
                    {{ [row.brand, row.model].filter(Boolean).join(" ") || "—" }}
                  </template>
                </el-table-column>
                <el-table-column label="位置" min-width="110">
                  <template #default="{ row }">{{ row.location || "—" }}</template>
                </el-table-column>
                <el-table-column label="状态" width="90">
                  <template #default="{ row }">
                    <StatusTag :value="row.status" kind="computer" />
                  </template>
                </el-table-column>
              </el-table>
            </template>

            <el-table
              v-else
              :data="recentInbound"
              size="small"
              empty-text="暂无物资入库记录"
            >
              <el-table-column label="物资类型" min-width="110">
                <template #default="{ row }">{{ row.typeName || "未分类物资" }}</template>
              </el-table-column>
              <el-table-column label="品牌型号" min-width="160">
                <template #default="{ row }">
                  {{ [row.brandName, row.modelName].filter(Boolean).join(" / ") || "—" }}
                </template>
              </el-table-column>
              <el-table-column label="数量" width="72" align="right">
                <template #default="{ row }">
                  <strong class="oa-success-text">+{{ Math.max(1, Number(row.quantity || 1)) }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="入库时间" min-width="150">
                <template #default="{ row }">{{ formatDateTimeText(row.occurredAt) }}</template>
              </el-table-column>
            </el-table>

            <div class="oa-panel-footer">
              <el-button
                v-if="module.key === 'recentAssets'"
                link
                type="primary"
                @click="router.push('/computers')"
              >
                查看全部资产 ›
              </el-button>
              <el-button
                v-else-if="module.key === 'myAssets'"
                link
                type="primary"
                @click="router.push('/employees')"
              >
                查看人员与设备 ›
              </el-button>
              <el-button v-else link type="primary" @click="router.push('/inventory')">
                查看物资台账 ›
              </el-button>
            </div>
          </el-tab-pane>
        </el-tabs>
      </DataPanel>
    </section>

    <DataPanel
      v-if="showQuality"
      class="oa-dashboard-quality"
      :title="moduleTitle('quality', '数据质量待办')"
      hint="待处理的数据问题"
    >
      <template #actions>
        <el-button link type="primary" @click="router.push('/governance')">
          前往同步与质量 ›
        </el-button>
      </template>
      <div v-if="qualityTop.length" class="oa-quality-summary">
        <div>
          <strong class="oa-tabular">{{ summary.quality?.open ?? qualityTop.length }}</strong>
          <span>项数据质量问题待处理</span>
        </div>
        <el-tag size="small" type="warning" effect="plain">
          展示最近 {{ qualityTop.length }} 项
        </el-tag>
      </div>
      <el-collapse v-if="qualityTop.length" v-model="qualityExpanded" class="oa-quality-collapse">
        <el-collapse-item title="展开查看待处理问题" name="issues">
          <div class="oa-quality-list">
            <div v-for="issue in qualityTop" :key="issue.id" class="oa-quality-item">
              <span class="oa-quality-dot" />
              <div class="oa-quality-main">
                <div>{{ issue.title }}</div>
                <div class="oa-cell-sub">
                  {{ issue.severityLabel }} · {{ issue.ruleLabel }} ·
                  {{ issue.entityTypeLabel }} · {{ formatDateTimeText(issue.firstDetectedAt) }}
                </div>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
      <EmptyHint v-else description="数据质量良好，暂无待处理问题" :size="52" />
    </DataPanel>

    <DetailDrawer v-model="customizing" title="自定义工作台" size="md">
      <p class="oa-cell-sub">
        模块会按你的角色权限过滤，显隐立即生效；最近动态页签按你设置的顺序排列，配置仅保存在本机浏览器。
      </p>
      <div class="oa-customize-list">
        <div v-for="(item, index) in draft" :key="item.key" class="oa-customize-item">
          <el-switch v-model="item.visible" />
          <span class="oa-customize-title">{{ item.title }}</span>
          <el-button link :disabled="index === 0" @click="moveModule(index, -1)">上移</el-button>
          <el-button
            link
            :disabled="index === draft.length - 1"
            @click="moveModule(index, 1)"
          >
            下移
          </el-button>
        </div>
      </div>
      <template #footer>
        <div class="oa-drawer-footer">
          <el-button @click="restoreDefault">恢复默认</el-button>
          <div class="oa-button-row">
            <el-button @click="customizing = false">取消</el-button>
            <el-button type="primary" @click="applyCustomize">保存</el-button>
          </div>
        </div>
      </template>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.oa-dashboard {
  --oa-dashboard-gap: var(--oa-space-4);
  --oa-dashboard-padding: var(--oa-space-5);
  --oa-dashboard-radius: var(--oa-radius-lg);
  display: flex;
  flex-direction: column;
  gap: var(--oa-dashboard-gap);
  min-width: 0;
}

.oa-dashboard-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: var(--oa-dashboard-gap);
  align-items: stretch;
}

.oa-dashboard :deep(.el-card) {
  border-radius: var(--oa-dashboard-radius);
  box-shadow: 0 2px 10px rgba(31, 45, 61, 0.06);
}

.oa-dashboard :deep(.el-card__body) {
  padding: var(--oa-dashboard-padding);
}

.oa-dashboard :deep(.el-card__header) {
  padding: var(--oa-dashboard-padding) var(--oa-dashboard-padding) 0;
  border-bottom: 0;
}

.oa-dashboard :deep(.oa-panel) {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.oa-dashboard :deep(.oa-panel > .el-card__body) {
  flex: 1 1 auto;
}

.oa-dashboard :deep(.oa-panel__title strong) {
  font-size: var(--oa-font-lg);
  font-weight: 700;
}

.oa-dashboard :deep(.el-empty) {
  padding: var(--oa-space-3) 0;
}

.oa-dashboard :deep(.el-empty__description) {
  margin-top: var(--oa-space-2);
}

.oa-dashboard-top__main {
  grid-column: span 8;
  height: 100%;
}

.oa-dashboard-top__main :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
}

.oa-dashboard-top__notifications {
  grid-column: span 4;
}

.oa-dashboard-core__metrics {
  grid-column: span 8;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--oa-dashboard-gap);
}

.oa-dashboard-core__metrics :deep(.oa-metric) {
  height: 100%;
}

.oa-dashboard-core__metrics :deep(.oa-metric .el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
}

.oa-dashboard-core__metrics :deep(.oa-metric__hint) {
  margin-top: auto;
}

.oa-dashboard-core__quick {
  grid-column: span 4;
}

.oa-dashboard-workspace__tasks,
.oa-dashboard-workspace__activity {
  grid-column: span 6;
}

.oa-dashboard-workspace__activity :deep(.oa-panel > .el-card__body) {
  display: flex;
  flex-direction: column;
}

.oa-dashboard-quality {
  grid-column: span 12;
}

.oa-quick-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--oa-space-2);
}

.oa-quick-action {
  width: 100%;
  height: 36px;
  margin: 0;
  padding: 0 var(--oa-space-2);
  justify-content: center;
  border-radius: var(--oa-radius-md);
  font-size: var(--oa-font-sm);
}

.oa-todo-list,
.oa-note-list,
.oa-quality-list,
.oa-customize-list {
  display: flex;
  flex-direction: column;
  gap: var(--oa-space-2);
}

.oa-todo-item,
.oa-note-item,
.oa-customize-item {
  display: flex;
  gap: var(--oa-space-3);
  align-items: center;
  border: var(--oa-border);
  border-radius: var(--oa-radius-md);
}

.oa-todo-item,
.oa-note-item {
  padding: var(--oa-space-2) var(--oa-space-3);
}

.oa-customize-item {
  padding: var(--oa-space-2) var(--oa-space-3);
}

.oa-todo-item {
  cursor: pointer;
  transition:
    border-color 150ms ease,
    background 150ms ease;
}

.oa-todo-item:hover {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-fill-color-lighter);
}

.oa-note-item {
  width: 100%;
  color: inherit;
  font: inherit;
  text-align: left;
  background: transparent;
  cursor: default;
}

.oa-note-item.is-unread {
  background: var(--el-color-danger-light-9);
  border-color: var(--el-color-danger-light-7);
}

.oa-note-dot {
  flex: none;
  width: var(--oa-space-2);
  height: var(--oa-space-2);
  border-radius: 50%;
  background: var(--el-color-info-light-5);
}

.oa-note-item.is-unread .oa-note-dot {
  background: var(--el-color-danger);
}

.oa-note-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.oa-note-title {
  overflow: hidden;
  font-size: var(--oa-font-sm);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.oa-note-action {
  flex: none;
  padding: 0;
  color: var(--el-color-primary);
  font-size: var(--oa-font-xs);
  background: transparent;
  border: 0;
  cursor: pointer;
}

.oa-todo-dot {
  flex: none;
  width: var(--oa-space-2);
  height: var(--oa-space-2);
  border-radius: 50%;
  background: var(--el-color-primary);
}

.oa-todo-dot.is-urgent {
  background: var(--el-color-danger);
}

.oa-todo-main,
.oa-note-main {
  flex: 1;
  min-width: 0;
}

.oa-todo-count.is-urgent,
.oa-danger-text {
  color: var(--el-color-danger);
}

.oa-warning-text {
  color: var(--el-color-warning);
}

.oa-success-text {
  color: var(--el-color-success);
}

.oa-progress-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--oa-dashboard-gap);
}

.oa-progress-card {
  padding: var(--oa-space-4);
  background: var(--el-fill-color-lighter);
  border: var(--oa-border);
  border-radius: var(--oa-radius-lg);
}

.oa-progress-card__head,
.oa-progress-card__meta,
.oa-inline-summary,
.oa-task-section__head,
.oa-quality-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oa-space-3);
}

.oa-progress-card__head {
  margin-bottom: var(--oa-space-3);
  font-size: var(--oa-font-sm);
}

.oa-progress-card__head strong {
  font-size: var(--oa-font-lg);
}

.oa-progress-card__meta {
  margin-top: var(--oa-space-2);
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-xs);
}

.oa-ticket-status {
  margin-top: var(--oa-space-4);
}

.oa-section-label {
  color: var(--oa-text-primary);
  font-size: var(--oa-font-sm);
  font-weight: 600;
}

.oa-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-1);
}

.oa-ticket-status .oa-tag-row {
  margin-top: var(--oa-space-2);
}

.oa-inline-summary {
  margin-top: var(--oa-space-3);
  padding: var(--oa-space-3) var(--oa-space-4);
  background: var(--el-fill-color-lighter);
  border-radius: var(--oa-radius-md);
  font-size: var(--oa-font-sm);
}

.oa-task-section {
  margin-top: var(--oa-space-5);
  padding-top: var(--oa-space-5);
  border-top: var(--oa-border);
}

.oa-task-section__head {
  margin-bottom: var(--oa-space-3);
}

.oa-activity-tabs :deep(.el-tabs__header) {
  margin-bottom: var(--oa-space-4);
}

.oa-panel-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--oa-space-3);
}

.oa-quality-summary {
  padding: var(--oa-space-3) var(--oa-space-4);
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: var(--oa-radius-md);
}

.oa-quality-summary > div {
  display: flex;
  align-items: baseline;
  gap: var(--oa-space-2);
}

.oa-quality-summary strong {
  color: var(--el-color-warning-dark-2);
  font-size: var(--oa-font-xl);
}

.oa-quality-summary span {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-sm);
}

.oa-quality-collapse {
  margin-top: var(--oa-space-3);
  border-top: 0;
  border-bottom: 0;
}

.oa-quality-item {
  display: flex;
  gap: var(--oa-space-3);
  align-items: flex-start;
  padding: var(--oa-space-2) 0;
}

.oa-quality-dot {
  flex: none;
  width: 6px;
  height: 6px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--el-color-warning);
}

.oa-quality-main {
  min-width: 0;
}

.oa-customize-title {
  flex: 1;
}

.oa-drawer-footer {
  display: flex;
  justify-content: space-between;
}

@media (max-width: 1199px) {
  .oa-dashboard-top__main,
  .oa-dashboard-top__notifications,
  .oa-dashboard-core__metrics,
  .oa-dashboard-core__quick {
    grid-column: span 12;
  }

  .oa-quick-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 991px) {
  .oa-dashboard-core__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .oa-dashboard-workspace__tasks,
  .oa-dashboard-workspace__activity {
    grid-column: span 12;
  }

  .oa-quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .oa-dashboard {
    --oa-dashboard-gap: var(--oa-space-4);
    --oa-dashboard-padding: var(--oa-space-5);
  }

  .oa-progress-summary {
    grid-template-columns: 1fr;
  }

  .oa-quality-summary {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 479px) {
  .oa-dashboard-core__metrics,
  .oa-quick-grid {
    grid-template-columns: 1fr;
  }

  .oa-note-action {
    display: none;
  }
}
</style>
