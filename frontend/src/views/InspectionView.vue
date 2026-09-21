<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  INSPECTION_RESULT_OPTIONS,
  INSPECTION_TASK_STATUS_LABELS,
  checkInspectionItem,
  createInspectionTask,
  fetchInspectionRacks,
  fetchInspectionSites,
  fetchInspectionTask,
  fetchInspectionTasks,
  fetchInspectionTemplates,
  submitInspectionTask,
  voidInspectionTask,
  type InspectionRack,
  type InspectionSite,
  type InspectionTask,
  type InspectionTaskItem,
  type InspectionTemplate,
} from "../api/governance";
import { formatDateTimeText } from "../labels";
import { hasPermission } from "../session";
import { confirmAction } from "../composables/useConfirm";
import { useRouter } from "vue-router";
import DataPanel from "../components/ui/DataPanel.vue";
import PageHeader from "../components/ui/PageHeader.vue";

const router = useRouter();
const loading = ref(true);
const saving = ref(false);
const activeTab = ref("tasks");
const tasks = ref<InspectionTask[]>([]);
const templates = ref<InspectionTemplate[]>([]);
const sites = ref<InspectionSite[]>([]);
const racks = ref<InspectionRack[]>([]);

const createVisible = ref(false);
const createForm = reactive({
  templateId: "",
  scopeKind: "site",
  siteId: "",
  rackId: "",
  inspectorUserId: "",
  remarks: "",
});

const detailVisible = ref(false);
const detail = ref<InspectionTask | null>(null);
const itemForms = ref<Record<string, { result: string; notes: string; valueText: string }>>({});
const submitForm = reactive({ abnormalSummary: "", remarks: "" });

const racksOfSite = computed(() =>
  racks.value.filter((rack) => !createForm.siteId || rack.siteId === createForm.siteId),
);

/** 服务端还没记录结论（pending）的检查项。 */
const pendingItems = computed(() =>
  (detail.value?.items ?? []).filter((item) => !item.result || item.result === "pending"),
);

/** 表单内容与服务端不一致（改了但没点保存）的检查项。 */
const unsavedItems = computed(() => (detail.value?.items ?? []).filter((item) => isItemDirty(item)));

function isItemDirty(item: InspectionTaskItem): boolean {
  const form = itemForms.value[item.id];
  if (!form) return false;
  const savedResult = item.result && item.result !== "pending" ? item.result : "";
  return (
    form.result !== savedResult ||
    (form.notes || "").trim() !== (item.notes || "").trim() ||
    (form.valueText || "").trim() !== (item.valueText || "").trim()
  );
}

function statusTagType(status: string): "success" | "warning" | "info" {
  if (status === "submitted") return "success";
  if (status === "running") return "warning";
  return "info";
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [taskList, templateList, siteList, rackList] = await Promise.all([
      fetchInspectionTasks(),
      fetchInspectionTemplates(),
      fetchInspectionSites(),
      fetchInspectionRacks(),
    ]);
    tasks.value = taskList;
    templates.value = templateList;
    sites.value = siteList;
    racks.value = rackList;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "巡检数据加载失败。");
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  createForm.templateId = templates.value[0]?.id ?? "";
  createForm.scopeKind = "site";
  createForm.siteId = sites.value[0]?.id ?? "";
  createForm.rackId = "";
  createForm.inspectorUserId = "";
  createForm.remarks = "";
  createVisible.value = true;
}

async function submitCreate(): Promise<void> {
  if (!createForm.templateId) {
    ElMessage.warning("请选择巡检模板。");
    return;
  }
  if (createForm.scopeKind === "site" && !createForm.siteId) {
    ElMessage.warning("请选择机房。");
    return;
  }
  if (createForm.scopeKind === "rack" && !createForm.rackId) {
    ElMessage.warning("请选择机柜。");
    return;
  }
  saving.value = true;
  try {
    await createInspectionTask({
      templateId: createForm.templateId,
      scopeKind: createForm.scopeKind,
      siteId: createForm.scopeKind === "site" ? createForm.siteId : "",
      rackId: createForm.scopeKind === "rack" ? createForm.rackId : "",
      inspectorUserId: createForm.inspectorUserId,
      remarks: createForm.remarks.trim(),
    });
    ElMessage.success("巡检任务已创建。");
    createVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建失败。");
  } finally {
    saving.value = false;
  }
}

async function openDetail(row: InspectionTask): Promise<void> {
  try {
    const task = await fetchInspectionTask(row.id);
    detail.value = task;
    const forms: Record<string, { result: string; notes: string; valueText: string }> = {};
    (task.items ?? []).forEach((item) => {
      forms[item.id] = {
        // 未检查的项不预选结论，避免"看着是正常但没保存"。
        result: item.result && item.result !== "pending" ? item.result : "",
        notes: item.notes || "",
        valueText: item.valueText || "",
      };
    });
    itemForms.value = forms;
    submitForm.abnormalSummary = task.abnormalSummary || "";
    submitForm.remarks = task.remarks || "";
    detailVisible.value = true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "任务详情加载失败。");
  }
}

