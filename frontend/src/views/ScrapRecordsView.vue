<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  deleteScrapRecord,
  fetchAssetScrapRecords,
  updateScrapRecordNotes,
  scrapConfigLabel,
  scrapModelLabel,
  SCRAP_STATUS_LABEL,
  SCRAP_EXPORT_HEADER,
  scrapRecordsToRows,
  type ScrapRecord,
} from "../api/scrap";
import { hasPermission } from "../session";
import { deviceTypeLabel, statusLabel } from "../labels";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import ExportMenu from "../components/ui/ExportMenu.vue";
import PageHeader from "../components/ui/PageHeader.vue";

const loading = ref(true);
const records = ref<ScrapRecord[]>([]);
const keyword = ref("");
const page = ref(1);
const pageSize = ref(50);
const detail = ref<ScrapRecord | null>(null);
const detailVisible = ref(false);
const canEdit = computed(() => hasPermission("scrap_management", "update"));
const canDelete = computed(() => hasPermission("scrap_management", "delete"));
const noteDialogVisible = ref(false);
const noteSaving = ref(false);
const noteTarget = ref<ScrapRecord | null>(null);
const noteDraft = ref("");

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return records.value;
  return records.value.filter((record) =>
    [
      record.deviceName,
      deviceTypeLabel(record.deviceType),
      scrapModelLabel(record),
      scrapConfigLabel(record),
      record.fixedAssetCode,
      record.snSt,
      record.reason,
      record.notes,
      record.employeeName,
      record.employeeNo,
      record.operatedByName,
    ]
      .join(" ")
      .toLowerCase()
      .includes(key),
  );
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    records.value = await fetchAssetScrapRecords(500);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "报废记录加载失败。");
  } finally {
    loading.value = false;
  }
}

/** 导出当前筛选结果；格式（CSV / Excel）由 ExportMenu 决定。 */
const scrapExportRows = computed(() => scrapRecordsToRows(filtered.value));
const scrapExportName = computed(
  () => `报废记录-${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")}`,
);

function openDetail(record: ScrapRecord): void {
  detail.value = record;
  detailVisible.value = true;
}

function openNoteDialog(record: ScrapRecord): void {
  noteTarget.value = record;
  noteDraft.value = record.notes ?? "";
  noteDialogVisible.value = true;
}

async function saveNote(): Promise<void> {
  const target = noteTarget.value;
  if (!target) return;
  noteSaving.value = true;
  try {
    const updated = await updateScrapRecordNotes(target, noteDraft.value.trim());
    target.notes = updated?.notes ?? noteDraft.value.trim();
    ElMessage.success("备注已保存。");
    noteDialogVisible.value = false;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "备注保存失败。");
  } finally {
    noteSaving.value = false;
  }
}

