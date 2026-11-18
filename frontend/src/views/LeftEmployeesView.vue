<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api/client";
import { companyScope } from "../companyScope";
import { hasPermission } from "../session";
import {
  loadDirectoryData,
  offboardDeviceActionText,
  type LeftDeviceRow,
  type LeftEmployeeRow,
} from "../api/directory";
import DataPanel from "../components/ui/DataPanel.vue";
import ExportMenu from "../components/ui/ExportMenu.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import { asText } from "../api/exports";
import {
  resolveLeftException,
  revokeLeftException,
  updateLeftEmployeeRemark,
} from "../api/directory";
import { formatDateTimeText } from "../labels";

const router = useRouter();
const loading = ref(true);
const rows = ref<LeftEmployeeRow[]>([]);
const keyword = ref("");
const detail = ref<LeftEmployeeRow | null>(null);
/** 异常项结清弹窗。 */
const resolveDialog = ref<{ visible: boolean; row: LeftEmployeeRow | null }>({ visible: false, row: null });
const resolveForm = ref({ resolution: "recovered", note: "" });
const resolving = ref(false);
const canUpdateEmployees = computed(() => hasPermission("employees", "update"));

const exceptionItems = computed(() =>
  (detail.value?.devices ?? []).filter((item) => item.action === "exception"),
);

const RESOLUTION_OPTIONS = [
  { value: "recovered", label: "已找回" },
  { value: "scrapped", label: "已报废" },
  { value: "compensated", label: "已赔付" },
  { value: "other", label: "其他" },
];
const detailVisible = ref(false);
const page = ref(1);
const pageSize = ref(50);

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return rows.value;
  return rows.value.filter((row) =>
    [row.name, row.employeeNo, row.orgPath, row.department, row.leaveInfo, row.leaveRemark]
      .join(" ")
      .toLowerCase()
      .includes(key),
  );
});

type SortOrder = "ascending" | "descending" | null;
const sortKey = ref("");
const sortOrder = ref<SortOrder>(null);

const sorted = computed(() => {
  const list = filtered.value.slice();
  if (!sortKey.value || !sortOrder.value) return list;
  const key = sortKey.value;
  const sign = sortOrder.value === "descending" ? -1 : 1;
  list.sort((a, b) => {
    const av = String((a as unknown as Record<string, unknown>)[key] ?? "");
    const bv = String((b as unknown as Record<string, unknown>)[key] ?? "");
    return sign * av.localeCompare(bv, "zh-Hans-CN");
  });
  return list;
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return sorted.value.slice(start, start + pageSize.value);
});

function onSortChange(payload: { prop: string; order: SortOrder }): void {
  sortKey.value = payload.order ? payload.prop : "";
  sortOrder.value = payload.order;
  page.value = 1;
}

async function removeRow(row: LeftEmployeeRow): Promise<void> {
  const ok = await ElMessageBox.confirm(
    "确定删除离职档案「" + row.name + "」吗？删除后不可恢复（不影响在职人员）。",
    "删除离职档案",
    { type: "warning" },
  ).catch(() => false);
  if (!ok) return;
  try {
    await api("/api/left-employees/" + encodeURIComponent(row.id), { method: "DELETE" });
    rows.value = rows.value.filter((item) => item.id !== row.id);
    ElMessage.success("离职档案已删除。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除离职档案失败。");
  }
}

const summary = computed(() => `显示 ${filtered.value.length} / ${rows.value.length} 人`);

function deviceSummary(devices: LeftDeviceRow[] | undefined): string {
  const list = devices ?? [];
  if (!list.length) return "暂无离职设备快照";
  return list
    .map((device) => {
      const extra = [
        device.detail,
        Number(device.quantity ?? 0) > 1 ? `x${device.quantity}` : "",
        offboardDeviceActionText(device),
      ]
        .filter(Boolean)
        .join(" · ");
      return extra ? `${device.label ?? "设备"}（${extra}）` : device.label ?? "设备";
    })
    .join("；");
}

function openDetail(row: LeftEmployeeRow): void {
  detail.value = row;
  detailVisible.value = true;
}

