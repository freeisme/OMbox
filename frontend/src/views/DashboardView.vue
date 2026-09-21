<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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
    hint: "维修 / 丢失 / 报废状态",
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

const inspectionRate = computed(() => {
  const total = runningInspections.value + submittedInspections.value;
  return total ? Math.round((submittedInspections.value / total) * 100) : 0;
});

const myAssets = computed(() => summary.value.myAssets);
const recentComputers = computed(() => summary.value.recentComputers);
const recentInbound = computed(() => summary.value.recentInbound);
const qualityTop = computed(() => summary.value.quality?.top ?? []);

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
  <PageHeader
    :title="`${greeting}，${session.user?.displayName || session.user?.username || '同事'}`"
    :description="`${today} · 待办 ${todos.length} 项 · 未读通知 ${unreadNotifications} 条`"
    v-loading="loading"
  >
    <template #actions>
      <el-button :loading="refreshing" @click="refresh">刷新数据</el-button>
      <el-button @click="openCustomize">自定义工作台</el-button>
    </template>
  </PageHeader>

  <el-row :gutter="12" class="oa-panel-gap">
    <el-col
      v-for="module in modules"
      :key="module.key"
      :xs="24"
      :sm="module.span === 12 ? 24 : 12"
      :md="module.span"
      class="oa-module-col"
    >
      <DataPanel :title="module.title" :hint="module.hint">
        <template #actions>
          <el-tag
            v-if="module.key === 'notifications' && unreadNotifications"
            size="small"
            type="danger"
          >
            未读 {{ unreadNotifications }}
          </el-tag>
          <el-tag v-else-if="module.key === 'todos' && todos.length" size="small" type="warning">
            {{ todos.length }} 项
          </el-tag>
        </template>

        <template v-if="module.key === 'todos'">
          <div v-if="todos.length" class="oa-todo-list">
            <div
              v-for="item in todos"
              :key="item.key"
              class="oa-todo-item"
              role="button"
              tabindex="0"
              @click="router.push(item.path)"
              @keyup.enter="router.push(item.path)"
              @keyup.space="router.push(item.path)"
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
          <EmptyHint v-else description="当前没有待办事项" />
        </template>

        <template v-else-if="module.key === 'quickActions'">
          <div v-if="quickActions.length" class="oa-button-row">
            <el-button v-for="action in quickActions" :key="action.key" @click="router.push(action.path)">
              {{ action.label }}
            </el-button>
          </div>
          <EmptyHint v-else description="当前账号没有可用的快捷操作" :size="60" />
        </template>

        <template v-else-if="module.key === 'assets'">
          <el-row :gutter="12">
            <el-col :xs="12" :md="6">
              <MetricCard
                label="办公终端资产"
                :value="metrics.total"
                :hint="`在用 ${metrics.inUseRate}% · ${metrics.inUse} 台在用`"
              />
            </el-col>
            <el-col :xs="12" :md="6">
              <MetricCard
                label="使用人员"
                :value="metrics.active"
                :hint="`${metrics.rootOrgs} 个根组织`"
              />
            </el-col>
            <el-col :xs="12" :md="6">
              <MetricCard label="闲置可用" :value="metrics.idle" hint="可用于新人员配置" />
            </el-col>
            <el-col :xs="12" :md="6">
              <MetricCard
                label="待关注"
                :value="metrics.attention"
                tone="warning"
                :hint="`${metrics.nonAsset} 件非资产设备在账`"
              />
            </el-col>
          </el-row>
        </template>

        <template v-else-if="module.key === 'notifications'">
          <div v-if="recentNotifications.length" class="oa-note-list">
            <div v-for="item in recentNotifications" :key="item.id" class="oa-note-item">
              <el-tag size="small" :type="item.isRead ? 'info' : 'danger'" effect="plain">
                {{ notificationTypeLabel(item.type) }}
              </el-tag>
              <div class="oa-note-main">
                <div :class="item.isRead ? '' : 'oa-note-unread'">{{ item.title }}</div>
                <div class="oa-cell-sub">
                  {{ item.content || "—" }} · {{ formatDateTimeText(item.createdAt) }}
                </div>
              </div>
              <el-button v-if="!item.isRead" link type="primary" @click="readNotification(item.id)">
                标记已读
              </el-button>
            </div>
          </div>
          <EmptyHint v-else description="暂无通知" />
        </template>

        <template v-else-if="module.key === 'progress'">
          <template v-if="hasPermission('tickets')">
            <div class="oa-progress-row">
              <span>工单状态分布</span>
              <span v-if="slaBreached" class="oa-danger-text">SLA 超时 {{ slaBreached }}</span>
            </div>
            <div class="oa-tag-row">
              <StatusTag
                v-for="item in ticketStatusSummary"
                :key="item.status"
                :value="item.status"
                kind="ticket"
              />
              <span v-if="!ticketStatusSummary.length" class="oa-cell-sub">暂无工单</span>
            </div>
          </template>
          <div v-if="hasPermission('approvals')" class="oa-progress-row">
            <span>待审批事项</span><strong>{{ pendingApprovals }}</strong>
          </div>
          <div v-if="hasPermission('inspection_management')" class="oa-progress-row-block">
            <div class="oa-progress-row">
              <span>巡检完成率</span>
              <span>{{ submittedInspections }} / {{ runningInspections + submittedInspections }}</span>
            </div>
            <el-progress :percentage="inspectionRate" :stroke-width="10" />
          </div>
          <div v-if="hasPermission('quality')" class="oa-progress-row">
            <span>数据质量问题</span>
            <strong :class="summary.quality?.open ? 'oa-warning-text' : ''">
              {{ summary.quality?.open ?? 0 }}
            </strong>
          </div>
          <EmptyHint
            v-if="
              !hasPermission('tickets') &&
              !hasPermission('approvals') &&
              !hasPermission('inspection_management') &&
              !hasPermission('quality')
            "
            description="当前账号没有可查看的进度数据"
            :size="60"
          />
        </template>

        <template v-else-if="module.key === 'recentAssets'">
          <el-table :data="recentComputers" size="small" empty-text="暂无办公终端记录">
            <el-table-column prop="deviceName" label="设备名" min-width="140" />
            <el-table-column label="所属组织" min-width="120">
              <template #default="{ row }">{{ row.orgName || "—" }}</template>
            </el-table-column>
            <el-table-column label="设备类型 / 品牌型号" min-width="160">
              <template #default="{ row }">{{ hardwareSummary(row) || "—" }}</template>
            </el-table-column>
            <el-table-column label="使用用户" width="100">
              <template #default="{ row }">{{ row.userName || "未分配" }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <StatusTag :value="row.status" kind="computer" />
              </template>
            </el-table-column>
          </el-table>
          <div class="oa-panel-footer">
            <el-button link type="primary" @click="router.push('/computers')">全部资产 ›</el-button>
          </div>
        </template>

        <template v-else-if="module.key === 'myAssets'">
          <div v-if="!session.user?.employeeId" class="oa-cell-sub">
            当前账号未绑定人员档案，暂不显示名下设备。
          </div>
          <el-table v-else :data="myAssets" size="small" empty-text="名下暂无办公终端">
            <el-table-column prop="deviceName" label="设备名" min-width="140" />
            <el-table-column label="品牌型号" min-width="140">
              <template #default="{ row }">
                {{ [row.brand, row.model].filter(Boolean).join(" ") || "—" }}
              </template>
            </el-table-column>
            <el-table-column prop="location" label="位置" min-width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <StatusTag :value="row.status" kind="computer" />
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template v-else-if="module.key === 'recentInbound'">
          <div v-if="recentInbound.length" class="oa-inbound-list">
            <div v-for="item in recentInbound" :key="item.id" class="oa-inbound-row">
              <div>
                <div>{{ item.typeName || "未分类物资" }}</div>
                <div class="oa-cell-sub">
                  {{ [item.brandName, item.modelName].filter(Boolean).join(" / ") || "未填写品牌型号" }}
                  · {{ formatDateTimeText(item.occurredAt) }} · {{ item.sourceLabel || "未标注来源" }}
                </div>
              </div>
              <strong class="oa-success-text">+{{ Math.max(1, Number(item.quantity || 1)) }}</strong>
            </div>
          </div>
          <EmptyHint v-else description="暂无物资入库记录" />
        </template>

        <template v-else-if="module.key === 'quality'">
          <div v-if="qualityTop.length" class="oa-quality-list">
            <div v-for="issue in qualityTop" :key="issue.id">
              <div>{{ issue.title }}</div>
              <div class="oa-cell-sub">
                {{ issue.severityLabel }} · {{ issue.ruleLabel }} · {{ issue.entityTypeLabel }} ·
                {{ formatDateTimeText(issue.firstDetectedAt) }}
              </div>
            </div>
          </div>
          <EmptyHint v-else description="数据质量良好，暂无待处理问题" />
          <div v-if="qualityTop.length" class="oa-panel-footer">
            <el-button link type="primary" @click="router.push('/governance')">
              前往同步与质量 ›
            </el-button>
          </div>
        </template>
      </DataPanel>
    </el-col>
  </el-row>

  <DetailDrawer v-model="customizing" title="自定义工作台" size="md">
    <p class="oa-cell-sub">
      模块会按你的角色权限过滤，顺序与显隐只影响当前账号，保存在本机浏览器。
    </p>
    <div class="oa-customize-list">
      <div v-for="(item, index) in draft" :key="item.key" class="oa-customize-item">
        <el-switch v-model="item.visible" />
        <span class="oa-customize-title">{{ item.title }}</span>
        <el-button link :disabled="index === 0" @click="moveModule(index, -1)">上移</el-button>
        <el-button link :disabled="index === draft.length - 1" @click="moveModule(index, 1)">下移</el-button>
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
</template>

<style scoped>
.oa-module-col {
  margin-bottom: var(--oa-gap);
}

.oa-todo-list,
.oa-note-list,
.oa-inbound-list,
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
  padding: var(--oa-space-2) var(--oa-space-3);
  border: var(--oa-border);
  border-radius: var(--oa-radius-md);
}

.oa-todo-item {
  cursor: pointer;
}

.oa-todo-item:hover {
  border-color: var(--el-color-primary-light-5);
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

.oa-note-unread {
  font-weight: 600;
}

.oa-progress-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--oa-space-2);
  margin-bottom: var(--oa-space-2);
  font-size: var(--oa-font-sm);
}

.oa-progress-row-block {
  margin-bottom: var(--oa-space-3);
}

.oa-tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-1);
  margin-bottom: var(--oa-space-3);
}

.oa-inbound-row {
  display: flex;
  gap: var(--oa-space-3);
  align-items: center;
  justify-content: space-between;
}

.oa-panel-footer {
  display: flex;
  justify-content: flex-end;
}

.oa-customize-title {
  flex: 1;
}

.oa-drawer-footer {
  display: flex;
  justify-content: space-between;
}
</style>
