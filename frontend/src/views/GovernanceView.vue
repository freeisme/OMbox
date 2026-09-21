<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  SYNC_RUN_STATUS_LABELS,
  applySyncRun,
  fetchQualityIssues,
  fetchSyncRuns,
  ignoreQualityIssue,
  resolveQualityIssue,
  runQualityCheck,
  type QualityIssue,
  type SyncRun,
} from "../api/governance";
import { formatDateTimeText } from "../labels";
import { hasPermission } from "../session";
import DataPanel from "../components/ui/DataPanel.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import { confirmAction } from "../composables/useConfirm";

const loading = ref(true);
const saving = ref(false);
const runs = ref<SyncRun[]>([]);
const issues = ref<QualityIssue[]>([]);
const issueStatus = ref("open");
const keyword = ref("");
const page = ref(1);
const pageSize = ref(20);

const resolveVisible = ref(false);
const resolveTarget = ref<QualityIssue | null>(null);
const resolveForm = reactive({ resolutionResult: "" });

const filteredIssues = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return issues.value;
  return issues.value.filter((issue) =>
    [issue.title, issue.ruleLabel, issue.entityTypeLabel, issue.details]
      .join(" ")
      .toLowerCase()
      .includes(key),
  );
});

const pagedIssues = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filteredIssues.value.slice(start, start + pageSize.value);
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [runList, issueList] = await Promise.all([
      hasPermission("sync") ? fetchSyncRuns() : Promise.resolve([]),
      hasPermission("quality") ? fetchQualityIssues(issueStatus.value) : Promise.resolve([]),
    ]);
    runs.value = runList;
    issues.value = issueList;
    page.value = 1;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "治理数据加载失败。");
  } finally {
    loading.value = false;
  }
}

async function applyRun(run: SyncRun): Promise<void> {
  const confirmed = await confirmAction(`确认应用同步批次「${run.sourceCode || run.id}」？`, {
    title: "应用确认",
    confirmText: "应用",
  });
  if (!confirmed) return;
  saving.value = true;
  try {
    await applySyncRun(run.id);
    ElMessage.success("同步批次已应用。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "应用失败。");
  } finally {
    saving.value = false;
  }
}

async function runCheck(): Promise<void> {
  saving.value = true;
  try {
    await runQualityCheck();
    ElMessage.success("数据质量检查已执行。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "检查失败。");
  } finally {
    saving.value = false;
  }
}

function openResolve(issue: QualityIssue): void {
  resolveTarget.value = issue;
  resolveForm.resolutionResult = "";
  resolveVisible.value = true;
}

async function submitResolve(): Promise<void> {
  const target = resolveTarget.value;
  if (!target) return;
  if (!resolveForm.resolutionResult.trim()) {
    ElMessage.warning("请填写处理结果。");
    return;
  }
  saving.value = true;
  try {
    await resolveQualityIssue(target.id, resolveForm.resolutionResult.trim());
    ElMessage.success("问题已标记为解决。");
    resolveVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "处理失败。");
  } finally {
    saving.value = false;
  }
}

async function ignoreIssue(issue: QualityIssue): Promise<void> {
  let reason = "";
  try {
    const result = await ElMessageBox.prompt("请填写忽略原因", "忽略数据质量问题", {
      confirmButtonText: "确认忽略",
      cancelButtonText: "取消",
    });
    reason = result.value ?? "";
  } catch {
    return;
  }
  try {
    await ignoreQualityIssue(issue.id, reason);
    ElMessage.success("问题已忽略。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "忽略失败。");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="同步与质量"
    description="外部数据先进入暂存区，校验通过后再由管理员应用；数据质量问题可逐条处理"
  >
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <el-button v-if="hasPermission('quality', 'update')" :loading="saving" @click="runCheck">
        运行质量检查
      </el-button>
    </template>
  </PageHeader>

  <DataPanel
    v-if="hasPermission('sync')"
    class="oa-panel-gap"
    title="同步暂存批次"
    :loading="loading"
  >
    <el-table :data="runs" size="small" border empty-text="暂无同步批次">
      <el-table-column prop="sourceCode" label="来源" width="140" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">
            {{ SYNC_RUN_STATUS_LABELS[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="recordsTotal" label="总数" width="80" />
      <el-table-column prop="recordsValid" label="有效" width="80" />
      <el-table-column prop="recordsInvalid" label="无效" width="80" />
      <el-table-column prop="recordsApplied" label="已应用" width="80" />
      <el-table-column label="开始时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.startedAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="hasPermission('sync', 'update') && row.status !== 'applied' && !row.recordsInvalid"
            link
            type="primary"
            @click="applyRun(row)"
          >
            应用
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataPanel>

  <DataPanel
    v-if="hasPermission('quality')"
    class="oa-panel-gap"
    title="数据质量问题"
    :loading="loading"
  >
    <template #actions>
      <div class="oa-flex-row">
        <el-input v-model="keyword" placeholder="标题、规则或对象" clearable style="width: 220px" />
        <el-select v-model="issueStatus" style="width: 140px" @change="load">
          <el-option label="待处理" value="open" />
          <el-option label="已解决" value="resolved" />
          <el-option label="已忽略" value="ignored" />
        </el-select>
        <span class="oa-cell-sub">{{ filteredIssues.length }} 条</span>
      </div>
    </template>
    <el-table :data="pagedIssues" size="small" border empty-text="暂无数据质量问题">
      <el-table-column prop="title" label="问题" min-width="220" />
      <el-table-column prop="ruleLabel" label="规则" width="160" />
      <el-table-column label="严重度" width="90">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="row.severityLabel === '高' ? 'danger' : row.severityLabel === '中' ? 'warning' : 'info'"
          >
            {{ row.severityLabel || "—" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="entityTypeLabel" label="对象" width="110" />
      <el-table-column label="首次发现" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.firstDetectedAt) }}</template>
      </el-table-column>
      <el-table-column label="处理结果" min-width="160">
        <template #default="{ row }">{{ row.resolutionResult || "—" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'open'">
            <el-button
              v-if="hasPermission('quality', 'update')"
              link
              type="primary"
              @click="openResolve(row)"
            >
              解决
            </el-button>
            <el-button
              v-if="hasPermission('quality', 'update')"
              link
              type="info"
              @click="ignoreIssue(row)"
            >
              忽略
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[10, 20, 50, 100]"
      :total="filteredIssues.length"
      layout="total, sizes, prev, pager, next"
      class="oa-pagination"
    />
  </DataPanel>

  <FormDialog
    v-model="resolveVisible"
    title="解决数据质量问题"
    size="md"
    confirm-text="保存"
    :loading="saving"
    @confirm="submitResolve"
  >
    <p class="oa-mt-0">{{ resolveTarget?.title }}</p>
    <el-form label-position="top">
      <el-form-item label="处理结果" required>
        <el-input v-model="resolveForm.resolutionResult" type="textarea" :rows="3" />
      </el-form-item>
    </el-form>
  </FormDialog>
</template>
