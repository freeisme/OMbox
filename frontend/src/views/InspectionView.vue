<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  INSPECTION_RESULT_OPTIONS,
  INSPECTION_TASK_STATUS_LABELS,
  checkInspectionItem,
  createInspectionTask,
  deleteInspectionRack,
  deleteInspectionSite,
  fetchInspectionRacks,
  fetchInspectionSites,
  fetchInspectionTask,
  fetchInspectionTasks,
  fetchInspectionTemplates,
  saveInspectionRack,
  saveInspectionSite,
  saveInspectionTemplate,
  submitInspectionTask,
  voidInspectionTask,
  type InspectionTemplateItemPayload,
  type InspectionRack,
  type InspectionSite,
  type InspectionTask,
  type InspectionTaskItem,
  type InspectionTemplate,
} from "../api/governance";
import { formatDateTimeText } from "../labels";
import { hasPermission } from "../session";
import { confirmAction } from "../composables/useConfirm";
import { useRoute, useRouter } from "vue-router";
import DataPanel from "../components/ui/DataPanel.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import ToolbarActions from "../components/ui/ToolbarActions.vue";

const router = useRouter();
const route = useRoute();
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

// ---------------------------------------------------------------- 机房 / 机柜 / 巡检模板维护

const siteVisible = ref(false);
const siteEditingId = ref("");
const siteForm = reactive({
  code: "",
  name: "",
  siteType: "server_room",
  location: "",
  remarks: "",
});

const rackVisible = ref(false);
const rackEditingId = ref("");
/** 复制来源名称：非空时对话框标题显示"复制自…"。 */
const rackCopyFrom = ref("");
const rackForm = reactive({
  code: "",
  name: "",
  siteId: "",
  heightU: "42",
  remarks: "",
});

const templateVisible = ref(false);
const templateForm = reactive({
  code: "",
  name: "",
  siteType: "both",
  description: "",
  items: [] as InspectionTemplateItemPayload[],
});

const TEMPLATE_VALUE_TYPES = [
  { value: "ok_fail", label: "正常 / 异常" },
  { value: "ok_fail_na", label: "正常 / 异常 / 不适用" },
  { value: "number", label: "数值" },
  { value: "text", label: "文本" },
];

function emptyTemplateItem(): InspectionTemplateItemPayload {
  return {
    category: "",
    title: "",
    checkMethod: "",
    valueType: "ok_fail",
    unit: "",
    normalRange: "",
    isRequired: true,
  };
}

function openSiteDialog(row?: InspectionSite): void {
  siteEditingId.value = row?.id ?? "";
  siteForm.code = row?.code ?? "";
  siteForm.name = row?.name ?? "";
  siteForm.siteType = row?.siteType || "server_room";
  siteForm.location = row?.location ?? "";
  siteForm.remarks = row?.remarks ?? "";
  siteVisible.value = true;
}

async function submitSite(): Promise<void> {
  if (!siteForm.code.trim() || !siteForm.name.trim()) {
    ElMessage.warning("机房/弱电间编码与名称必填。");
    return;
  }
  saving.value = true;
  try {
    await saveInspectionSite(
      {
        code: siteForm.code.trim(),
        name: siteForm.name.trim(),
        siteType: siteForm.siteType,
        location: siteForm.location.trim(),
        remarks: siteForm.remarks.trim(),
      },
      siteEditingId.value,
    );
    ElMessage.success(siteEditingId.value ? "机房/弱电间已更新。" : "机房/弱电间已创建。");
    siteVisible.value = false;
    siteEditingId.value = "";
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存机房/弱电间失败。");
  } finally {
    saving.value = false;
  }
}

async function removeSite(row: InspectionSite): Promise<void> {
  let reason = "";
  try {
    const { value } = await ElMessageBox.prompt(
      `删除「${row.name}」的原因（会写入操作日志）`,
      "删除机房 / 弱电间",
      { confirmButtonText: "确认删除", cancelButtonText: "取消" },
    );
    reason = String(value ?? "");
  } catch {
    return;
  }
  saving.value = true;
  try {
    await deleteInspectionSite(row.id, reason.trim());
    ElMessage.success("机房/弱电间已删除。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除机房/弱电间失败。");
  } finally {
    saving.value = false;
  }
}

function openRackDialog(row?: InspectionRack): void {
  rackEditingId.value = row?.id ?? "";
  rackCopyFrom.value = "";
  rackForm.code = row?.code ?? "";
  rackForm.name = row?.name ?? "";
  rackForm.siteId = row?.siteId ?? sites.value[0]?.id ?? "";
  rackForm.heightU = String(row?.heightU || 42);
  rackForm.remarks = row?.remarks ?? "";
  if (!sites.value.length) {
    ElMessage.warning("请先创建机房或弱电间，机柜必须归属其中一个。");
  }
  rackVisible.value = true;
}