const remarkDialogVisible = ref(false);
const remarkSaving = ref(false);
const remarkTarget = ref<LeftEmployeeRow | null>(null);
const remarkDraft = ref("");

/** 去处理：设备跳办公终端并带上搜索词，物资跳物资管理。 */
function goHandleException(row: { label?: string; category?: string }): void {
  const label = String(row.label ?? "").trim();
  if (row.category === "computer" && label) {
    void router.push({ path: "/computers", query: { keyword: label } });
    return;
  }
  void router.push({ path: "/inventory-hub", query: label ? { keyword: label } : {} });
}

function openResolveDialog(row: { resolved?: boolean }): void {
  if (row.resolved) return;
  resolveForm.value = { resolution: "recovered", note: "" };
  resolveDialog.value = { visible: true, row: detail.value };
  pendingExceptionIndex.value = Number((row as { exceptionIndex?: number }).exceptionIndex ?? -1);
}

const pendingExceptionIndex = ref(-1);

async function submitResolve(): Promise<void> {
  const archive = resolveDialog.value.row;
  const index = pendingExceptionIndex.value;
  if (!archive || index < 0) return;
  resolving.value = true;
  try {
    await resolveLeftException(archive.id, index, {
      resolution: resolveForm.value.resolution,
      note: resolveForm.value.note,
    });
    ElMessage.success("已结清。");
    resolveDialog.value.visible = false;
    await refreshDetail();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "结清失败。");
  } finally {
    resolving.value = false;
  }
}

async function revokeException(row: { exceptionIndex?: number }): Promise<void> {
  const archive = detail.value;
  const index = Number(row.exceptionIndex ?? -1);
  if (!archive || index < 0) return;
  try {
    await ElMessageBox.confirm("撤销后该项会重新变成「待结清」，确定继续？", "撤销结清", { type: "warning" });
  } catch {
    return;
  }
  try {
    await revokeLeftException(archive.id, index);
    ElMessage.success("已撤销结清。");
    await refreshDetail();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "撤销失败。");
  }
}

async function refreshDetail(): Promise<void> {
  const id = detail.value?.id ?? "";
  if (!id) return;
  try {
    const data = await loadDirectoryData(true);
    rows.value = data.leftEmployees;
    const fresh = rows.value.find((item) => item.id === id);
    if (fresh) detail.value = fresh;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "刷新失败。");
  }
}

function openRemarkDialog(row: LeftEmployeeRow): void {
  remarkTarget.value = row;
  remarkDraft.value = row.leaveRemark ?? "";
  remarkDialogVisible.value = true;
}

async function saveRemark(): Promise<void> {
  const target = remarkTarget.value;
  if (!target) return;
  remarkSaving.value = true;
  try {
    await updateLeftEmployeeRemark(target.id, remarkDraft.value.trim());
    target.leaveRemark = remarkDraft.value.trim();
    ElMessage.success("离职备注已保存。");
    remarkDialogVisible.value = false;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "离职备注保存失败。");
  } finally {
    remarkSaving.value = false;
  }
}

function resetFilters(): void {
  keyword.value = "";
}

/** 离职人员导出列：与列表展示字段一致，附带设备快照与异常项。 */
const LEFT_EMPLOYEE_EXPORT_HEADER = [
  "人员编号",
  "姓名",
  "原组织路径",
  "部门",
  "岗位",
  "邮箱",
  "手机号",
  "离职日期",
  "离职原因",
  "离职备注",
  "归档时间",
  "资产数量",
  "异常待处理数",
  "离职设备快照",
];

const leftEmployeeExportRows = computed(() =>
  sorted.value.map((row) => [
    asText(row.employeeNo),
    asText(row.name),
    asText(row.orgPath),
    asText(row.department),
    asText(row.position),
    asText(row.email),
    asText(row.mobile),
    asText(row.leaveDate),
    asText(row.leaveInfo),
    asText(row.leaveRemark),
    asText(formatDateTimeText(row.archivedAt)),
    asText((row.devices ?? []).length),
    asText(row.exceptionCount ?? 0),
    asText(deviceSummary(row.devices)),
  ]),
);

