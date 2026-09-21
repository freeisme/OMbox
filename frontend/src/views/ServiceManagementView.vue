<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  PRIORITY_OPTIONS,
  createChange,
  createKnowledge,
  createProblem,
  createSlaPolicy,
  decideApproval,
  fetchApprovals,
  fetchChanges,
  fetchKnowledge,
  fetchNotifications,
  fetchProblems,
  fetchSlaPolicies,
  markNotificationRead,
  type ApprovalRow,
  type ChangeRow,
  type KnowledgeRow,
  type NotificationRow,
  type ProblemRow,
  type SlaPolicyRow,
} from "../api/service";
import { formatDateTimeText, notificationTypeLabel } from "../labels";
import { hasPermission } from "../session";
import DataPanel from "../components/ui/DataPanel.vue";
import PageHeader from "../components/ui/PageHeader.vue";

interface ServiceTab {
  key: string;
  label: string;
  module: string;
}

const TABS: ServiceTab[] = [
  { key: "changes", label: "变更", module: "changes" },
  { key: "problems", label: "问题", module: "problems" },
  { key: "knowledge", label: "知识库", module: "knowledge" },
  { key: "policies", label: "SLA 策略", module: "sla" },
  { key: "approvals", label: "审批", module: "approvals" },
  { key: "notifications", label: "通知", module: "notifications" },
];

const activeTab = ref("");
const loading = ref(false);
const saving = ref(false);
const changes = ref<ChangeRow[]>([]);
const problems = ref<ProblemRow[]>([]);
const articles = ref<KnowledgeRow[]>([]);
const policies = ref<SlaPolicyRow[]>([]);
const approvals = ref<ApprovalRow[]>([]);
const notifications = ref<NotificationRow[]>([]);

const createVisible = ref(false);
const form = reactive({
  title: "",
  description: "",
  type: "normal",
  impact: "medium",
  risk: "medium",
  content: "",
  name: "",
  priority: "medium",
  responseMinutes: 60,
  resolutionMinutes: 480,
});

const visibleTabs = computed(() => TABS.filter((tab) => hasPermission(tab.module)));
const canCreate = computed(() => {
  if (activeTab.value === "changes") return hasPermission("changes", "create");
  if (activeTab.value === "problems") return hasPermission("problems", "create");
  if (activeTab.value === "knowledge") return hasPermission("knowledge", "create");
  if (activeTab.value === "policies") return hasPermission("sla", "create");
  return false;
});

function priorityLabel(value?: string): string {
  return PRIORITY_OPTIONS.find((item) => item.value === value)?.label || value || "—";
}

async function loadTab(): Promise<void> {
  loading.value = true;
  try {
    if (activeTab.value === "changes") changes.value = await fetchChanges();
    else if (activeTab.value === "problems") problems.value = await fetchProblems();
    else if (activeTab.value === "knowledge") articles.value = await fetchKnowledge();
    else if (activeTab.value === "policies") policies.value = await fetchSlaPolicies();
    else if (activeTab.value === "approvals") approvals.value = await fetchApprovals();
    else if (activeTab.value === "notifications") notifications.value = await fetchNotifications();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "数据加载失败。");
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  form.title = "";
  form.description = "";
  form.type = "normal";
  form.impact = "medium";
  form.risk = "medium";
  form.content = "";
  form.name = "";
  form.priority = "medium";
  form.responseMinutes = 60;
  form.resolutionMinutes = 480;
  createVisible.value = true;
}

async function submitCreate(): Promise<void> {
  saving.value = true;
  try {
    if (activeTab.value === "changes") {
      if (!form.title.trim()) throw new Error("请填写变更标题。");
      await createChange({
        title: form.title.trim(),
        description: form.description.trim(),
        type: form.type,
        impact: form.impact,
        risk: form.risk,
      });
    } else if (activeTab.value === "problems") {
      if (!form.title.trim()) throw new Error("请填写问题标题。");
      await createProblem({
        title: form.title.trim(),
        description: form.description.trim(),
        impact: form.impact,
      });
    } else if (activeTab.value === "knowledge") {
      if (!form.title.trim()) throw new Error("请填写文章标题。");
      await createKnowledge({ title: form.title.trim(), content: form.content.trim() });
    } else if (activeTab.value === "policies") {
      if (!form.name.trim()) throw new Error("请填写策略名称。");
      await createSlaPolicy({
        name: form.name.trim(),
        priority: form.priority,
        responseMinutes: Number(form.responseMinutes),
        resolutionMinutes: Number(form.resolutionMinutes),
      });
    }
    ElMessage.success("已创建。");
    createVisible.value = false;
    await loadTab();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建失败。");
  } finally {
    saving.value = false;
  }
}

async function decide(row: ApprovalRow, decision: "approved" | "rejected"): Promise<void> {
  let comment = "";
  if (decision === "rejected") {
    try {
      const result = await ElMessageBox.prompt("请填写驳回原因", "驳回审批", {
        confirmButtonText: "确认驳回",
        cancelButtonText: "取消",
      });
      comment = result.value ?? "";
    } catch {
      return;
    }
  }
  try {
    await decideApproval(row.id, decision, comment);
    ElMessage.success(decision === "approved" ? "已通过。" : "已驳回。");
    await loadTab();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批失败。");
  }
}