/**
 * 复制机柜：只沿用非唯一的项（所属机房、高度），机柜编码与名称留空由手工填写，
 * 避免和已有记录撞唯一约束。
 */
function copyRack(row: InspectionRack): void {
  rackEditingId.value = "";
  rackCopyFrom.value = row.name || row.code;
  rackForm.code = "";
  rackForm.name = "";
  rackForm.siteId = row.siteId ?? sites.value[0]?.id ?? "";
  rackForm.heightU = String(row.heightU || 42);
  rackForm.remarks = "";
  rackVisible.value = true;
}

async function submitRack(): Promise<void> {
  if (!rackForm.code.trim() || !rackForm.name.trim() || !rackForm.siteId) {
    ElMessage.warning("机柜编码、名称与所属机房必填。");
    return;
  }
  const heightU = Number(rackForm.heightU);
  if (!Number.isInteger(heightU) || heightU < 1 || heightU > 100) {
    ElMessage.warning("机柜高度必须是 1-100 之间的整数。");
    return;
  }
  saving.value = true;
  try {
    await saveInspectionRack(
      {
        code: rackForm.code.trim(),
        name: rackForm.name.trim(),
        siteId: rackForm.siteId,
        heightU: String(heightU),
        remarks: rackForm.remarks.trim(),
      },
      rackEditingId.value,
    );
    ElMessage.success(rackEditingId.value ? "机柜已更新。" : "机柜已创建。");
    rackVisible.value = false;
    rackEditingId.value = "";
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存机柜失败。");
  } finally {
    saving.value = false;
  }
}

async function removeRack(row: InspectionRack): Promise<void> {
  let reason = "";
  try {
    const { value } = await ElMessageBox.prompt(
      `删除「${row.name}」的原因（会写入操作日志）`,
      "删除机柜",
      { confirmButtonText: "确认删除", cancelButtonText: "取消" },
    );
    reason = String(value ?? "");
  } catch {
    return;
  }
  saving.value = true;
  try {
    await deleteInspectionRack(row.id, reason.trim());
    ElMessage.success("机柜已删除。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除机柜失败。");
  } finally {
    saving.value = false;
  }
}

function openTemplateDialog(): void {
  templateForm.code = "";
  templateForm.name = "";
  templateForm.siteType = "both";
  templateForm.description = "";
  templateForm.items = [emptyTemplateItem()];
  templateVisible.value = true;
}

function addTemplateItem(): void {
  templateForm.items.push(emptyTemplateItem());
}

function removeTemplateItem(index: number): void {
  templateForm.items.splice(index, 1);
  if (!templateForm.items.length) templateForm.items.push(emptyTemplateItem());
}

async function submitTemplate(): Promise<void> {
  if (!templateForm.code.trim() || !templateForm.name.trim()) {
    ElMessage.warning("模板编码与名称必填。");
    return;
  }
  const items = templateForm.items
    .map((item) => ({
      category: item.category.trim(),
      title: item.title.trim(),
      checkMethod: item.checkMethod.trim(),
      valueType: item.valueType || "ok_fail",
      unit: item.unit.trim(),
      normalRange: item.normalRange.trim(),
      isRequired: Boolean(item.isRequired),
    }))
    .filter((item) => item.title);
  if (!items.length) {
    ElMessage.warning("至少需要一项巡检事项。");
    return;
  }
  saving.value = true;
  try {
    await saveInspectionTemplate({
      code: templateForm.code.trim(),
      name: templateForm.name.trim(),
      siteType: templateForm.siteType,
      description: templateForm.description.trim(),
      items,
    });
    ElMessage.success("巡检模板已创建。");
    templateVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存巡检模板失败。");
  } finally {
    saving.value = false;
  }
}

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