const leftEmployeeExportName = computed(
  () => "离职人员-" + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, ""),
);

async function loadRows(): Promise<void> {
  loading.value = true;
  try {
    const data = await loadDirectoryData();
    rows.value = data.leftEmployees;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "离职人员数据加载失败。");
  } finally {
    loading.value = false;
  }
}

watch(
  () => companyScope.companyId,
  () => {
    page.value = 1;
    void loadRows();
  },
);

onMounted(loadRows);
</script>

<template>
  <PageHeader
    title="离职人员"
    description="离职人员已从组织树移出，保留离职时间、说明、备注与离职时设备快照"
  >
    <template #actions>
      <el-button @click="loadRows">刷新</el-button>
      <ExportMenu
        :file-name="leftEmployeeExportName"
        sheet-name="离职人员"
        :header="LEFT_EMPLOYEE_EXPORT_HEADER"
        :rows="leftEmployeeExportRows"
        label="导出当前结果"
        :disabled="!sorted.length"
      />
      <el-button @click="router.push('/employees')">返回使用人员</el-button>
    </template>
    <template #filters>
      <FilterBar :summary="summary" :resettable="Boolean(keyword)" @reset="resetFilters">
        <el-input
          v-model="keyword"
          placeholder="搜索姓名、编号、组织、部门或离职说明"
          clearable
          style="max-width: 360px"
        />
      </FilterBar>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      :data="paged"
      size="small"
      border
      stripe
      empty-text="暂无离职人员记录"
      @sort-change="onSortChange"
    >
      <el-table-column label="人员" prop="name" min-width="150" sortable="custom">
        <template #default="{ row }">
          <div>{{ row.name }}</div>
          <div class="oa-cell-sub">{{ row.employeeNo }}</div>
        </template>
      </el-table-column>
      <el-table-column label="原组织 / 部门" prop="orgPath" min-width="220" sortable="custom">
        <template #default="{ row }">
          <div>{{ row.orgPath || "—" }}</div>
          <div class="oa-cell-sub">{{ row.department || "未填写部门" }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="position" label="岗位" width="110" sortable="custom" />
      <el-table-column prop="leaveDate" label="离职日期" width="115" sortable="custom" />
      <el-table-column
        prop="archivedAt"
        label="归档时间"
        width="140"
        sortable="custom"
      >
        <template #default="{ row }">{{ formatDateTimeText(row.archivedAt) }}</template>
      </el-table-column>
      <el-table-column label="离职设备快照" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ deviceSummary(row.devices) }}</template>
      </el-table-column>
      <el-table-column label="异常项" width="150">
        <template #default="{ row }">
          <el-tooltip
            v-if="Number(row.exceptionOpenCount ?? 0) > 0"
            :content="(row.exceptionOpenLabels ?? []).join('、')"
            placement="top"
          >
            <el-tag type="danger" size="small">
              待结清 {{ row.exceptionOpenCount }}/{{ row.exceptionCount }}
            </el-tag>
          </el-tooltip>
          <el-tooltip
            v-else-if="row.exceptionCount"
            :content="(row.exceptionLabels ?? []).join('、')"
            placement="top"
          >
            <el-tag type="info" size="small">异常已结清 {{ row.exceptionCount }}</el-tag>
          </el-tooltip>
          <span v-else class="oa-cell-sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
          <el-button
            v-if="hasPermission('employees', 'update')"
            link
            type="primary"
            @click="openRemarkDialog(row)"
          >
            编辑备注
          </el-button>
          <el-button
            v-if="hasPermission('employees', 'delete')"
            link
            type="danger"
            @click="removeRow(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="filtered.length"
        layout="total, sizes, prev, pager, next"
        class="oa-pagination"
      />
    </template>
  </DataPanel>

  <FormDialog
    v-model="remarkDialogVisible"
    title="编辑离职备注"
    size="sm"
    :loading="remarkSaving"
    @confirm="saveRemark"
  >
    <el-form label-width="70px">
      <el-form-item label="备注">
        <el-input
          v-model="remarkDraft"
          type="textarea"
          :rows="4"
          maxlength="500"
          show-word-limit
          placeholder="补充交接情况、遗留事项等（最多 500 字）"
        />
      </el-form-item>
    </el-form>
  </FormDialog>

  <DetailDrawer v-model="detailVisible" :title="`${detail?.name ?? ''} · 离职人员档案`" size="md">
    <el-descriptions v-if="detail" :column="1" border>
      <el-descriptions-item label="人员编号">{{ detail.employeeNo || "—" }}</el-descriptions-item>
      <el-descriptions-item label="人员姓名">{{ detail.name || "—" }}</el-descriptions-item>
      <el-descriptions-item label="原组织路径">{{ detail.orgPath || "—" }}</el-descriptions-item>
      <el-descriptions-item label="部门">{{ detail.department || "—" }}</el-descriptions-item>
      <el-descriptions-item label="岗位">{{ detail.position || "—" }}</el-descriptions-item>
      <el-descriptions-item label="离职日期">{{ detail.leaveDate || "—" }}</el-descriptions-item>
      <el-descriptions-item label="归档时间">
        {{ formatDateTimeText(detail.archivedAt) }}
      </el-descriptions-item>
      <el-descriptions-item label="手机号">{{ detail.mobile || "—" }}</el-descriptions-item>
      <el-descriptions-item label="离职信息">{{ detail.leaveInfo || "—" }}</el-descriptions-item>
      <el-descriptions-item label="备注">{{ detail.leaveRemark || "—" }}</el-descriptions-item>
    </el-descriptions>
    <div v-if="detail?.exceptionCount" class="oa-drawer-section">
      <h4>异常项（未结清 {{ detail.exceptionOpenCount ?? 0 }} / 共 {{ detail.exceptionCount }}）</h4>
      <el-table :data="exceptionItems" size="small" border>
        <el-table-column prop="label" label="资产" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.resolved ? 'success' : 'danger'" size="small">
              {{ row.resolved ? "已结清" : "待结清" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处理方式" width="120">
          <template #default="{ row }">
            {{ row.resolutionLabel || "—" }}
          </template>
        </el-table-column>
        <el-table-column label="处理人 / 时间" width="170">
          <template #default="{ row }">
            <span v-if="row.resolved">{{ row.resolvedBy }} · {{ row.resolvedAt }}</span>
            <span v-else class="oa-hint">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="resolutionNote" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goHandleException(row)">去处理</el-button>
            <el-button
              v-if="canUpdateEmployees && !row.resolved"
              link
              type="primary"
              @click="openResolveDialog(row)"
            >
              结清
            </el-button>
            <el-button
              v-if="canUpdateEmployees && row.resolved"
              link
              type="warning"
              @click="revokeException(row)"
            >
              撤销结清
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="oa-drawer-section">
      <h4>离职时设备快照（{{ (detail?.devices ?? []).length }} 条）</h4>
      <el-descriptions v-if="(detail?.devices ?? []).length" :column="1" border size="small">
        <el-descriptions-item
          v-for="(device, index) in detail?.devices ?? []"
          :key="index"
          :label="device.label || `设备 ${index + 1}`"
        >
          {{ [device.detail, Number(device.quantity ?? 0) > 1 ? `x${device.quantity}` : "", offboardDeviceActionText(device)].filter(Boolean).join(" · ") || "—" }}
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="暂无离职设备快照" :image-size="60" />
    </div>
  </DetailDrawer>

  <el-dialog v-model="resolveDialog.visible" title="结清异常项" width="480px">
    <el-form label-width="96px">
      <el-form-item label="处理方式">
        <el-select v-model="resolveForm.resolution" class="oa-full-width">
          <el-option v-for="item in RESOLUTION_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="resolveForm.note" type="textarea" :rows="3" placeholder="如：已找回，存放于 A 库；或已按 8 折赔付" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="resolveDialog.visible = false">取消</el-button>
      <el-button type="primary" :loading="resolving" @click="submitResolve">确认结清</el-button>
    </template>
  </el-dialog>
</template>