async function readNotification(row: NotificationRow): Promise<void> {
  try {
    await markNotificationRead(row.id);
    await loadTab();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "标记已读失败。");
  }
}

onMounted(async () => {
  activeTab.value = visibleTabs.value[0]?.key ?? "changes";
  await loadTab();
});
</script>

<template>
  <PageHeader
    title="服务管理"
    description="变更、问题、知识库、SLA、审批与通知；工单请使用「工单」页面"
  >
    <template #actions>
      <el-button @click="loadTab">刷新</el-button>
      <el-button v-if="canCreate" type="primary" @click="openCreate">新建</el-button>
    </template>
    <template #filters>
      <el-tabs v-model="activeTab" @tab-change="loadTab">
        <el-tab-pane v-for="tab in visibleTabs" :key="tab.key" :label="tab.label" :name="tab.key" />
      </el-tabs>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      v-if="activeTab === 'changes'"
      :data="changes"
      size="small"
      border
      empty-text="暂无变更"
    >
      <el-table-column prop="number" label="编号" width="140" />
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">{{ row.type || "—" }}</template>
      </el-table-column>
      <el-table-column label="影响 / 风险" width="130">
        <template #default="{ row }">
          {{ priorityLabel(row.impact) }} / {{ priorityLabel(row.risk) }}
        </template>
      </el-table-column>
      <el-table-column prop="assignedToName" label="负责人" width="110" />
    </el-table>

    <el-table
      v-else-if="activeTab === 'problems'"
      :data="problems"
      size="small"
      border
      empty-text="暂无问题记录"
    >
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column label="影响" width="90">
        <template #default="{ row }">{{ priorityLabel(row.impact) }}</template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
    </el-table>

    <el-table
      v-else-if="activeTab === 'knowledge'"
      :data="articles"
      size="small"
      border
      empty-text="暂无知识库文章"
    >
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column prop="visibility" label="可见范围" width="120" />
      <el-table-column prop="ownerName" label="负责人" width="120" />
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.updatedAt || row.publishedAt) }}</template>
      </el-table-column>
    </el-table>

    <el-table
      v-else-if="activeTab === 'policies'"
      :data="policies"
      size="small"
      border
      empty-text="暂无 SLA 策略"
    >
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="优先级" width="90">
        <template #default="{ row }">{{ priorityLabel(row.priority) }}</template>
      </el-table-column>
      <el-table-column prop="responseMinutes" label="响应（分钟）" width="120" />
      <el-table-column prop="resolutionMinutes" label="解决（分钟）" width="120" />
    </el-table>

    <el-table
      v-else-if="activeTab === 'approvals'"
      :data="approvals"
      size="small"
      border
      empty-text="暂无审批事项"
    >
      <el-table-column prop="recordType" label="类型" width="90" />
      <el-table-column prop="title" label="事项" min-width="200" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="requestedByName" label="申请人" width="120" />
      <el-table-column label="提交时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button link type="primary" @click="decide(row, 'approved')">通过</el-button>
            <el-button link type="danger" @click="decide(row, 'rejected')">驳回</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <el-table
      v-else-if="activeTab === 'notifications'"
      :data="notifications"
      size="small"
      border
      empty-text="暂无通知"
    >
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.isRead ? 'info' : 'danger'" effect="plain">
            {{ notificationTypeLabel(row.type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="200" />
      <el-table-column prop="content" label="内容" min-width="240" show-overflow-tooltip />
      <el-table-column label="时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button v-if="!row.isRead" link type="primary" @click="readNotification(row)">
            标记已读
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataPanel>

  <FormDialog
    v-model="createVisible"
    :title="
      activeTab === 'changes'
        ? '新建变更'
        : activeTab === 'problems'
          ? '新建问题'
          : activeTab === 'knowledge'
            ? '新建知识库文章'
            : '新建 SLA 策略'
    "
    size="md"
    confirm-text="创建"
    :loading="saving"
    @confirm="submitCreate"
  >
    <el-form label-position="top">
      <template v-if="activeTab === 'policies'">
        <el-form-item label="策略名称" required><el-input v-model="form.name" /></el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="8">
            <el-form-item label="优先级">
              <el-select v-model="form.priority" class="oa-full-width">
                <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="响应时限（分钟）">
              <el-input-number v-model="form.responseMinutes" :min="1" class="oa-full-width" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="解决时限（分钟）">
              <el-input-number v-model="form.resolutionMinutes" :min="1" class="oa-full-width" />
            </el-form-item>
          </el-col>
        </el-row>
      </template>
      <template v-else>
        <el-form-item label="标题" required><el-input v-model="form.title" /></el-form-item>
        <el-form-item v-if="activeTab === 'knowledge'" label="正文">
          <el-input v-model="form.content" type="textarea" :rows="5" />
        </el-form-item>
        <template v-else>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="3" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col v-if="activeTab === 'changes'" :span="8">
              <el-form-item label="类型">
                <el-select v-model="form.type" class="oa-full-width">
                  <el-option label="标准" value="standard" />
                  <el-option label="常规" value="normal" />
                  <el-option label="紧急" value="emergency" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="影响">
                <el-select v-model="form.impact" class="oa-full-width">
                  <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col v-if="activeTab === 'changes'" :span="8">
              <el-form-item label="风险">
                <el-select v-model="form.risk" class="oa-full-width">
                  <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </template>
      </template>
    </el-form>
  </FormDialog>
</template>