onMounted(async () => {
  // 机柜视图等页面可以带 ?tab=sites 直达「机房与机柜」，方便新增机柜。
  const requested = typeof route.query.tab === "string" ? route.query.tab : "";
  if (["tasks", "templates", "sites"].includes(requested)) activeTab.value = requested;
  await load();
});
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
    <ToolbarActions
      v-if="activeTab !== 'tasks'"
      class="oa-mb-3"
      :hint="
        activeTab === 'sites'
          ? '机柜必须归属一个机房或弱电间；先建机房，再建机柜'
          : '模板定义一次检查项，可被机房或机柜的巡检任务反复使用'
      "
    >
      <template v-if="activeTab === 'sites'">
        <el-button
          v-if="hasPermission('inspection_management', 'create')"
          type="primary"
          @click="openSiteDialog()"
        >
          ＋ 新增机房 / 弱电间
        </el-button>
        <el-button
          v-if="hasPermission('inspection_management', 'create')"
          @click="openRackDialog()"
        >
          ＋ 新增机柜
        </el-button>
      </template>
      <el-button
        v-else-if="hasPermission('inspection_management', 'create')"
        type="primary"
        @click="openTemplateDialog()"
      >
        ＋ 新增模板
      </el-button>
    </ToolbarActions>

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
        <template #default="{ row }">
          {{ row.itemCount ?? (row.items ?? []).length }}
        </template>
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
            <el-table-column label="机柜数" width="80">
              <template #default="{ row }">{{ row.rackCount ?? 0 }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openSiteDialog(row)">编辑</el-button>
                <el-button link type="danger" @click="removeSite(row)">删除</el-button>
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
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRackDialog(row)">编辑</el-button>
                <el-button link @click="copyRack(row)">复制</el-button>
                <el-button link type="danger" @click="removeRack(row)">删除</el-button>
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

  <FormDialog
    v-model="siteVisible"
    :title="siteEditingId ? '编辑机房 / 弱电间' : '新增机房 / 弱电间'"
    size="md"
    :loading="saving"
    @confirm="submitSite"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="编码" required>
            <el-input v-model="siteForm.code" placeholder="例如 SR-01" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="名称" required>
            <el-input v-model="siteForm.name" placeholder="例如 一号机房" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="类型" required>
        <el-radio-group v-model="siteForm.siteType">
          <el-radio-button value="server_room">机房</el-radio-button>
          <el-radio-button value="weak_room">弱电间</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="位置">
        <el-input v-model="siteForm.location" placeholder="例如 一号楼 3 层" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="siteForm.remarks" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="rackVisible"
    :title="
      rackEditingId
        ? '编辑机柜'
        : rackCopyFrom
          ? `复制机柜（来自 ${rackCopyFrom}）`
          : '新增机柜'
    "
    size="md"
    :loading="saving"
    @confirm="submitRack"
  >
    <el-alert
      v-if="rackCopyFrom && !rackEditingId"
      type="info"
      :closable="false"
      show-icon
      title="已沿用被复制机柜的所属机房与高度，请填写新的机柜编码与名称。"
      class="oa-mb-2"
    />
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="机柜编码" required>
            <el-input v-model="rackForm.code" placeholder="例如 RACK-A01" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="机柜名称" required>
            <el-input v-model="rackForm.name" placeholder="例如 A 列 01 柜" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="所属机房 / 弱电间" required>
        <el-select v-model="rackForm.siteId" class="oa-full-width" placeholder="请选择机房或弱电间">
          <el-option
            v-for="site in sites"
            :key="site.id"
            :label="`${site.name}（${site.siteType === 'weak_room' ? '弱电间' : '机房'}）`"
            :value="site.id"
          />
        </el-select>
        <div v-if="!sites.length" class="oa-hint">
          还没有机房或弱电间，请先在左侧新增机房。
        </div>
      </el-form-item>
      <el-form-item label="高度（U）" required>
        <el-input-number v-model="rackForm.heightU" :min="1" :max="100" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="rackForm.remarks" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="templateVisible"
    title="新增巡检模板"
    size="lg"
    :loading="saving"
    @confirm="submitTemplate"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="8">
          <el-form-item label="模板编码" required>
            <el-input v-model="templateForm.code" placeholder="例如 TPL-DAILY" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-form-item label="模板名称" required>
            <el-input v-model="templateForm.name" placeholder="例如 机房日常巡检" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-form-item label="适用对象">
            <el-select v-model="templateForm.siteType" class="oa-full-width">
              <el-option label="机房与弱电间通用" value="both" />
              <el-option label="仅机房" value="server_room" />
              <el-option label="仅弱电间" value="weak_room" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="说明">
        <el-input v-model="templateForm.description" placeholder="可选" />
      </el-form-item>
    </el-form>

    <el-divider content-position="left">巡检事项</el-divider>
    <el-table :data="templateForm.items" size="small" border>
      <el-table-column label="分类" width="120">
        <template #default="{ row }">
          <el-input v-model="row.category" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="检查项" min-width="160">
        <template #default="{ row }">
          <el-input v-model="row.title" size="small" placeholder="例如 指示灯状态" />
        </template>
      </el-table-column>
      <el-table-column label="检查方法" min-width="150">
        <template #default="{ row }">
          <el-input v-model="row.checkMethod" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="结论类型" width="140">
        <template #default="{ row }">
          <el-select v-model="row.valueType" size="small">
            <el-option
              v-for="option in TEMPLATE_VALUE_TYPES"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="单位" width="90">
        <template #default="{ row }">
          <el-input v-model="row.unit" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="正常范围" width="120">
        <template #default="{ row }">
          <el-input v-model="row.normalRange" size="small" placeholder="可选" />
        </template>
      </el-table-column>
      <el-table-column label="必填" width="70" align="center">
        <template #default="{ row }">
          <el-checkbox v-model="row.isRequired" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="70" align="center">
        <template #default="{ $index }">
          <el-button link type="danger" @click="removeTemplateItem($index)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-button class="oa-mt-2" @click="addTemplateItem">＋ 添加检查项</el-button>
  </FormDialog>
</template>