async function saveItem(itemId: string): Promise<void> {
  if (!detail.value) return;
  const form = itemForms.value[itemId];
  if (!form) return;
  if (!form.result) {
    ElMessage.warning("请先选择结论（正常 / 异常 / 不适用）再保存。");
    return;
  }
  if (form.result === "fail" && !form.notes.trim()) {
    ElMessage.warning("异常项必须填写说明。");
    return;
  }
  saving.value = true;
  try {
    await checkInspectionItem(detail.value.id, itemId, {
      result: form.result,
      notes: form.notes.trim(),
      valueText: form.valueText.trim(),
    });
    ElMessage.success("检查项已保存。");
    detail.value = await fetchInspectionTask(detail.value.id);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

async function submitTask(): Promise<void> {
  if (!detail.value) return;
  const pending = pendingItems.value;
  if (pending.length) {
    const names = pending
      .slice(0, 5)
      .map((item) => item.title)
      .join("、");
    const dirtyNote = unsavedItems.value.length
      ? `其中 ${unsavedItems.value.length} 项填了内容但没点「保存」。`
      : "";
    ElMessage.warning(
      `还有 ${pending.length} 项未保存结论（${names}${pending.length > 5 ? " 等" : ""}），` +
        `${dirtyNote}请逐项选择结论并点该行「保存」。`,
    );
    return;
  }
  const confirmed = await confirmAction("提交后将生成完整巡检表，确认提交？", {
    title: "提交巡检",
    confirmText: "确认提交",
  });
  if (!confirmed) return;
  saving.value = true;
  try {
    await submitInspectionTask(detail.value.id, {
      abnormalSummary: submitForm.abnormalSummary.trim(),
      remarks: submitForm.remarks.trim(),
    });
    ElMessage.success("巡检任务已提交。");
    detailVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "提交失败。");
  } finally {
    saving.value = false;
  }
}

async function voidTask(row: InspectionTask): Promise<void> {
  let reason = "";
  try {
    const result = await ElMessageBox.prompt("请填写作废原因", "作废巡检任务", {
      confirmButtonText: "确认作废",
      cancelButtonText: "取消",
    });
    reason = result.value ?? "";
  } catch {
    return;
  }
  try {
    await voidInspectionTask(row.id, reason);
    ElMessage.success("任务已作废。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "作废失败。");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="机房巡检"
    description="按机房、弱电间或单个机柜发起巡检，逐项记录结论并在提交后输出完整巡检表"
  >
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <el-button @click="router.push('/rack-layout')">机柜视图</el-button>
      <el-button
        v-if="hasPermission('inspection_management', 'create')"
        type="primary"
        @click="openCreate"
      >
        发起巡检
      </el-button>
    </template>
    <template #filters>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="巡检任务" name="tasks" />
        <el-tab-pane label="巡检模板" name="templates" />
        <el-tab-pane label="机房与机柜" name="sites" />
      </el-tabs>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      v-if="activeTab === 'tasks'"
      :data="tasks"
      size="small"
      border
      empty-text="暂无巡检任务"
    >
      <el-table-column label="编号 / 时间" width="190">
        <template #default="{ row }">
          <div>{{ row.number || row.id }}</div>
          <div class="oa-cell-sub">
            {{ formatDateTimeText(row.startedAt) }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="范围" min-width="180">
        <template #default="{ row }">
          {{ row.rackName || row.siteName || "—" }}
        </template>
      </el-table-column>
      <el-table-column prop="templateName" label="模板" width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">
            {{ INSPECTION_TASK_STATUS_LABELS[row.status] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="inspectorName" label="巡检人" width="110" />
      <el-table-column prop="abnormalSummary" label="异常说明" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看</el-button>
          <el-button
            v-if="hasPermission('inspection_management', 'update') && row.status === 'running'"
            link
            type="danger"
            @click="voidTask(row)"
          >
            作废
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-table
      v-else-if="activeTab === 'templates'"
      :data="templates"
      size="small"
      border
      empty-text="暂无巡检模板"
    >
      <el-table-column prop="name" label="模板名称" min-width="200" />
      <el-table-column prop="code" label="编码" width="140" />
      <el-table-column label="检查项" width="100">
        <template #default="{ row }">{{ (row.items ?? []).length }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">{{ row.isActive ? "是" : "否" }}</template>
      </el-table-column>
    </el-table>

    <template v-else>
      <el-row :gutter="12">
        <el-col :xs="24" :md="12">
          <el-table :data="sites" size="small" border empty-text="暂无机房">
            <el-table-column prop="name" label="机房 / 弱电间" min-width="160" />
            <el-table-column prop="code" label="编码" width="120" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                {{ row.siteType === "weak_room" ? "弱电间" : "机房" }}
              </template>
            </el-table-column>
          </el-table>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-table :data="racks" size="small" border empty-text="暂无机柜">
            <el-table-column prop="name" label="机柜" min-width="140" />
            <el-table-column prop="code" label="编码" width="120" />
            <el-table-column label="U 高" width="80">
              <template #default="{ row }">{{ row.heightU || "—" }}</template>
            </el-table-column>
            <el-table-column label="所属机房" min-width="140">
              <template #default="{ row }">
                {{ sites.find((item) => item.id === row.siteId)?.name || "—" }}
              </template>
            </el-table-column>
          </el-table>
        </el-col>
      </el-row>
    </template>
  </DataPanel>

  <FormDialog
    v-model="createVisible"
    title="发起巡检"
    size="md"
    confirm-text="创建任务"
    :loading="saving"
    @confirm="submitCreate"
  >
    <el-form label-position="top">
      <el-form-item label="巡检模板" required>
        <el-select v-model="createForm.templateId" class="oa-full-width">
          <el-option
            v-for="template in templates"
            :key="template.id"
            :label="template.name"
            :value="template.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="巡检范围" required>
        <el-radio-group v-model="createForm.scopeKind">
          <el-radio-button value="site">按机房</el-radio-button>
          <el-radio-button value="rack">按机柜</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="createForm.scopeKind === 'site'" label="机房" required>
        <el-select v-model="createForm.siteId" class="oa-full-width">
          <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
        </el-select>
      </el-form-item>
      <template v-else>
        <el-form-item label="机房">
          <el-select v-model="createForm.siteId" clearable class="oa-full-width">
            <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="机柜" required>
          <el-select v-model="createForm.rackId" class="oa-full-width">
            <el-option v-for="rack in racksOfSite" :key="rack.id" :label="rack.name" :value="rack.id" />
          </el-select>
        </el-form-item>
      </template>
      <el-form-item label="备注"><el-input v-model="createForm.remarks" type="textarea" :rows="2" /></el-form-item>
    </el-form>
  </FormDialog>

  <DetailDrawer
    v-model="detailVisible"
    :title="detail ? `${detail.number || detail.id} · ${detail.rackName || detail.siteName || ''}` : '巡检任务'"
    size="xl"
  >
    <template v-if="detail">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="状态">
          <el-tag size="small" :type="statusTagType(detail.status)">
            {{ INSPECTION_TASK_STATUS_LABELS[detail.status] || detail.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="模板">{{ detail.templateName || "—" }}</el-descriptions-item>
        <el-descriptions-item label="巡检人">{{ detail.inspectorName || "—" }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">
          {{ formatDateTimeText(detail.startedAt) }}
        </el-descriptions-item>
        <el-descriptions-item label="检查进度">
          共 {{ detail.items?.length ?? 0 }} 项 ·
          <span :style="{ color: pendingItems.length ? 'var(--el-color-warning)' : 'inherit' }">
            未检查 {{ pendingItems.length }}
          </span>
          · 未保存 {{ unsavedItems.length }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">检查项</el-divider>
      <div
        v-for="item in detail.items ?? []"
        :key="item.id"
        class="oa-check-item"
      >
        <div class="oa-flex-between">
          <span>
            <strong>{{ item.title }}</strong>
            <el-tag
              v-if="!item.result || item.result === 'pending'"
              size="small"
              type="warning"
              effect="plain"
              class="oa-ml-1"
            >
              未检查
            </el-tag>
            <el-tag v-else-if="isItemDirty(item)" size="small" type="info" effect="plain" class="oa-ml-1">
              未保存
            </el-tag>
            <el-tag v-else size="small" type="success" effect="plain" class="oa-ml-1">已保存</el-tag>
          </span>
          <span class="oa-cell-sub">
            {{ item.checkMethod || "" }}
          </span>
        </div>
        <div class="oa-flex-row oa-mt-2">
          <el-select
            v-model="itemForms[item.id].result"
            style="width: 130px"
            placeholder="请选择结论"
            :disabled="detail.status !== 'running'"
          >
            <el-option
              v-for="option in INSPECTION_RESULT_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-input
            v-model="itemForms[item.id].valueText"
            placeholder="记录值"
            style="width: 150px"
            :disabled="detail.status !== 'running'"
          />
          <el-input
            v-model="itemForms[item.id].notes"
            placeholder="说明"
            class="oa-flex-1 oa-min-180"
            :disabled="detail.status !== 'running'"
          />
          <el-button
            v-if="detail.status === 'running'"
            :loading="saving"
            @click="saveItem(item.id)"
          >
            保存
          </el-button>
        </div>
      </div>

      <template v-if="detail.status === 'running'">
        <el-divider content-position="left">提交</el-divider>
        <el-form label-position="top">
          <el-form-item label="异常说明">
            <el-input v-model="submitForm.abnormalSummary" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="submitForm.remarks" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <div class="oa-text-right">
          <el-button type="primary" :loading="saving" @click="submitTask">提交巡检</el-button>
        </div>
      </template>
    </template>
  </DetailDrawer>
</template>