async function removeRecord(record: ScrapRecord): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除「${record.deviceName || "该设备"}」的报废记录吗？删除后不可恢复，操作日志里会留痕。`,
      "删除报废记录",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    await deleteScrapRecord(record);
    records.value = records.value.filter(
      (item) => !(item.kind === record.kind && item.id === record.id),
    );
    ElMessage.success("报废记录已删除。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除失败。");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="报废记录"
    description="办公终端报废后状态改为「待报废」，不回收、不回补库存，只归档留痕；IT 物资的报废只在「操作日志」里体现"
  >
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <ExportMenu
        :file-name="scrapExportName"
        sheet-name="报废记录"
        :header="SCRAP_EXPORT_HEADER"
        :rows="scrapExportRows"
        label="导出当前结果"
        :disabled="!filtered.length"
      />
    </template>
    <template #filters>
      <FilterBar
        :summary="`显示 ${filtered.length} / ${records.length} 条`"
        :resettable="Boolean(keyword)"
        @reset="keyword = ''; load()"
      >
        <el-input
          v-model="keyword"
          placeholder="设备名、品牌型号、固资编码、SN、人员、报废原因或备注"
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
      empty-text="暂无符合条件的报废记录"
    >
      <el-table-column prop="scrapAt" label="报废时间" width="150" />
      <el-table-column label="设备名称" min-width="180">
        <template #default="{ row }">
          <div>{{ row.deviceName || "—" }}</div>
          <div class="oa-cell-sub">{{ deviceTypeLabel(row.deviceType) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="品牌型号" min-width="160">
        <template #default="{ row }">{{ scrapModelLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="配置" min-width="170">
        <template #default="{ row }">{{ scrapConfigLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="固资编码" width="130">
        <template #default="{ row }">
          <span :class="{ 'oa-muted': !row.fixedAssetCode }">{{ row.fixedAssetCode || "—" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="SN/ST" width="130">
        <template #default="{ row }">
          <span :class="{ 'oa-muted': !row.snSt }">{{ row.snSt || "—" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" type="warning" effect="plain">{{ SCRAP_STATUS_LABEL }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="使用人" width="130">
        <template #default="{ row }">
          <template v-if="row.employeeName">
            <div>{{ row.employeeName }}</div>
            <div class="oa-cell-sub">
              {{ row.employeeNo }}
            </div>
          </template>
          <span v-else class="oa-muted">未登记</span>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="报废原因" min-width="140">
        <template #default="{ row }">{{ row.reason || "未填写" }}</template>
      </el-table-column>
      <el-table-column prop="operatedByName" label="操作人" width="110" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button v-if="canEdit" link type="primary" @click="openNoteDialog(row)">编辑备注</el-button>
          <el-button v-if="canDelete" link type="danger" @click="removeRecord(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[20, 50, 100, 200]"
      :total="filtered.length"
      layout="total, sizes, prev, pager, next"
      class="oa-pagination"
    />
  </DataPanel>

  <FormDialog v-model="noteDialogVisible" title="编辑报废备注" size="sm" :loading="noteSaving" @confirm="saveNote">
    <el-form label-width="70px">
      <el-form-item label="备注">
        <el-input
          v-model="noteDraft"
          type="textarea"
          :rows="4"
          maxlength="500"
          show-word-limit
          placeholder="补充处置说明、存放位置或后续跟进事项（最多 500 字）"
        />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="detailVisible"
    title="报废记录详情"
    size="md"
  >
    <template #footer>
      <el-button @click="detailVisible = false">关闭</el-button>
    </template>
    <el-descriptions v-if="detail" :column="1" border>
      <el-descriptions-item label="报废时间">{{ detail.scrapAt || "—" }}</el-descriptions-item>
      <el-descriptions-item label="设备名称">{{ detail.deviceName || "—" }}</el-descriptions-item>
      <el-descriptions-item label="设备类型">
        {{ deviceTypeLabel(detail.deviceType) }}
      </el-descriptions-item>
      <el-descriptions-item label="品牌型号">{{ scrapModelLabel(detail) }}</el-descriptions-item>
      <el-descriptions-item label="配置">{{ scrapConfigLabel(detail) }}</el-descriptions-item>
      <el-descriptions-item label="固资编码">{{ detail.fixedAssetCode || "—" }}</el-descriptions-item>
      <el-descriptions-item label="SN/ST">{{ detail.snSt || "—" }}</el-descriptions-item>
      <el-descriptions-item label="购置日期">{{ detail.purchaseDate || "—" }}</el-descriptions-item>
      <el-descriptions-item label="登记日期">{{ detail.registeredDate || "—" }}</el-descriptions-item>
      <el-descriptions-item label="使用人">
        {{ detail.employeeName ? `${detail.employeeName} ${detail.employeeNo}`.trim() : "—" }}
      </el-descriptions-item>
      <el-descriptions-item label="报废前状态">
        {{ detail.previousStatus ? statusLabel(detail.previousStatus) : "—" }}
      </el-descriptions-item>
      <el-descriptions-item label="当前状态">
        <el-tag size="small" type="warning" effect="plain">{{ SCRAP_STATUS_LABEL }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="报废原因">{{ detail.reason || "—" }}</el-descriptions-item>
      <el-descriptions-item label="说明">{{ detail.notes || "—" }}</el-descriptions-item>
      <el-descriptions-item label="操作人">{{ detail.operatedByName || "—" }}</el-descriptions-item>
    </el-descriptions>
  </FormDialog>
</template>
